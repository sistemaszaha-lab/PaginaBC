from pathlib import Path

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import (
    RequestFactory,
    SimpleTestCase,
    TestCase,
    override_settings,
)

from audit_performance_readonly import (
    MarkupMetrics,
    analyze_form_fragments,
    percentile,
    summarize_runs,
)

from .performance import PerformanceDiagnosticsMiddleware, _safe_sql_fingerprint


PROJECT_ROOT = Path(__file__).resolve().parent.parent


class PerformanceDiagnosticsTests(SimpleTestCase):
    def test_sql_fingerprint_redacts_literals(self):
        value = _safe_sql_fingerprint(
            "SELECT * FROM auth_user WHERE email='persona@example.com' AND id=123"
        )
        self.assertNotIn("persona@example.com", value)
        self.assertNotIn("123", value)
        self.assertIn("email=?", value)
        self.assertIn("id=?", value)

    @override_settings(PERFORMANCE_DEBUG=True, PERFORMANCE_DEBUG_TOP_QUERIES=5)
    def test_enabled_logs_request_summary_without_sensitive_request_data(self):
        middleware = PerformanceDiagnosticsMiddleware(
            lambda request: HttpResponse("<html>ok</html>", content_type="text/html")
        )
        request = RequestFactory().get(
            "/diagnostico/?token=no-registrar",
            HTTP_COOKIE="sessionid=no-registrar",
        )

        with self.assertLogs("performance", level="INFO") as captured:
            response = middleware(request)

        output = "\n".join(captured.output)
        self.assertEqual(response.status_code, 200)
        self.assertIn("GET /diagnostico/", output)
        self.assertIn("status=200", output)
        self.assertIn("html_bytes=15", output)
        self.assertNotIn("token=no-registrar", output)
        self.assertNotIn("sessionid=no-registrar", output)

    @override_settings(PERFORMANCE_DEBUG=False)
    def test_disabled_does_not_emit_performance_log(self):
        middleware = PerformanceDiagnosticsMiddleware(
            lambda request: HttpResponse("ok", content_type="text/plain")
        )
        request = RequestFactory().get("/diagnostico/")

        with self.assertNoLogs("performance", level="INFO"):
            response = middleware(request)

        self.assertEqual(response.status_code, 200)


class ReadOnlyAuditorTests(SimpleTestCase):
    def test_form_analysis_groups_dynamic_actions_without_exposing_csrf(self):
        html = """
        <form method="post" action="/clientes/123/eliminar/">
          <input type="hidden" name="csrfmiddlewaretoken" value="secreto-uno">
          <input type="hidden" name="estado" value="Activo">
          <button type="submit">Eliminar</button>
        </form>
        <form method="post" action="/clientes/456/eliminar/">
          <input type="hidden" name="csrfmiddlewaretoken" value="secreto-dos">
          <button type="submit">Eliminar</button>
        </form>
        """

        analysis = analyze_form_fragments(html)
        serialized = str(analysis)

        self.assertEqual(analysis["forms"], 2)
        self.assertEqual(analysis["csrf_inputs"], 2)
        self.assertEqual(len(analysis["groups"]), 1)
        self.assertIn("/clientes/<id>/eliminar/", serialized)
        self.assertNotIn("secreto-uno", serialized)
        self.assertNotIn("secreto-dos", serialized)
        self.assertGreater(analysis["unwrap_savings_bytes"], 0)

    def test_markup_counts_form_controls_without_recording_values(self):
        markup = MarkupMetrics()
        markup.feed(
            """
            <form method="post">
              <input type="hidden" name="csrfmiddlewaretoken" value="no-guardar">
              <input type="hidden" name="estado" value="Pendiente">
              <button type="submit">Guardar</button>
            </form>
            """
        )

        self.assertEqual(markup.forms, 1)
        self.assertEqual(markup.hidden_inputs, 2)
        self.assertEqual(markup.csrf_inputs, 1)
        self.assertEqual(markup.buttons, 1)

    def test_markup_recognizes_all_real_kanban_column_classes(self):
        markup = MarkupMetrics()
        markup.feed(
            """
            <div class="panel-cotizaciones-col" data-estado="uno">
              <article data-panel-cotizacion-card="1"></article>
            </div>
            <div class="kanban-col" data-estado="dos">
              <article data-garantia-card="1"></article>
            </div>
            <div class="panel-operaciones-col" data-estado="tres">
              <article data-panel-operacion-card="1"></article>
            </div>
            <div class="columna-drop" data-estado="cuatro">
              <article data-cuenta-card="1"></article>
            </div>
            <button data-cuenta-load-more="1"></button>
            <button data-panel-cotizacion-load-more="1"></button>
            <button data-garantia-load-more="1"></button>
            <button data-operacion-load-more="1"></button>
            """
        )

        self.assertEqual(markup.kanban_columns, 4)
        self.assertEqual(markup.kanban_cards, 4)
        self.assertEqual(markup.load_more_buttons, 4)
        self.assertEqual(
            [column["cards"] for column in markup.cards_per_column],
            [1, 1, 1, 1],
        )

    def test_robust_statistics_trim_fastest_and_slowest(self):
        runs = [
            {
                "total_ms": value,
                "queries": 5,
                "sql_ms": 1,
                "html_bytes": 100,
                "records": 1,
                "forms": 1,
                "inline_scripts": 1,
                "inline_script_bytes": 10,
                "inline_style_bytes": 20,
                "embedded_json_bytes": 0,
                "local_js_files": 1,
                "kanban_columns": 1,
                "kanban_cards": 1,
            }
            for value in (1, 2, 3, 4, 100)
        ]

        summary = summarize_runs(runs)

        self.assertAlmostEqual(percentile([1, 2, 3, 4, 100], 90), 61.6)
        self.assertEqual(summary["median_ms"], 3)
        self.assertEqual(summary["trimmed_mean_ms"], 3)
        self.assertEqual(summary["trimmed_median_ms"], 3)


