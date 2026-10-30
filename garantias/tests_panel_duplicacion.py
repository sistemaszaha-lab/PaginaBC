"""Diagnóstico del tablero sin escribir en la base local ni cambiar la transferencia."""
from html.parser import HTMLParser
from pathlib import Path
import shutil
import subprocess
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from cuenta_gastos.models import CuentaGastos
from .models import Garantia, GarantiaArchivo, GarantiaComentario, GarantiaEnlace, GarantiaEtiqueta
from .views import _board_queryset


class TarjetasParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.ids = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-garantia-card") == "1":
            self.ids.append((attrs["id"], int(attrs["data-garantia-id"])))


@override_settings(PERFORMANCE_DEBUG=False, STORAGES={
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class PanelGarantiasDuplicacionTests(TestCase):
    def setUp(self):
        self.admin = get_user_model().objects.create_user(username="panel-admin", is_superuser=True)
        self.ejecutivo = get_user_model().objects.create_user(username="panel-ejecutivo")
        self.original = Garantia.objects.create(
            titulo="Original", creado_por=self.admin, estado=Garantia.Estado.DEVOLUCION_CLIENTE,
        )
        self.otra = Garantia.objects.create(titulo="Otra intacta", creado_por=self.admin)
        self.original.asignados.set([self.admin, self.ejecutivo])
        self.otra.asignados.add(self.ejecutivo)
        # Multiplicar deliberadamente los joins para detectar repetición de IDs.
        for numero in range(2):
            self.original.etiquetas.add(GarantiaEtiqueta.objects.create(nombre=f"Etiqueta {numero}"))
            GarantiaComentario.objects.create(garantia=self.original, usuario=self.admin, comentario=f"Comentario {numero}")
            GarantiaArchivo.objects.create(garantia=self.original, archivo=f"diagnostico-{numero}.txt", subido_por=self.admin)
            GarantiaEnlace.objects.create(garantia=self.original, url=f"https://example.com/{numero}", creado_por=self.admin)
        self.client.force_login(self.admin)

    def assert_panel_ids(self, *, usuario=None):
        params = {"usuario": usuario.pk} if usuario else {}
        expected = sorted((f"garantia-{g.pk}", g.pk) for g in (self.original, self.otra))
        for endpoint in ("panel_garantias", "tablero_partial"):
            response = self.client.get(reverse(f"garantias:{endpoint}"), params)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(sorted(TarjetasParser(response.content.decode()).ids), expected)
        ids = list(_board_queryset(usuario).values_list("pk", flat=True))
        self.assertEqual(sorted(ids), sorted(g.pk for g in (self.original, self.otra)))

    def test_registros_e_ids_unicos_antes_despues_y_al_recargar(self):
        datos_antes = list(Garantia.objects.order_by("pk").values())
        relaciones_antes = {
            nombre: list(getattr(self.original, nombre).values().order_by("pk"))
            for nombre in ("asignados", "etiquetas", "comentarios", "archivos", "enlaces")
        }
        self.assert_panel_ids()
        self.assert_panel_ids(usuario=self.ejecutivo)
        url = reverse("garantias:enviar_garantia_a_cuenta", args=[self.original.pk])
        for creada in (True, False, False):
            response = self.client.post(url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code, 200)
            cuenta = CuentaGastos.objects.get(garantia_origen=self.original)
            self.assertEqual(response.json(), {"ok": True, "creada": creada, "cuenta_id": cuenta.pk})
            self.assertEqual(CuentaGastos.objects.count(), 1)
            self.assertEqual(list(cuenta.asignados.order_by("pk")), [self.admin, self.ejecutivo])
            self.assertEqual(list(Garantia.objects.order_by("pk").values()), datos_antes)
            for nombre, valores in relaciones_antes.items():
                self.assertEqual(list(getattr(self.original, nombre).values().order_by("pk")), valores)
            self.assert_panel_ids()
            self.assert_panel_ids(usuario=self.ejecutivo)

    def test_carga_ajax_columna_excluye_los_ids_ya_renderizados(self):
        url = reverse("garantias:tarjetas_columna", args=[self.original.estado])
        response = self.client.get(url, {"offset": 0})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(TarjetasParser(response.json()["html"]).ids, [(f"garantia-{self.original.pk}", self.original.pk)])
        self.client.post(reverse("garantias:enviar_garantia_a_cuenta", args=[self.original.pk]))
        for _ in range(2):
            response = self.client.get(url, {"offset": 1, "loaded": str(self.original.pk)})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["html"], "")
            self.assertEqual(response.json()["total"], 1)
            self.assertEqual(response.json()["stale_ids"], [])


class PanelGarantiasJavascriptTests(SimpleTestCase):
    @skipUnless(shutil.which("gjs"), "El diagnóstico JavaScript requiere GJS local")
    def test_handler_real_con_dom_simulado(self):
        directory = Path(__file__).resolve().parent
        result = subprocess.run(
            ["gjs", str(directory / "tests_panel_duplicacion.js"), str(directory / "static/garantias/js/panel_garantias.js")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("OK", result.stdout)
