from datetime import timedelta
from pathlib import Path
import re
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase
from django.test.utils import CaptureQueriesContext, override_settings
from django.middleware.csrf import get_token
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from . import views
from .models import CuentaGastos, CuentaGastosArchivo, CuentaGastosComentario, CuentaGastosEnlace, CuentaGastosEtiqueta, CuentaGastosOpcion

PANEL_JS_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "cuenta_gastos"
    / "js"
    / "panel_cuenta_gastos.js"
)


@override_settings(
    PERFORMANCE_DEBUG=False,
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class CuentaGastosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.asignado = User.objects.create_user(username="asignado", password="pass", first_name="Asignado")

        self.cliente = Cliente.objects.create(nombre="Cliente Test", empresa="Empresa Test")
        self.etiqueta = CuentaGastosEtiqueta.objects.create(nombre="Urgente", color="#FF0000")
        self.opcion = CuentaGastosOpcion.objects.create(nombre="Opción Especial")

        self.cuenta = CuentaGastos.objects.create(
            titulo="Laptop HP",
            descripcion="Laptop para desarrollo",
            cliente=self.cliente,
            prioridad="ALTA",
            fecha_vencimiento="2026-05-22",
            creado_por=self.user,
        )
        self.cuenta.asignados.add(self.asignado)
        self.cuenta.etiquetas.add(self.etiqueta)
        self.cuenta.opciones.add(self.opcion)

        self.client = Client()
        self.client.force_login(self.user)

    def test_panel_cuenta_gastos_view(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))
        self.assertEqual(resp.status_code, 200)

    def test_panel_no_instancia_formulario_inline_de_creacion(self):
        with patch("cuenta_gastos.views.CuentaGastosInlineCreateForm") as form_class:
            resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))

        self.assertEqual(resp.status_code, 200)
        form_class.assert_not_called()
        self.assertNotIn("inline_form", resp.context)

    def test_panel_tiene_slot_unico_sin_formulario_inline_inicial(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))
        html = resp.content.decode()

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            len(re.findall(r'<div\b[^>]*data-cuenta-inline-shared-slot="1"', html)),
            1,
        )
        self.assertEqual(
            len(re.findall(r'<form\b[^>]*data-cuenta-inline-form="1"', html)),
            0,
        )
        self.assertEqual(
            len(re.findall(r'<button\b[^>]*data-cuenta-inline-open="1"', html)),
            len(views.COLUMNAS),
        )
        self.assertEqual(
            len(re.findall(r'<section\b[^>]*data-cuenta-column="1"', html)),
            len(views.COLUMNAS),
        )
        self.assertEqual(
            len(
                re.findall(
                    r'<form\b[^>]*data-cuenta-inline-editor="1"',
                    html,
                )
            ),
            0,
        )
        self.assertNotIn("_inline_editor_form.html", html)

    def test_panel_contiene_carga_fetch_deduplicada_y_reintento(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))
        html = resp.content.decode()
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="panel-cuenta-gastos-config"', html)
        self.assertIn("/static/cuenta_gastos/js/panel_cuenta_gastos.js", html)
        self.assertNotIn("let inlineFormLoadPromise = null", html)
        self.assertEqual(javascript.count("const inlineFormUrl ="), 1)
        self.assertEqual(javascript.count("let inlineFormLoadPromise = null"), 1)
        self.assertIn("if (inlineFormLoadPromise) return inlineFormLoadPromise", javascript)
        self.assertIn("inlineFormLoadPromise = null", javascript)
        self.assertIn("No se pudo cargar el formulario. Intenta nuevamente.", javascript)
        self.assertIn("if (select.tomselect)", javascript)
        self.assertIn("select.tomselect.destroy()", javascript)
        self.assertEqual(javascript.count("document.addEventListener('submit'"), 1)
        self.assertIn("const inlineEditorRequests = new Map()", javascript)
        self.assertIn("inlineEditorRequests.get(cardId)", javascript)
        self.assertIn("existing.fieldName === fieldName", javascript)
        self.assertIn("existing.controller.abort()", javascript)
        self.assertIn("data-cuenta-inline-editor-loading", javascript)
        self.assertIn("No se pudo cargar el editor. Intenta nuevamente.", javascript)
        self.assertNotIn("{% filter escapejs %}", javascript)

    def test_endpoint_editor_inline_get_real_solo_lectura_y_metodos_seguros(self):
        url = reverse("cuenta_gastos:editor_cuenta_inline", args=[self.cuenta.pk])
        before = {
            "cuentas": CuentaGastos.objects.count(),
            "archivos": CuentaGastosArchivo.objects.count(),
            "comentarios": CuentaGastosComentario.objects.count(),
            "enlaces": CuentaGastosEnlace.objects.count(),
            "asignados": list(self.cuenta.asignados.values_list("pk", flat=True)),
            "etiquetas": list(self.cuenta.etiquetas.values_list("pk", flat=True)),
            "opciones": list(self.cuenta.opciones.values_list("pk", flat=True)),
            "titulo": self.cuenta.titulo,
        }

        response = self.client.get(url, {"field": "asignados"})

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["id"], self.cuenta.pk)
        self.assertEqual(data["field"], "asignados")
        self.assertIn('data-cuenta-inline-editor="1"', data["html"])
        self.assertIn(f'data-cuenta-editor-id="{self.cuenta.pk}"', data["html"])
        self.cuenta.refresh_from_db()
        self.assertEqual(
            {
                "cuentas": CuentaGastos.objects.count(),
                "archivos": CuentaGastosArchivo.objects.count(),
                "comentarios": CuentaGastosComentario.objects.count(),
                "enlaces": CuentaGastosEnlace.objects.count(),
                "asignados": list(self.cuenta.asignados.values_list("pk", flat=True)),
                "etiquetas": list(self.cuenta.etiquetas.values_list("pk", flat=True)),
                "opciones": list(self.cuenta.opciones.values_list("pk", flat=True)),
                "titulo": self.cuenta.titulo,
            },
            before,
        )
        self.assertEqual(self.client.post(url, {"field": "titulo"}).status_code, 405)
        self.assertEqual(self.client.put(url, {"field": "titulo"}).status_code, 405)
        self.assertEqual(self.client.get(url, {"field": "estado"}).status_code, 400)
        self.assertEqual(
            self.client.get(
                reverse("cuenta_gastos:editor_cuenta_inline", args=[999999]),
                {"field": "titulo"},
            ).status_code,
            404,
        )

    def test_endpoint_editor_inline_aplica_autenticacion_y_permiso_del_post(self):
        url = reverse("cuenta_gastos:editor_cuenta_inline", args=[self.cuenta.pk])
        otro = get_user_model().objects.create_user(
            username="sin_permiso_editor",
            password="pass",
        )
        self.client.force_login(otro)
        self.assertEqual(self.client.get(url, {"field": "titulo"}).status_code, 403)

        self.client.logout()
        response = self.client.get(url, {"field": "titulo"})
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_endpoint_formulario_inline_autenticado_devuelve_todos_los_campos(self):
        resp = self.client.get(
            reverse("cuenta_gastos:formulario_cuenta_gastos_inline")
        )

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-cuenta-inline-form-fragment="1"', count=1)
        self.assertContains(resp, 'data-cuenta-inline-form="1"', count=1)
        for field_name in [
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
            "opciones",
            "estado",
        ]:
            self.assertContains(resp, f'name="{field_name}"')

    def test_endpoint_formulario_inline_anonimo_redirige_a_login(self):
        self.client.logout()
        resp = self.client.get(
            reverse("cuenta_gastos:formulario_cuenta_gastos_inline")
        )

        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_endpoint_formulario_inline_rechaza_post(self):
        resp = self.client.post(
            reverse("cuenta_gastos:formulario_cuenta_gastos_inline")
        )
        self.assertEqual(resp.status_code, 405)

    def test_endpoint_formulario_inline_no_modifica_datos_ni_relaciones(self):
        before = {
            "cuentas": CuentaGastos.objects.count(),
            "archivos": CuentaGastosArchivo.objects.count(),
            "comentarios": CuentaGastosComentario.objects.count(),
            "enlaces": CuentaGastosEnlace.objects.count(),
            "asignados": self.cuenta.asignados.count(),
            "etiquetas": self.cuenta.etiquetas.count(),
            "opciones": self.cuenta.opciones.count(),
        }

        resp = self.client.get(
            reverse("cuenta_gastos:formulario_cuenta_gastos_inline")
        )

        self.assertEqual(resp.status_code, 200)
        after = {
            "cuentas": CuentaGastos.objects.count(),
            "archivos": CuentaGastosArchivo.objects.count(),
            "comentarios": CuentaGastosComentario.objects.count(),
            "enlaces": CuentaGastosEnlace.objects.count(),
            "asignados": self.cuenta.asignados.count(),
            "etiquetas": self.cuenta.etiquetas.count(),
            "opciones": self.cuenta.opciones.count(),
        }
        self.assertEqual(after, before)

    def test_crear_inline_valido_conserva_campos_y_relaciones(self):
        before = CuentaGastos.objects.count()
        resp = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "Cuenta inline completa",
                "descripcion": "Descripción inline",
                "cliente": str(self.cliente.id),
                "prioridad": CuentaGastos.Prioridad.ALTA,
                "fecha_vencimiento": "2026-08-15",
                "asignados": [str(self.asignado.id)],
                "etiquetas": [str(self.etiqueta.id)],
                "opciones": [str(self.opcion.id)],
                "estado": CuentaGastos.Estado.COBRANZA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(CuentaGastos.objects.count(), before + 1)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estado"], CuentaGastos.Estado.COBRANZA)
        self.assertIn('data-cuenta-card="1"', data["html"])

        cuenta = CuentaGastos.objects.get(titulo="Cuenta inline completa")
        self.assertEqual(cuenta.descripcion, "Descripción inline")
        self.assertEqual(cuenta.cliente, self.cliente)
        self.assertEqual(cuenta.prioridad, CuentaGastos.Prioridad.ALTA)
        self.assertEqual(str(cuenta.fecha_vencimiento), "2026-08-15")
        self.assertEqual(list(cuenta.asignados.all()), [self.asignado])
        self.assertEqual(list(cuenta.etiquetas.all()), [self.etiqueta])
        self.assertEqual(list(cuenta.opciones.all()), [self.opcion])

    def test_crear_inline_invalido_devuelve_400_sin_crear(self):
        before = CuentaGastos.objects.count()
        resp = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "",
                "estado": CuentaGastos.Estado.EN_PROCESO,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(resp.status_code, 400)
        self.assertEqual(CuentaGastos.objects.count(), before)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertIn("titulo", data["errors"])
        self.assertIn('data-cuenta-inline-form-fragment="1"', data["html"])
        self.assertIn(
            f'name="estado" value="{CuentaGastos.Estado.EN_PROCESO}"',
            data["html"],
        )

    def test_crear_inline_respeta_filtro_de_usuario(self):
        resp = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "Visible para filtro",
                "estado": CuentaGastos.Estado.SOLICITUD_PAGO,
                "asignados": [str(self.asignado.id)],
                "usuario": str(self.asignado.id),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["matches_filter"])

        otro = get_user_model().objects.create_user(
            username="filtro_otro", password="pass"
        )
        resp = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "Oculta para filtro",
                "estado": CuentaGastos.Estado.SOLICITUD_PAGO,
                "asignados": [str(self.asignado.id)],
                "usuario": str(otro.id),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["matches_filter"])

    def test_crear_inline_anonimo_conserva_permiso_existente(self):
        self.client.logout()
        resp = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "No autorizado",
                "estado": CuentaGastos.Estado.SOLICITUD_PAGO,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 302)

    def test_panel_muestra_etiqueta_agencia_aduanal_y_conserva_valor_interno(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))
        self.assertContains(resp, "Solicitud de cuenta de agencia aduanal")
        self.assertEqual(
            CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS,
            "SOLICITUD_CUENTA_GASTOS",
        )

    def test_panel_filtra_por_usuario(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"), {"usuario": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Laptop HP")

    def _bulk_cuentas(self, cantidad, *, estado=None):
        estado = estado or CuentaGastos.Estado.SOLICITUD_PAGO
        base = timezone.now() + timedelta(minutes=1)
        CuentaGastos.objects.bulk_create(
            [
                CuentaGastos(
                    titulo=f"Fase 7A {index:03d}",
                    estado=estado,
                    creado_por=self.user,
                    fecha_creacion=base + timedelta(seconds=index),
                )
                for index in range(cantidad)
            ]
        )

    def _columna_contexto(self, response, estado):
        return next(
            columna
            for columna in response.context["columnas"]
            if columna["estado"] == estado
        )

    def _endpoint_columna(self, estado, loaded_ids=(), **params):
        params.setdefault("offset", len(loaded_ids))
        params.setdefault(
            "loaded", ",".join(str(value) for value in loaded_ids)
        )
        return self.client.get(
            reverse("cuenta_gastos:tarjetas_columna", args=[estado]),
            params,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_panel_limita_tres_por_columna_y_conserva_total_real(self):
        self._bulk_cuentas(20)
        response = self.client.get(
            reverse("cuenta_gastos:panel_cuenta_gastos")
        )
        columna = self._columna_contexto(
            response, CuentaGastos.Estado.SOLICITUD_PAGO
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columnas"]), 15)
        self.assertEqual(columna["count"], 21)
        self.assertEqual(columna["loaded"], views.INITIAL_CARDS_PER_COLUMN)
        self.assertEqual(len(columna["items"]), views.INITIAL_CARDS_PER_COLUMN)
        self.assertTrue(columna["has_more"])
        self.assertEqual(columna["remaining"], 18)
        self.assertContains(response, 'data-total="21"')
        self.assertContains(response, "Cargar más (18 restantes)")
        self.assertEqual(
            response.content.decode().count('data-cuenta-card="1"'),
            views.INITIAL_CARDS_PER_COLUMN,
        )

    def test_panel_exactamente_tres_no_ofrece_mas_y_cuatro_si_ofrece(self):
        self._bulk_cuentas(2)
        response = self.client.get(
            reverse("cuenta_gastos:panel_cuenta_gastos")
        )
        columna = self._columna_contexto(
            response, CuentaGastos.Estado.SOLICITUD_PAGO
        )
        self.assertEqual(columna["count"], 3)
        self.assertEqual(columna["loaded"], views.INITIAL_CARDS_PER_COLUMN)
        self.assertFalse(columna["has_more"])

        self._bulk_cuentas(1)
        response = self.client.get(
            reverse("cuenta_gastos:panel_cuenta_gastos")
        )
        columna = self._columna_contexto(
            response, CuentaGastos.Estado.SOLICITUD_PAGO
        )
        self.assertEqual(columna["count"], 4)
        self.assertEqual(columna["loaded"], views.INITIAL_CARDS_PER_COLUMN)
        self.assertTrue(columna["has_more"])

    def test_panel_consultas_constantes_con_cien_registros(self):
        url = reverse("cuenta_gastos:panel_cuenta_gastos")
        with CaptureQueriesContext(connection) as current_queries:
            current = self.client.get(url)
        self.assertEqual(current.status_code, 200)

        self._bulk_cuentas(99)
        with CaptureQueriesContext(connection) as scaled_queries:
            scaled = self.client.get(url)
        self.assertEqual(scaled.status_code, 200)
        self.assertEqual(len(scaled_queries), len(current_queries))
        self.assertEqual(
            self._columna_contexto(
                scaled, CuentaGastos.Estado.SOLICITUD_PAGO
            )["loaded"],
            views.INITIAL_CARDS_PER_COLUMN,
        )

    def test_endpoint_tres_cargas_sin_repetidos_y_en_orden(self):
        self._bulk_cuentas(20)
        panel = self.client.get(
            reverse("cuenta_gastos:panel_cuenta_gastos")
        )
        columna = self._columna_contexto(
            panel, CuentaGastos.Estado.SOLICITUD_PAGO
        )
        first_ids = [cuenta.pk for cuenta in columna["items"]]

        second = self._endpoint_columna(
            CuentaGastos.Estado.SOLICITUD_PAGO, first_ids
        )
        self.assertEqual(second.status_code, 200)
        second_data = second.json()
        second_ids = [
            int(value)
            for value in re.findall(
                r'id="cuenta-(\d+)"', second_data["html"]
            )
        ]
        self.assertEqual(second_data["loaded"], views.CARDS_PAGE_SIZE)
        self.assertTrue(second_data["has_more"])
        self.assertEqual(second_data["total"], 21)
        self.assertEqual(second_data["next_offset"], 13)
        self.assertEqual(second_data["stale_ids"], [])

        third = self._endpoint_columna(
            CuentaGastos.Estado.SOLICITUD_PAGO,
            first_ids + second_ids,
        )
        third_data = third.json()
        third_ids = [
            int(value)
            for value in re.findall(
                r'id="cuenta-(\d+)"', third_data["html"]
            )
        ]
        self.assertEqual(third_data["loaded"], 8)
        self.assertFalse(third_data["has_more"])
        self.assertEqual(third_data["next_offset"], 21)

        expected = list(
            CuentaGastos.objects.filter(
                estado=CuentaGastos.Estado.SOLICITUD_PAGO
            ).values_list("pk", flat=True)
        )
        combined = first_ids + second_ids + third_ids
        self.assertEqual(combined, expected)
        self.assertEqual(len(combined), len(set(combined)))
        self.assertNotIn("<html", second_data["html"].lower())
        self.assertIn("data-cuenta-editor-url=", second_data["html"])
        self.assertIn('data-cuenta-modal-open="1"', second_data["html"])
        self.assertIn('data-cuenta-state-select="1"', second_data["html"])

    def test_endpoint_reconcilia_registro_eliminado_o_movido(self):
        self._bulk_cuentas(10)
        ordered_ids = list(
            CuentaGastos.objects.filter(
                estado=CuentaGastos.Estado.SOLICITUD_PAGO
            ).values_list("pk", flat=True)
        )
        loaded_ids = ordered_ids[:10]
        stale_id = loaded_ids[-1]
        CuentaGastos.objects.filter(pk=stale_id).update(
            estado=CuentaGastos.Estado.COBRANZA
        )

        response = self._endpoint_columna(
            CuentaGastos.Estado.SOLICITUD_PAGO, loaded_ids
        )
        data = response.json()
        returned_ids = [
            int(value)
            for value in re.findall(r'id="cuenta-(\d+)"', data["html"])
        ]
        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["stale_ids"], [stale_id])
        self.assertEqual(data["loaded"], 1)
        self.assertNotIn(stale_id, returned_ids)
        self.assertFalse(data["has_more"])
        self.assertEqual(data["next_offset"], data["total"])

    def test_endpoint_offset_mayor_al_total_reconcilia_ids_obsoletos(self):
        response = self._endpoint_columna(
            CuentaGastos.Estado.APROBADAS,
            [999998, 999999],
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total"], 0)
        self.assertEqual(data["next_offset"], 0)
        self.assertEqual(data["stale_ids"], [999998, 999999])
        self.assertFalse(data["has_more"])

    def test_endpoint_creacion_entre_cargas_no_duplica(self):
        self._bulk_cuentas(15)
        first_ids = list(
            CuentaGastos.objects.filter(
                estado=CuentaGastos.Estado.SOLICITUD_PAGO
            ).values_list("pk", flat=True)[:10]
        )
        created = CuentaGastos.objects.create(
            titulo="Creada entre cargas",
            estado=CuentaGastos.Estado.SOLICITUD_PAGO,
            creado_por=self.user,
            fecha_creacion=timezone.now() + timedelta(days=1),
        )
        loaded_ids = [created.pk] + first_ids
        response = self._endpoint_columna(
            CuentaGastos.Estado.SOLICITUD_PAGO, loaded_ids
        )
        returned_ids = [
            int(value)
            for value in re.findall(
                r'id="cuenta-(\d+)"', response.json()["html"]
            )
        ]
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(created.pk, returned_ids)
        self.assertTrue(set(first_ids).isdisjoint(returned_ids))

    def test_endpoint_valida_estado_offset_filtro_metodo_y_autenticacion(self):
        valid_url = reverse(
            "cuenta_gastos:tarjetas_columna",
            args=[CuentaGastos.Estado.SOLICITUD_PAGO],
        )
        self.assertEqual(
            self.client.get(valid_url, {"offset": "-1"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(valid_url, {"offset": "texto"}).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                valid_url, {"offset": "1", "loaded": "abc"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                valid_url, {"offset": "2", "loaded": "1,1"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                valid_url, {"offset": "0", "usuario": "999999"}
            ).status_code,
            400,
        )
        self.assertEqual(
            self.client.get(
                reverse(
                    "cuenta_gastos:tarjetas_columna",
                    args=["ESTADO_INEXISTENTE"],
                ),
                {"offset": "0"},
            ).status_code,
            404,
        )
        self.assertEqual(
            self.client.post(valid_url, {"offset": "0"}).status_code,
            405,
        )
        self.assertEqual(
            self.client.put(valid_url, {"offset": "0"}).status_code,
            405,
        )
        self.assertEqual(
            self.client.delete(valid_url, {"offset": "0"}).status_code,
            405,
        )

        self.client.logout()
        anonymous = self.client.get(valid_url, {"offset": "0"})
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login/", anonymous.url)

    def test_endpoint_vacio_solo_lectura_y_lectura_autenticada_compartida(self):
        estado = CuentaGastos.Estado.APROBADAS
        before = CuentaGastos.objects.count()
        response = self._endpoint_columna(estado)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "ok": True,
                "estado": estado,
                "html": "",
                "loaded": 0,
                "next_offset": 0,
                "has_more": False,
                "total": 0,
                "stale_ids": [],
            },
        )
        self.assertEqual(CuentaGastos.objects.count(), before)

        otro = get_user_model().objects.create_user(
            username="lector_fase7a", password="pass"
        )
        self.client.force_login(otro)
        self.assertEqual(self._endpoint_columna(estado).status_code, 200)

    def test_endpoint_respeta_filtro_y_consulta_constante(self):
        cuentas = [
            CuentaGastos.objects.create(
                titulo=f"Filtrada {index}",
                estado=CuentaGastos.Estado.EN_PROCESO,
                creado_por=self.user,
            )
            for index in range(12)
        ]
        for cuenta in cuentas[:11]:
            cuenta.asignados.add(self.asignado)

        response = self._endpoint_columna(
            CuentaGastos.Estado.EN_PROCESO,
            usuario=self.asignado.pk,
        )
        data = response.json()
        self.assertEqual(data["total"], 11)
        self.assertEqual(data["loaded"], views.CARDS_PAGE_SIZE)
        self.assertTrue(data["has_more"])
        self.assertNotIn(cuentas[-1].titulo, data["html"])

        with CaptureQueriesContext(connection) as first_queries:
            first = self._endpoint_columna(
                CuentaGastos.Estado.EN_PROCESO
            )
        self.assertEqual(first.status_code, 200)
        self._bulk_cuentas(88, estado=CuentaGastos.Estado.EN_PROCESO)
        with CaptureQueriesContext(connection) as scaled_queries:
            scaled = self._endpoint_columna(
                CuentaGastos.Estado.EN_PROCESO
            )
        self.assertEqual(scaled.status_code, 200)
        self.assertEqual(len(scaled_queries), len(first_queries))

    def test_js_carga_progresiva_deduplica_aborta_y_no_recrea_sortable(self):
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")
        response = self.client.get(
            reverse("cuenta_gastos:panel_cuenta_gastos")
        )
        html = response.content.decode()

        self.assertIn("const columnLoadRequests = new Map()", javascript)
        self.assertIn("if (existing) return existing.promise", javascript)
        self.assertIn("entry.controller.abort()", javascript)
        self.assertIn("requestVersion !== filterVersion", javascript)
        self.assertIn("Tarjeta duplicada o incompatible.", javascript)
        self.assertIn("if (duplicateCard) duplicateCard.remove()", javascript)
        self.assertIn("data-cuenta-load-more", javascript)
        self.assertEqual(javascript.count("Sortable.create("), 1)
        self.assertEqual(
            javascript.count("document.addEventListener('click'"), 1
        )
        self.assertIn(
            "sortablejs@1.15.6/Sortable.min.js",
            html,
        )

    def test_detalle_cuenta_gastos_view(self):
        resp = self.client.get(reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 200)

    def test_detalle_cuenta_gastos_drawer_layout(self):
        resp = self.client.get(
            reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cuenta-drawer__panel", data["html"])
        self.assertIn('name="layout" value="drawer"', data["html"])
        self.assertIn("data-cuenta-tags-section", data["html"])
        self.assertIn("data-cuenta-options-section", data["html"])

    def test_editar_cuenta_preserva_valores(self):
        # We send a POST request with empty values for title, description, client, assignments, tags, options, etc.
        # But changing priority from ALTA to MEDIA.
        post_data = {
            "titulo": "",
            "descripcion": "",
            "cliente": "",
            "fecha_vencimiento": "",
            "prioridad": "MEDIA",
            "asignados": [],
            "etiquetas": [],
            "opciones": [],
        }

        resp = self.client.post(
            reverse("cuenta_gastos:editar_cuenta", args=[self.cuenta.id]),
            post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)

        # Refresh from database and assert values
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.prioridad, "MEDIA")
        self.assertEqual(self.cuenta.titulo, "Laptop HP")
        self.assertEqual(self.cuenta.descripcion, "Laptop para desarrollo")
        self.assertEqual(self.cuenta.cliente, self.cliente)
        self.assertEqual(str(self.cuenta.fecha_vencimiento), "2026-05-22")
        self.assertIn(self.asignado, self.cuenta.asignados.all())
        self.assertIn(self.etiqueta, self.cuenta.etiquetas.all())
        self.assertIn(self.opcion, self.cuenta.opciones.all())

    def test_editar_cuenta_ajax_drawer_devuelve_drawer_y_tarjeta(self):
        resp = self.client.post(
            reverse("cuenta_gastos:editar_cuenta", args=[self.cuenta.id]),
            {
                "layout": "drawer",
                "titulo": "Laptop HP Drawer",
                "descripcion": "Laptop para desarrollo",
                "cliente": str(self.cliente.id),
                "fecha_vencimiento": "2026-05-22",
                "prioridad": "MEDIA",
                "asignados": [str(self.asignado.id)],
                "etiquetas": [str(self.etiqueta.id)],
                "opciones": [str(self.opcion.id)],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("cuenta-drawer__panel", data["html"])
        self.assertIn('id="cuenta-%s"' % self.cuenta.id, data["card_html"])

    def test_agregar_comentario_ajax_devuelve_solo_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "Comentario desde drawer", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["comments_count"], 1)
        self.assertIn("data-cuenta-comments-section", data["comments_html"])
        self.assertIn("Comentario desde drawer", data["comments_html"])
        self.assertNotIn("cuenta-drawer__panel", data["comments_html"])

    def test_agregar_comentario_ajax_preserva_texto_en_error(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("data-cuenta-comments-section", data["comments_html"])
        self.assertIn('name="comentario"', data["comments_html"])

    def test_agregar_comentario_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="tester", password="pass")

        response_sin_csrf = client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "Comentario sin CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response_sin_csrf.status_code, 403)
        self.assertFalse(CuentaGastosComentario.objects.filter(comentario="Comentario sin CSRF").exists())

        request = HttpRequest()
        csrftoken = get_token(request)
        client.cookies.load({"csrftoken": csrftoken})

        response_con_csrf = client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "Comentario con CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken
        )
        self.assertEqual(response_con_csrf.status_code, 200)
        data = response_con_csrf.json()
        self.assertTrue(data["success"])
        self.assertTrue(CuentaGastosComentario.objects.filter(comentario="Comentario con CSRF").exists())

    def test_queryset_comentarios_muestra_mas_recientes_primero(self):
        viejo = CuentaGastosComentario.objects.create(
            cuenta_gasto=self.cuenta,
            usuario=self.user,
            comentario="Comentario viejo",
            fecha=timezone.now() - timedelta(days=1),
        )
        nuevo = CuentaGastosComentario.objects.create(
            cuenta_gasto=self.cuenta,
            usuario=self.user,
            comentario="Comentario nuevo",
            fecha=timezone.now(),
        )
        comentarios = list(views._comentarios_queryset(self.cuenta))
        self.assertEqual([comentarios[0].id, comentarios[1].id], [nuevo.id, viejo.id])

    def test_actualizar_etiquetas_cuenta_ajax_devuelve_seccion_y_tarjeta(self):
        otra = CuentaGastosEtiqueta.objects.create(nombre="Seguimiento", color="#00AAFF")
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "etiquetas": [str(self.etiqueta.id), str(otra.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("data-cuenta-tags-section", data["html"])
        self.assertIn("Seguimiento", data["html"])
        self.assertIn('id="cuenta-%s"' % self.cuenta.id, data["card_html"])

    def test_crear_etiqueta_cuenta_ajax_la_asigna_sin_borrar_catalogo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:crear_etiqueta_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "nombre": "Finanzas", "color": "#123456"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(CuentaGastosEtiqueta.objects.filter(nombre="Finanzas", color="#123456").exists())
        self.assertIn("Finanzas", data["html"])

    def test_quitar_etiqueta_cuenta_solo_desasocia(self):
        resp = self.client.post(
            reverse("cuenta_gastos:quitar_etiqueta_cuenta", args=[self.cuenta.id, self.etiqueta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertNotIn(self.etiqueta, self.cuenta.etiquetas.all())
        self.assertTrue(CuentaGastosEtiqueta.objects.filter(id=self.etiqueta.id).exists())

    def test_actualizar_opciones_cuenta_ajax_devuelve_seccion(self):
        otra = CuentaGastosOpcion.objects.create(nombre="Pago parcial")
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "opciones": [str(self.opcion.id), str(otra.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("data-cuenta-options-section", data["html"])
        self.assertIn("Pago parcial", data["html"])

    def test_crear_opcion_cuenta_ajax_la_asigna(self):
        resp = self.client.post(
            reverse("cuenta_gastos:crear_opcion_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "nombre": "Transferencia"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(CuentaGastosOpcion.objects.filter(nombre="Transferencia").exists())
        self.assertIn("Transferencia", data["html"])

    def test_quitar_opcion_cuenta_solo_desasocia(self):
        resp = self.client.post(
            reverse("cuenta_gastos:quitar_opcion_cuenta", args=[self.cuenta.id, self.opcion.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertNotIn(self.opcion, self.cuenta.opciones.all())
        self.assertTrue(CuentaGastosOpcion.objects.filter(id=self.opcion.id).exists())

    def test_agregar_archivo_ajax_valido_devuelve_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer", "archivos": SimpleUploadedFile("factura.txt", b"contenido")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["files_count"], 1)
        self.assertIn("data-cuenta-files-section", data["html"])
        self.assertIn("factura", data["html"])

    def test_agregar_archivo_ajax_invalido_devuelve_error_y_conteo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn("data-cuenta-files-section", data["html"])

    def test_eliminar_archivo_ajax_devuelve_seccion_y_conteo(self):
        archivo = CuentaGastosArchivo.objects.create(
            cuenta_gasto=self.cuenta,
            archivo=SimpleUploadedFile("factura_eliminar.txt", b"contenido"),
            subido_por=self.user,
        )
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer", "archivo_id": archivo.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn("data-cuenta-files-section", data["html"])
        self.assertFalse(CuentaGastosArchivo.objects.filter(id=archivo.id).exists())

    def test_agregar_enlace_ajax_valido_devuelve_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "titulo": "Portal", "url": "https://example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["links_count"], 1)
        self.assertIn("data-cuenta-links-section", data["html"])
        self.assertIn("https://example.com", data["html"])

    def test_agregar_enlace_ajax_invalido_devuelve_error_y_conteo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "titulo": "Portal", "url": "nota-url"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn("data-cuenta-links-section", data["html"])

    def test_eliminar_enlace_ajax_devuelve_seccion_y_conteo(self):
        enlace = CuentaGastosEnlace.objects.create(
            cuenta_gasto=self.cuenta,
            titulo="Portal borrar",
            url="https://example.com/borrar",
            creado_por=self.user,
        )
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "enlace_id": enlace.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn("data-cuenta-links-section", data["html"])
        self.assertFalse(CuentaGastosEnlace.objects.filter(id=enlace.id).exists())

    def test_inline_update_titulo_only_updates_titulo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_cuenta_inline", args=[self.cuenta.id]),
            {"field": "titulo", "titulo": "Nuevo titulo inline"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.titulo, "Nuevo titulo inline")
        self.assertEqual(self.cuenta.prioridad, "ALTA")
        self.assertEqual(self.cuenta.cliente, self.cliente)

    def test_inline_update_asignados_only_updates_asignados(self):
        User = get_user_model()
        nuevo = User.objects.create_user(username="nuevo_inline", password="pass", first_name="Nuevo")

        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_cuenta_inline", args=[self.cuenta.id]),
            {"field": "asignados", "asignados": [str(nuevo.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertIn(nuevo, self.cuenta.asignados.all())
        self.assertNotIn(self.asignado, self.cuenta.asignados.all())
        self.assertEqual(self.cuenta.titulo, "Laptop HP")

    def test_inline_update_asignados_informa_si_deja_de_coincidir_filtro(self):
        response = self.client.post(
            reverse(
                "cuenta_gastos:actualizar_cuenta_inline",
                args=[self.cuenta.id],
            ),
            {
                "field": "asignados",
                "asignados": [],
                "usuario": str(self.asignado.pk),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertFalse(data["matches_filter"])
        self.assertEqual(data["column_count"], 0)

    def test_inline_update_invalido_devuelve_solo_editor_con_errores(self):
        fecha_original = str(self.cuenta.fecha_vencimiento)
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_cuenta_inline", args=[self.cuenta.id]),
            {"field": "fecha_vencimiento", "fecha_vencimiento": "invalida"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["id"], self.cuenta.pk)
        self.assertEqual(data["field"], "fecha_vencimiento")
        self.assertIn('data-cuenta-inline-editor="1"', data["html"])
        self.assertIn("Introduzca una fecha válida", data["html"])
        self.cuenta.refresh_from_db()
        self.assertEqual(str(self.cuenta.fecha_vencimiento), fecha_original)

    def test_usuario_sin_permiso_no_puede_eliminar_archivo(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_archivo_cg", password="pass")
        archivo = CuentaGastosArchivo.objects.create(
            cuenta_gasto=self.cuenta,
            archivo=SimpleUploadedFile("factura.txt", b"contenido"),
            subido_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"archivo_id": archivo.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(CuentaGastosArchivo.objects.filter(id=archivo.id).exists())

    def test_eliminar_archivo_inexistente_devuelve_404(self):
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"archivo_id": 999999},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 404)

    def test_agregar_archivo_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_eliminar_archivo_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_usuario_anonimo_no_puede_agregar_archivo(self):
        self.client.logout()
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"archivos": SimpleUploadedFile("anonimo.txt", b"contenido")},
        )
        self.assertEqual(resp.status_code, 302)

    def test_usuario_sin_permiso_no_puede_eliminar_enlace(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_enlace_cg", password="pass")
        enlace = CuentaGastosEnlace.objects.create(
            cuenta_gasto=self.cuenta,
            titulo="Portal",
            url="https://example.com/portal",
            creado_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"enlace_id": enlace.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(CuentaGastosEnlace.objects.filter(id=enlace.id).exists())

    def test_usuario_sin_permiso_no_puede_actualizar_etiquetas_cuenta(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_tags_cg", password="pass")
        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]),
            {"etiquetas": [str(self.etiqueta.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 403)

    def test_usuario_sin_permiso_no_puede_actualizar_opciones_cuenta(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_opts_cg", password="pass")
        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]),
            {"opciones": [str(self.opcion.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 403)

    def test_eliminar_enlace_inexistente_devuelve_404(self):
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"enlace_id": 999999},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 404)

    def test_agregar_enlace_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_eliminar_enlace_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_usuario_anonimo_no_puede_agregar_enlace(self):
        self.client.logout()
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"titulo": "Anonimo", "url": "https://example.com"},
        )
        self.assertEqual(resp.status_code, 302)

    def test_actualizar_etiquetas_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_actualizar_opciones_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)