class BaseStaticAssetsTests(SimpleTestCase):
    def setUp(self):
        self.base_template = (
            PROJECT_ROOT / "templates" / "base.html"
        ).read_text(encoding="utf-8-sig")
        self.base_css = (
            PROJECT_ROOT / "solicitudes" / "static" / "css" / "base.css"
        ).read_text(encoding="utf-8")
        self.theme_js = (
            PROJECT_ROOT
            / "solicitudes"
            / "static"
            / "js"
            / "base-theme.js"
        ).read_text(encoding="utf-8")
        self.base_js = (
            PROJECT_ROOT / "solicitudes" / "static" / "js" / "base.js"
        ).read_text(encoding="utf-8")

    def test_base_referencia_assets_sin_css_o_js_funcional_inline(self):
        self.assertIn("{% static 'css/base.css' %}", self.base_template)
        self.assertIn(
            "{% static 'js/base-theme.js' %}",
            self.base_template,
        )
        self.assertIn("{% static 'js/base.js' %}", self.base_template)
        self.assertNotIn("<style", self.base_template)
        self.assertNotIn("<script>", self.base_template)

    def test_orden_de_assets_y_bloques_django_se_conserva(self):
        theme = self.base_template.index("js/base-theme.js")
        bootstrap_css = self.base_template.index(
            "bootstrap@5.3.2/dist/css/bootstrap.min.css"
        )
        base_css = self.base_template.index("css/base.css")
        content = self.base_template.index(
            "{% block content %}{% endblock %}"
        )
        base_js = self.base_template.index("js/base.js")

        self.assertLess(theme, bootstrap_css)
        self.assertLess(bootstrap_css, base_css)
        self.assertLess(content, base_js)
        self.assertIn(
            "{% block title %}Sistema{% endblock %}",
            self.base_template,
        )

    def test_sidebar_header_y_logout_se_conservan(self):
        for fragment in (
            'class="sidebar"',
            'class="header"',
            'id="sidebarToggle"',
            'id="themeToggle"',
            "{% url 'logout' %}",
            'class="sidebar-logout-btn"',
        ):
            self.assertIn(fragment, self.base_template)

    def test_css_conserva_tema_responsive_y_selectores_globales(self):
        for selector in (
            ":root",
            "html.dark",
            '[data-bs-theme="dark"]',
            ".sidebar",
            ".sidebar-collapsed",
            ".sidebar-open",
            ".header",
            ".content",
            ".table-responsive",
            ".sidebar-logout-btn",
            "@media (max-width: 768px)",
            "@media (max-width: 480px)",
        ):
            self.assertIn(selector, self.base_css)

    def test_javascript_conserva_tema_sidebar_y_normalizacion(self):
        self.assertIn('localStorage.getItem("theme")', self.theme_js)
        self.assertIn('html.classList.toggle("dark"', self.theme_js)
        for fragment in (
            'document.getElementById("themeToggle")',
            'document.getElementById("sidebarToggle")',
            'localStorage.setItem("theme", theme)',
            'localStorage.setItem("sidebarCollapsed"',
            'body.classList.toggle("sidebar-open")',
            'body.classList.toggle("sidebar-collapsed")',
            'document.addEventListener("input"',
            "js-uppercase-cliente",
        ):
            self.assertIn(fragment, self.base_js)

    def test_assets_no_contienen_sintaxis_django_o_datos_dinamicos(self):
        combined = self.theme_js + self.base_js
        for forbidden in ("{%", "{{", "csrfmiddlewaretoken"):
            self.assertNotIn(forbidden, combined)
        self.assertEqual(
            self.base_js.count('toggleBtn.addEventListener("click"'),
            1,
        )
        self.assertEqual(
            self.base_js.count('sidebarToggle.addEventListener("click"'),
            1,
        )
        self.assertEqual(
            self.base_js.count('document.addEventListener("input"'),
            1,
        )


