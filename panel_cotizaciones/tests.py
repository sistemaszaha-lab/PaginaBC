import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.middleware.csrf import get_token
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente

from .forms import PanelCotizacionCreateForm
from .models import PanelCotizacion

User = get_user_model()
PANEL_JS_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "panel_cotizaciones"
    / "js"
    / "panel.js"
)


class PanelCotizacionClienteNormalizacionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_user", password="panel123", first_name="Panel"
        )

    def test_creacion_normaliza_cliente(self):
        cliente = Cliente.objects.create(nombre=" empresa vargas ")
        form = PanelCotizacionCreateForm(
            data={
                "titulo": "Tablero",
                "descripcion": "Descripcion",
                "cliente": cliente.pk,
                "prioridad": "MEDIA",
                "fecha_vencimiento": date(2026, 2, 1).isoformat(),
                "asignados": [],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        panel = form.save(commit=False)
        panel.creado_por = self.user
        panel.estado = PanelCotizacion.Estado.REQUERIMIENTO
        panel.save()

        self.assertEqual(panel.cliente, "EMPRESA VARGAS")

    def test_edicion_normaliza_cliente_y_conserva_caracteres(self):
        panel = PanelCotizacion.objects.create(
            titulo="Tablero",
            descripcion="Descripcion",
            cliente="",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        panel.cliente = " mexico  & cia. - log / sur "
        panel.save()
        panel.refresh_from_db()

        self.assertEqual(panel.cliente, "MEXICO & CIA. - LOG / SUR")


class PanelCotizacionAccessAndRenderingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="panel_admin", password="panel123", email="admin@example.com"
        )
        self.ejecutivo = User.objects.create_user(
            username="panel_exec", password="panel123", first_name="Ejecutivo"
        )
        self.panel = PanelCotizacion.objects.create(
            titulo="Carga inicial",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.admin,
        )

    def test_panel_carga_para_admin_y_ejecutivo(self):
        client = Client()
        client.force_login(self.admin)
        admin_response = client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "Panel de Cotizaciones")

        client = Client()
        client.force_login(self.ejecutivo)
        exec_response = client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(exec_response.status_code, 200)
        self.assertContains(exec_response, "Carga inicial")

    def test_panel_requiere_autenticacion(self):
        response = self.client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(response.status_code, 302)

    def test_detalle_drawer_renderiza(self):
        client = Client()
        client.force_login(self.ejecutivo)
        response = client.get(
            reverse("panel_cotizaciones:detalle_modal", args=[self.panel.pk]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carga inicial")
        self.assertContains(response, "CLIENTE UNO")


class PanelCotizacionFiltroTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_filter", password="panel123", first_name="Panel"
        )
        self.asignado = User.objects.create_user(
            username="panel_asignado", password="panel123", first_name="Asignado"
        )
        self.otro_asignado = User.objects.create_user(
            username="panel_otro_asignado", password="panel123", first_name="Otro"
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.panel = PanelCotizacion.objects.create(
            titulo="Cotizacion Visible",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.panel.asignados.add(self.asignado)
        self.panel_2 = PanelCotizacion.objects.create(
            titulo="Cotizacion Dos",
            descripcion="Descripcion",
            cliente="CLIENTE DOS",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.panel_2.asignados.add(self.otro_asignado)
        self.panel_3 = PanelCotizacion.objects.create(
            titulo="Sin Asignado",
            descripcion="Descripcion",
            cliente="CLIENTE TRES",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_panel_filtra_por_usuario(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": str(self.asignado.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertNotContains(response, "Cotizacion Dos")
        self.assertNotContains(response, "Sin Asignado")

    def test_panel_filtra_por_multiples_usuarios(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": [str(self.asignado.id), str(self.otro_asignado.id)]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertContains(response, "Cotizacion Dos")
        self.assertNotContains(response, "Sin Asignado")

    def test_panel_ignora_valores_vacios_en_filtro(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": ["", str(self.asignado.id)]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertNotContains(response, "Cotizacion Dos")


@override_settings(PERFORMANCE_DEBUG=False)
class PanelCotizacionCargaProgresivaTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_fase7b",
            password="panel123",
            first_name="Fase",
        )
        self.asignado = User.objects.create_user(
            username="panel_fase7b_asignado",
            password="panel123",
            first_name="Asignado",
        )
        self.client.force_login(self.user)
        self.base = PanelCotizacion.objects.create(
            titulo="Base 7B",
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def _bulk(self, cantidad, estado=None):
        estado = estado or PanelCotizacion.Estado.REQUERIMIENTO
        base = timezone.now() + timedelta(minutes=1)
        PanelCotizacion.objects.bulk_create(
            [
                PanelCotizacion(
                    titulo=f"Fase 7B {estado} {index:03d}",
                    estado=estado,
                    creado_por=self.user,
                    fecha_creacion=base + timedelta(seconds=index),
                )
                for index in range(cantidad)
            ]
        )

    def _columna(self, response, estado):
        return next(
            columna
            for columna in response.context["columnas_kanban"]
            if columna["estado"] == estado
        )

    def _endpoint(self, estado, loaded_ids=(), **params):
        params.setdefault("offset", len(loaded_ids))
        params.setdefault(
            "loaded", ",".join(str(value) for value in loaded_ids)
        )
        return self.client.get(
            reverse(
                "panel_cotizaciones:tarjetas_columna",
                args=[estado],
            ),
            params,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    @staticmethod
    def _ids(html):
        return [
            int(value)
            for value in re.findall(
                r'id="panel-cotizacion-(\d+)"',
                html,
            )
        ]

    def test_get_limita_diez_con_total_real_y_sin_escrituras(self):
        self._bulk(20)
        before = PanelCotizacion.objects.count()
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones")
        )
        columna = self._columna(
            response, PanelCotizacion.Estado.REQUERIMIENTO
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columnas_kanban"]), 3)
        self.assertEqual(columna["count"], 21)
        self.assertEqual(columna["loaded"], 10)
        self.assertEqual(len(columna["items"]), 10)
        self.assertTrue(columna["has_more"])
        self.assertContains(response, 'data-total="21"')
        self.assertContains(response, "Cargar más (11 restantes)")
        self.assertEqual(
            response.content.decode().count(
                'data-panel-cotizacion-card="1"'
            ),
            10,
        )
        self.assertEqual(PanelCotizacion.objects.count(), before)

    def test_limites_uno_diez_once_veinte_y_veintiuno(self):
        estado = PanelCotizacion.Estado.REQUERIMIENTO
        scenarios = (
            (1, 1, False),
            (10, 10, False),
            (11, 10, True),
            (20, 10, True),
            (21, 10, True),
        )
        for total, visible, has_more in scenarios:
            PanelCotizacion.objects.exclude(pk=self.base.pk).delete()
            if total > 1:
                self._bulk(total - 1)
            response = self.client.get(
                reverse("panel_cotizaciones:panel_cotizaciones")
            )
            columna = self._columna(response, estado)
            self.assertEqual(columna["count"], total)
            self.assertEqual(columna["loaded"], visible)
            self.assertEqual(columna["has_more"], has_more)

    def test_las_tres_columnas_pueden_limitarse_independientemente(self):
        self._bulk(10, PanelCotizacion.Estado.REQUERIMIENTO)
        self._bulk(11, PanelCotizacion.Estado.EN_PROGRESO)
        self._bulk(11, PanelCotizacion.Estado.ENVIADA)
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones")
        )

        self.assertEqual(
            [
                columna["loaded"]
                for columna in response.context["columnas_kanban"]
            ],
            [10, 10, 10],
        )
        self.assertEqual(
            sum(
                1
                for columna in response.context["columnas_kanban"]
                if columna["has_more"]
            ),
            3,
        )

    def test_get_y_endpoint_mantienen_consultas_constantes(self):
        panel_url = reverse("panel_cotizaciones:panel_cotizaciones")
        endpoint_url = reverse(
            "panel_cotizaciones:tarjetas_columna",
            args=[PanelCotizacion.Estado.REQUERIMIENTO],
        )
        with CaptureQueriesContext(connection) as panel_small_queries:
            self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_small_queries:
            self.client.get(
                endpoint_url,
                {"offset": "0", "loaded": ""},
            )

        self._bulk(99)
        with CaptureQueriesContext(connection) as panel_large_queries:
            response = self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_large_queries:
            endpoint = self.client.get(
                endpoint_url,
                {"offset": "0", "loaded": ""},
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(endpoint.status_code, 200)
        self.assertEqual(
            len(panel_small_queries), len(panel_large_queries)
        )
        self.assertEqual(
            len(endpoint_small_queries), len(endpoint_large_queries)
        )

    def test_endpoint_tres_cargas_sin_repetidos_y_en_orden(self):
        self._bulk(20)
        panel = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones")
        )
        first_ids = [
            obj.pk
            for obj in self._columna(
                panel, PanelCotizacion.Estado.REQUERIMIENTO
            )["items"]
        ]
        second = self._endpoint(
            PanelCotizacion.Estado.REQUERIMIENTO,
            first_ids,
        )
        second_data = second.json()
        second_ids = self._ids(second_data["html"])
        third = self._endpoint(
            PanelCotizacion.Estado.REQUERIMIENTO,
            first_ids + second_ids,
        )
        third_data = third.json()
        third_ids = self._ids(third_data["html"])

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second_data["loaded"], 10)
        self.assertTrue(second_data["has_more"])
        self.assertEqual(second_data["next_offset"], 20)
        self.assertEqual(third_data["loaded"], 1)
        self.assertFalse(third_data["has_more"])
        expected = list(
            PanelCotizacion.objects.filter(
                estado=PanelCotizacion.Estado.REQUERIMIENTO
            )
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)
        )
        combined = first_ids + second_ids + third_ids
        self.assertEqual(combined, expected)
        self.assertEqual(len(combined), len(set(combined)))
        self.assertNotIn("<html", second_data["html"].lower())
        self.assertIn(
            'data-panel-cotizacion-modal-open="1"',
            second_data["html"],
        )
        self.assertIn(
            "data-panel-cotizacion-editor-url=",
            second_data["html"],
        )
        self.assertIn(
            'data-panel-cotizacion-state-select="1"',
            second_data["html"],
        )
        self.assertIn('data-status-option="', second_data["html"])

    def test_endpoint_reconcilia_movimiento_eliminacion_y_offset_mayor(self):
        self._bulk(10)
        loaded_ids = list(
            PanelCotizacion.objects.filter(
                estado=PanelCotizacion.Estado.REQUERIMIENTO
            )
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)[:10]
        )
        moved_id = loaded_ids[-1]
        PanelCotizacion.objects.filter(pk=moved_id).update(
            estado=PanelCotizacion.Estado.ENVIADA
        )
        response = self._endpoint(
            PanelCotizacion.Estado.REQUERIMIENTO,
            loaded_ids,
        )
        data = response.json()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["stale_ids"], [moved_id])
        self.assertNotIn(moved_id, self._ids(data["html"]))

        empty = self._endpoint(
            PanelCotizacion.Estado.EN_PROGRESO,
            [999998, 999999],
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["next_offset"], 0)
        self.assertEqual(
            empty.json()["stale_ids"], [999998, 999999]
        )

    def test_creacion_y_cambio_de_orden_entre_cargas_no_duplican(self):
        self._bulk(15)
        estado = PanelCotizacion.Estado.REQUERIMIENTO
        first_ids = list(
            PanelCotizacion.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)[:10]
        )
        created = PanelCotizacion.objects.create(
            titulo="Creada entre cargas",
            estado=estado,
            creado_por=self.user,
        )
        PanelCotizacion.objects.filter(pk=first_ids[-1]).update(
            fecha_creacion=timezone.now() + timedelta(days=2)
        )
        loaded_ids = [created.pk] + first_ids
        response = self._endpoint(estado, loaded_ids)
        returned_ids = self._ids(response.json()["html"])

        self.assertEqual(response.status_code, 200)
        self.assertNotIn(created.pk, returned_ids)
        self.assertTrue(set(first_ids).isdisjoint(returned_ids))

    def test_endpoint_valida_estado_offset_filtro_metodos_y_anonimo(self):
        estado = PanelCotizacion.Estado.REQUERIMIENTO
        url = reverse(
            "panel_cotizaciones:tarjetas_columna",
            args=[estado],
        )
        for params in (
            {"offset": "-1"},
            {"offset": "texto"},
            {"offset": "1", "loaded": "abc"},
            {"offset": "2", "loaded": "1,1"},
            {"offset": "0", "usuario": "invalido"},
            {"offset": "0", "usuario": "999999"},
        ):
            self.assertEqual(
                self.client.get(url, params).status_code,
                400,
            )
        invalid_state = reverse(
            "panel_cotizaciones:tarjetas_columna",
            args=["ESTADO_INEXISTENTE"],
        )
        self.assertEqual(
            self.client.get(
                invalid_state, {"offset": "0", "loaded": ""}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.put(url).status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)
        self.client.logout()
        anonymous = self.client.get(
            url, {"offset": "0", "loaded": ""}
        )
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login/", anonymous.url)

    def test_endpoint_respeta_filtro_multiple_y_lectura_compartida(self):
        estado = PanelCotizacion.Estado.EN_PROGRESO
        matching = []
        for index in range(12):
            obj = PanelCotizacion.objects.create(
                titulo=f"Filtrada {index}",
                estado=estado,
                creado_por=self.user,
            )
            if index < 11:
                obj.asignados.add(self.asignado)
                matching.append(obj)
        response = self._endpoint(
            estado,
            usuario=[str(self.asignado.pk)],
        )
        data = response.json()
        self.assertEqual(data["total"], 11)
        self.assertEqual(data["loaded"], 10)
        self.assertTrue(data["has_more"])
        self.assertNotIn("Filtrada 11", data["html"])

        other = User.objects.create_user(
            username="panel_fase7b_lector",
            password="panel123",
        )
        self.client.force_login(other)
        self.assertEqual(self._endpoint(estado).status_code, 200)

    def test_javascript_deduplica_aborta_y_reconstruye_tablero(self):
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("const columnLoadRequests = new Map()", javascript)
        self.assertIn("if (existing) return existing.promise", javascript)
        self.assertIn("entry.controller.abort()", javascript)
        self.assertIn("boardRefreshController?.abort()", javascript)
        self.assertIn("requestVersion !== boardVersion", javascript)
        self.assertIn("Tarjeta duplicada o incompatible.", javascript)
        self.assertIn("data-panel-cotizacion-load-more", javascript)
        self.assertIn("if (duplicateCard) duplicateCard.remove()", javascript)
        self.assertEqual(javascript.count("Sortable.create("), 1)
        self.assertEqual(
            javascript.count("root.addEventListener('click'"), 1
        )
        self.assertIn("root.dataset.panelJsInitialized = '1'", javascript)
        self.assertIn(
            "const statusButton = e.target.closest('.kanban-status-control__option[data-status-option]');",
            javascript,
        )
        self.assertIn("handleCardStateChange(stateSelect, statusButton);", javascript)
        self.assertIn("persistCardState(card, sourceColumn, targetColumn, nuevoEstado, previousState, triggerElement)", javascript)
        self.assertIn("postForm(updateUrl, fd, triggerElement?.closest('form') || triggerElement || card)", javascript)
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", javascript)
        self.assertIn("'X-CSRFToken': token", javascript)
        self.assertIn("button.classList.toggle('active', isActive);", javascript)


class PanelCotizacionInlineCreateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_inline",
            password="panel123",
            first_name="Inline",
        )
        self.cliente = Cliente.objects.create(nombre=" cliente demo ")
        self.client = Client()
        self.client.force_login(self.user)

    def test_panel_no_instancia_formulario_inline_y_conserva_columnas(self):
        with patch(
            "panel_cotizaciones.views.PanelCotizacionInlineCreateForm",
            side_effect=AssertionError("No debe instanciarse en el GET inicial"),
        ):
            response = self.client.get(
                reverse("panel_cotizaciones:panel_cotizaciones")
            )

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("inline_form", response.context)
        html = response.content.decode()
        self.assertEqual(
            len(re.findall(r"<form\b[^>]*data-panel-cotizacion-inline-form=", html)),
            0,
        )
        self.assertEqual(
            len(re.findall(r"<button\b[^>]*data-panel-cotizacion-inline-open=", html)),
            1,
        )
        self.assertEqual(
            len(re.findall(r"<section\b[^>]*panel-cotizacion-column", html)),
            3,
        )
        self.assertEqual(
            len(re.findall(r"<div\b[^>]*data-panel-cotizacion-inline-shared-slot=", html)),
            1,
        )
        self.assertEqual(
            len(
                re.findall(
                    r'<form\b[^>]*data-panel-cotizacion-inline-editor="1"',
                    html,
                )
            ),
            0,
        )
        self.assertNotIn("_inline_editor_form.html", html)

    def test_tablero_partial_tampoco_instancia_formulario_inline(self):
        with patch(
            "panel_cotizaciones.views.PanelCotizacionInlineCreateForm",
            side_effect=AssertionError("No debe instanciarse al refrescar el tablero"),
        ):
            response = self.client.get(
                reverse("panel_cotizaciones:tablero_partial"),
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "data-panel-cotizacion-inline-form=")

    def test_endpoint_formulario_inline_autenticado_y_solo_get(self):
        url = reverse("panel_cotizaciones:formulario_inline")
        total = PanelCotizacion.objects.count()

        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-panel-cotizacion-inline-form-fragment="1"')
        self.assertContains(response, 'data-panel-cotizacion-inline-form="1"')
        for field_name in ("titulo", "cliente", "prioridad", "estado"):
            self.assertContains(response, f'name="{field_name}"')
        self.assertEqual(PanelCotizacion.objects.count(), total)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.put(url).status_code, 405)

    def test_endpoint_formulario_inline_anonimo_redirige(self):
        self.client.logout()
        response = self.client.get(
            reverse("panel_cotizaciones:formulario_inline")
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_javascript_carga_unica_reintento_y_tom_select_seguro(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones")
        )
        html = response.content.decode()
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="panel-cotizaciones-config"', html)
        self.assertIn("/static/panel_cotizaciones/js/panel.js", html)
        self.assertNotIn("let inlineFormLoadPromise = null", html)
        self.assertEqual(javascript.count("let inlineFormLoadPromise = null"), 1)
        self.assertIn("if (inlineFormLoadPromise) return inlineFormLoadPromise", javascript)
        self.assertIn("latestInlineTarget = target", javascript)
        self.assertIn("inlineFormLoadPromise = null", javascript)
        self.assertIn("redirect: 'error'", javascript)
        self.assertIn("if (inlineForm.dataset.submitting === 'true') return", javascript)
        self.assertIn("if (select.tomselect) return", javascript)
        self.assertIn("select.tomselect.destroy()", javascript)
        self.assertIn("if (hasActiveFilter) {\n              refreshBoard();", javascript)
        self.assertEqual(javascript.count("root.addEventListener('submit'"), 1)
        self.assertIn("const inlineEditorRequests = new Map()", javascript)
        self.assertIn("inlineEditorRequests.get(cardId)", javascript)
        self.assertIn("existing.fieldName === fieldName", javascript)
        self.assertIn("existing.controller.abort()", javascript)
        self.assertIn("data-panel-cotizacion-inline-editor-loading", javascript)
        self.assertIn("No se pudo cargar el editor. Intenta nuevamente.", javascript)
        self.assertNotIn("{% filter escapejs %}", javascript)

    def test_endpoint_editor_inline_get_real_solo_lectura_y_metodos_seguros(self):
        cotizacion = PanelCotizacion.objects.create(
            titulo="Editor real",
            cliente="Cliente real",
            creado_por=self.user,
        )
        cotizacion.asignados.add(self.user)
        url = reverse("panel_cotizaciones:inline_editor", args=[cotizacion.pk])
        before = {
            "objetos": PanelCotizacion.objects.count(),
            "asignados": list(cotizacion.asignados.values_list("pk", flat=True)),
            "titulo": cotizacion.titulo,
        }

        response = self.client.get(url, {"field": "asignados"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["id"], cotizacion.pk)
        self.assertEqual(data["field"], "asignados")
        self.assertIn('data-panel-cotizacion-inline-editor="1"', data["html"])
        self.assertIn(
            f'data-panel-cotizacion-editor-id="{cotizacion.pk}"',
            data["html"],
        )
        cotizacion.refresh_from_db()
        self.assertEqual(
            {
                "objetos": PanelCotizacion.objects.count(),
                "asignados": list(cotizacion.asignados.values_list("pk", flat=True)),
                "titulo": cotizacion.titulo,
            },
            before,
        )
        self.assertEqual(self.client.post(url, {"field": "titulo"}).status_code, 405)
        self.assertEqual(self.client.put(url, {"field": "titulo"}).status_code, 405)
        self.assertEqual(self.client.get(url, {"field": "estado"}).status_code, 400)
        self.assertEqual(
            self.client.get(
                reverse("panel_cotizaciones:inline_editor", args=[999999]),
                {"field": "titulo"},
            ).status_code,
            404,
        )

    def test_endpoint_editor_inline_requiere_autenticacion(self):
        cotizacion = PanelCotizacion.objects.create(
            titulo="Privada",
            creado_por=self.user,
        )
        self.client.logout()
        response = self.client.get(
            reverse("panel_cotizaciones:inline_editor", args=[cotizacion.pk]),
            {"field": "titulo"},
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_creacion_inline_devuelve_json_y_tarjeta_renderizada(self):
        response = self.client.post(
            reverse("panel_cotizaciones:crear_inline"),
            {
                "estado": PanelCotizacion.Estado.EN_PROGRESO,
                "titulo": "Nueva inline",
                "cliente": self.cliente.pk,
                "prioridad": PanelCotizacion.Prioridad.ALTA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estado"], PanelCotizacion.Estado.EN_PROGRESO)
        self.assertEqual(data["column_count"], 1)
        self.assertIn("Nueva inline", data["html"])

        creada = PanelCotizacion.objects.get(pk=data["id"])
        self.assertEqual(creada.creado_por, self.user)
        self.assertEqual(creada.estado, PanelCotizacion.Estado.EN_PROGRESO)
        self.assertEqual(creada.cliente, "CLIENTE DEMO")

    def test_creacion_inline_invalida_devuelve_errores_y_html(self):
        response = self.client.post(
            reverse("panel_cotizaciones:crear_inline"),
            {
                "estado": "INVALIDO",
                "titulo": "Demo",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("estado", data["errors"])

        response = self.client.post(
            reverse("panel_cotizaciones:crear_inline"),
            {
                "estado": PanelCotizacion.Estado.EN_PROGRESO,
                "titulo": "Demo",
                "prioridad": "INVALIDA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("prioridad", data["errors"])
        self.assertIn('data-panel-cotizacion-inline-form-fragment="1"', data["html"])
        self.assertIn(
            f'value="{PanelCotizacion.Estado.EN_PROGRESO}"',
            data["html"],
        )

    def test_creacion_inline_sin_ajax_falla(self):
        response = self.client.post(
            reverse("panel_cotizaciones:crear_inline"),
            {
                "estado": PanelCotizacion.Estado.EN_PROGRESO,
                "titulo": "Sin ajax",
            },
        )
        self.assertEqual(response.status_code, 400)


class PanelCotizacionEstadoUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_estado",
            password="panel123",
            first_name="Estado",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Estado demo",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_estado_update_ajax_persiste_y_devuelve_estado(self):
        response = self.client.post(
            reverse("panel_cotizaciones:estado_update"),
            {
                "cotizacion_id": self.panel.pk,
                "nuevo_estado": PanelCotizacion.Estado.ENVIADA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.panel.refresh_from_db()
        self.assertEqual(self.panel.estado, PanelCotizacion.Estado.ENVIADA)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["estado"], PanelCotizacion.Estado.ENVIADA)

    def test_estado_update_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="panel_estado", password="panel123")
        client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        response_sin_csrf = client.post(
            reverse("panel_cotizaciones:estado_update"),
            {
                "cotizacion_id": self.panel.pk,
                "nuevo_estado": PanelCotizacion.Estado.ENVIADA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response_sin_csrf.status_code, 403)


class PanelCotizacionInlineUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_edit",
            password="panel123",
            first_name="Editor",
        )
        self.asignado = User.objects.create_user(
            username="panel_asignado_edit",
            password="panel123",
            first_name="Asignado",
        )
        self.cliente = Cliente.objects.create(nombre=" cliente inline ")
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Original",
            descripcion="Descripcion",
            cliente="",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_inline_update_titulo(self):
        response = self.client.post(
            reverse("panel_cotizaciones:inline_update", args=[self.panel.pk]),
            {"field": "titulo", "titulo": "Nuevo titulo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.panel.refresh_from_db()
        self.assertEqual(self.panel.titulo, "Nuevo titulo")
        self.assertTrue(response.json()["ok"])

    def test_inline_update_asignados(self):
        response = self.client.post(
            reverse("panel_cotizaciones:inline_update", args=[self.panel.pk]),
            {"field": "asignados", "asignados": [self.asignado.pk]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.panel.refresh_from_db()
        self.assertEqual(
            list(self.panel.asignados.values_list("pk", flat=True)),
            [self.asignado.pk],
        )

    def test_inline_update_rechaza_campos_no_permitidos(self):
        response = self.client.post(
            reverse("panel_cotizaciones:inline_update", args=[self.panel.pk]),
            {"field": "estado", "estado": "ENVIADA"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])

    def test_inline_update_invalido_devuelve_solo_editor_con_errores(self):
        response = self.client.post(
            reverse("panel_cotizaciones:inline_update", args=[self.panel.pk]),
            {"field": "fecha_vencimiento", "fecha_vencimiento": "invalida"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["id"], self.panel.pk)
        self.assertEqual(data["field"], "fecha_vencimiento")
        self.assertIn('data-panel-cotizacion-inline-editor="1"', data["html"])
        self.assertIn("Introduzca una fecha válida", data["html"])
        self.panel.refresh_from_db()
        self.assertIsNone(self.panel.fecha_vencimiento)


class PanelCotizacionDetalleUpdateTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_detail",
            password="panel123",
            first_name="Detalle",
        )
        self.asignado = User.objects.create_user(
            username="panel_detail_asignado",
            password="panel123",
            first_name="Asignado",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Detalle original",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.panel.asignados.add(self.asignado)

    def test_detalle_update_conserva_asignados_si_no_se_envian(self):
        response = self.client.post(
            reverse("panel_cotizaciones:detalle_modal_update", args=[self.panel.pk]),
            {
                "layout": "drawer",
                "titulo": "Detalle actualizado",
                "descripcion": "Descripcion actualizada",
                "prioridad": PanelCotizacion.Prioridad.ALTA,
                "fecha_vencimiento": "",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.panel.refresh_from_db()
        self.assertEqual(self.panel.titulo, "Detalle actualizado")
        self.assertEqual(
            list(self.panel.asignados.values_list("pk", flat=True)),
            [self.asignado.pk],
        )


class PanelCotizacionComentarioTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_comment",
            password="panel123",
            first_name="Comentario",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Con comentarios",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_comentario_create_devuelve_html_y_contador(self):
        response = self.client.post(
            reverse("panel_cotizaciones:comentario_create", args=[self.panel.pk]),
            {"texto": "Primer comentario"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("Primer comentario", data["html"])
        self.assertEqual(data["comentarios_count"], 1)

    def test_comentario_create_vacio_devuelve_error(self):
        response = self.client.post(
            reverse("panel_cotizaciones:comentario_create", args=[self.panel.pk]),
            {"texto": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("texto", data["errors"])

    def test_agregar_comentario_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="panel_comment", password="panel123")

        response_sin_csrf = client.post(
            reverse("panel_cotizaciones:comentario_create", args=[self.panel.pk]),
            {"texto": "Comentario sin CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response_sin_csrf.status_code, 403)
        self.assertFalse(self.panel.comentarios.filter(texto="Comentario sin CSRF").exists())

        request = HttpRequest()
        csrftoken = get_token(request)
        client.cookies.load({"csrftoken": csrftoken})

        response_con_csrf = client.post(
            reverse("panel_cotizaciones:comentario_create", args=[self.panel.pk]),
            {"texto": "Comentario con CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken
        )
        self.assertEqual(response_con_csrf.status_code, 200)
        data = response_con_csrf.json()
        self.assertEqual(data["status"], "ok")
        self.assertTrue(self.panel.comentarios.filter(texto="Comentario con CSRF").exists())



class PanelCotizacionAdjuntosEnlacesTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_adjuntos",
            password="panel123",
            first_name="Adjuntos",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Con adjuntos",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_agregar_enlace_devuelve_html(self):
        response = self.client.post(
            reverse("panel_cotizaciones:enlace_agregar", args=[self.panel.pk]),
            {"titulo": "Propuesta", "url": "https://example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("Propuesta", response.json()["html"])

    def test_agregar_enlace_invalido_devuelve_error(self):
        response = self.client.post(
            reverse("panel_cotizaciones:enlace_agregar", args=[self.panel.pk]),
            {"titulo": "Propuesta", "url": "no-es-url"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn("url", response.json()["errors"])

    def test_agregar_archivo_devuelve_html(self):
        archivo = SimpleUploadedFile(
            "demo.txt", b"hola mundo", content_type="text/plain"
        )
        response = self.client.post(
            reverse("panel_cotizaciones:archivo_agregar", args=[self.panel.pk]),
            {"archivos": [archivo]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertIn("demo", response.json()["html"])


class PanelCotizacionHttpSafetyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_http",
            password="panel123",
            first_name="Http",
        )
        self.panel = PanelCotizacion.objects.create(
            titulo="HTTP demo",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_csrf_protege_creacion_inline(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        response = client.post(
            reverse("panel_cotizaciones:crear_inline"),
            {
                "estado": PanelCotizacion.Estado.REQUERIMIENTO,
                "titulo": "Con csrf",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)

    def test_detalle_modal_inexistente_responde_404(self):
        client = Client()
        client.force_login(self.user)
        response = client.get(
            reverse("panel_cotizaciones:detalle_modal", args=[999999]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)