@override_settings(
    SESSION_ENGINE="django.contrib.sessions.backends.signed_cookies"
)
class BaseAssetsRouteCompatibilityTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.admin = get_user_model().objects.create_superuser(
            username="fase10_admin",
            password="fase10-pass",
            email="fase10@example.com",
        )

    def setUp(self):
        self.client.force_login(self.admin)

    def test_rutas_autenticadas_referencian_assets_globales(self):
        paths = (
            "/",
            "/solicitudes/",
            "/cotizaciones/",
            "/referencias/",
            "/clientes/",
            "/usuarios/",
            "/panel-cotizaciones/",
            "/garantias/",
            "/operaciones/",
            "/cuenta-gastos/",
            "/incidencias/",
        )
        for path in paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/css/base.css")
                self.assertContains(response, "/static/js/base-theme.js")
                self.assertContains(response, "/static/js/base.js")

    def test_dependencias_especificas_de_modulos_se_conservan(self):
        expected = {
            "/": ("chart.js@4.4.2",),
            "/panel-cotizaciones/": (
                "bootstrap.bundle.min.js",
                "Sortable.min.js",
                "/static/panel_cotizaciones/js/panel.js",
            ),
            "/garantias/": (
                "bootstrap.bundle.min.js",
                "Sortable.min.js",
                "/static/js/kanban-quick-edit.js",
                "/static/garantias/js/panel_garantias.js",
            ),
            "/operaciones/": (
                "bootstrap.bundle.min.js",
                "Sortable.min.js",
                "/static/operaciones/js/panel_operaciones.js",
            ),
            "/cuenta-gastos/": (
                "bootstrap.bundle.min.js",
                "Sortable.min.js",
                "/static/cuenta_gastos/js/panel_cuenta_gastos.js",
            ),
            "/incidencias/": (
                "tabulator.min.js",
                "/static/incidencias/js/incidencias_tabla.js",
            ),
        }
        for path, fragments in expected.items():
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                for fragment in fragments:
                    self.assertContains(response, fragment)

    def test_anonimo_conserva_redireccion_a_login(self):
        self.client.logout()
        response = self.client.get("/solicitudes/")
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_ejecutivo_conserva_assets_y_permisos(self):
        executive = get_user_model().objects.create_user(
            username="fase10_ejecutivo",
            password="fase10-pass",
        )
        self.client.force_login(executive)
        for path in (
            "/",
            "/solicitudes/",
            "/cotizaciones/",
            "/referencias/",
            "/clientes/",
            "/panel-cotizaciones/",
            "/garantias/",
            "/operaciones/",
            "/cuenta-gastos/",
            "/incidencias/",
        ):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertContains(response, "/static/css/base.css")
                self.assertContains(response, "/static/js/base.js")

        users_response = self.client.get("/usuarios/")
        self.assertEqual(users_response.status_code, 403)
