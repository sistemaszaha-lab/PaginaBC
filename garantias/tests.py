from .models import Garantia, GarantiaEtiqueta
from django.test import TestCase, Client
from django.urls import reverse
import re
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
User = get_user_model()
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.middleware.csrf import get_token
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone
from datetime import date, timedelta

from clientes.models import Cliente

from .models import (
    Garantia,
    GarantiaArchivo,
    GarantiaColumna,
    GarantiaComentario,
    GarantiaEnlace,
    GarantiaEtiqueta,
)

PANEL_JS_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "garantias"
    / "js"
    / "panel_garantias.js"
)


class GarantiasFiltroTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.asignado = User.objects.create_user(
            username="asignado_garantias", password="pass123", first_name="Asignado"
        )
        self.otro = User.objects.create_user(
            username="otro_garantias", password="pass123", first_name="Otro"
        )

        self.garantia = Garantia.objects.create(
            titulo="Garantia Visible", creado_por=self.admin
        )
        self.garantia.asignados.add(self.asignado, self.asignado)

        self.client.force_login(self.admin)

    def test_panel_filtra_por_usuario(self):
        response = self.client.get(
            reverse("garantias:panel_garantias"), {"usuario": str(self.asignado.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Garantia Visible")

    def test_panel_no_renderiza_cliente_ni_descripcion_en_tarjetas(self):
        self.garantia.cliente = Cliente.objects.create(nombre="Cliente visible solo en detalle")
        self.garantia.descripcion = "Descripcion solo para detalle"
        self.garantia.save(update_fields=["cliente", "descripcion"])
        response = self.client.get(reverse("garantias:panel_garantias"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "garantia-card__client")
        self.assertNotContains(response, "garantia-card__description")

    def test_panel_no_duplica_por_many_to_many(self):
        response = self.client.get(
            reverse("garantias:panel_garantias"), {"usuario": str(self.asignado.id)}
        )
        self.assertEqual(response.content.decode("utf-8").count("Garantia Visible"), 1)

    def test_panel_filtra_sin_resultados(self):
        response = self.client.get(
            reverse("garantias:panel_garantias"), {"usuario": str(self.otro.id)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin garantias.")


@override_settings(PERFORMANCE_DEBUG=False)
class GarantiasCargaProgresivaTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="garantias_fase7c_admin",
            password="garantias123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.ejecutivo = User.objects.create_user(
            username="garantias_fase7c_ejecutivo",
            password="garantias123",
            first_name="Ejecutivo",
        )
        self.asignado = User.objects.create_user(
            username="garantias_fase7c_asignado",
            password="garantias123",
            first_name="Asignado",
        )
        self.client.force_login(self.admin)

    def _bulk(self, cantidad, estado=Garantia.Estado.SOLICITUD_NAVIERA):
        base = timezone.now() + timedelta(minutes=1)
        Garantia.objects.bulk_create(
            [
                Garantia(
                    titulo=f"Fase 7C {estado} {index:03d}",
                    estado=estado,
                    creado_por=self.admin,
                    fecha_creacion=base + timedelta(seconds=index),
                )
                for index in range(cantidad)
            ]
        )

    @staticmethod
    def _columna(response, estado):
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
            reverse("garantias:tarjetas_columna", args=[estado]),
            params,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    @staticmethod
    def _ids(html):
        return [
            int(value)
            for value in re.findall(r'id="garantia-(\d+)"', html)
        ]

    def test_get_limita_diez_total_real_tres_columnas_y_sin_formularios(self):
        self._bulk(21)
        before = Garantia.objects.count()
        response = self.client.get(reverse("garantias:panel_garantias"))
        columna = self._columna(
            response, Garantia.Estado.SOLICITUD_NAVIERA
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columnas_kanban"]), 3)
        self.assertEqual(columna["count"], 21)
        self.assertEqual(columna["loaded"], 10)
        self.assertEqual(len(columna["items"]), 10)
        self.assertTrue(columna["has_more"])
        self.assertEqual(html.count('data-garantia-card="1"'), 10)
        self.assertEqual(html.count('data-garantia-column="1"'), 3)
        self.assertIn('data-total="21"', html)
        self.assertIn("Cargar más (11)", html)
        self.assertNotIn('data-garantia-inline-form="1"', html)
        self.assertNotIn('data-garantia-quick-edit-form="1"', html)
        self.assertEqual(Garantia.objects.count(), before)

    def test_limites_cero_uno_diez_once_veinte_y_veintiuno(self):
        estado = Garantia.Estado.SOLICITUD_NAVIERA
        for total, visible, has_more in (
            (0, 0, False),
            (1, 1, False),
            (10, 10, False),
            (11, 10, True),
            (20, 10, True),
            (21, 10, True),
        ):
            Garantia.objects.all().delete()
            self._bulk(total)
            response = self.client.get(
                reverse("garantias:panel_garantias")
            )
            columna = self._columna(response, estado)
            self.assertEqual(columna["count"], total)
            self.assertEqual(columna["loaded"], visible)
            self.assertEqual(columna["has_more"], has_more)

    def test_tres_columnas_limite_independiente_e_historicos_excluidos(self):
        for estado in (
            Garantia.Estado.SOLICITUD_NAVIERA,
            Garantia.Estado.PAGO_NAVIERA_ZAHA,
            Garantia.Estado.DEVOLUCION_CLIENTE,
        ):
            self._bulk(11, estado)
        Garantia.objects.create(
            titulo="Estado historico invisible",
            estado="CREADA",
            creado_por=self.admin,
        )
        response = self.client.get(reverse("garantias:panel_garantias"))

        self.assertEqual(
            [
                columna["loaded"]
                for columna in response.context["columnas_kanban"]
            ],
            [10, 10, 10],
        )
        self.assertEqual(
            sum(
                columna["has_more"]
                for columna in response.context["columnas_kanban"]
            ),
            3,
        )
        self.assertNotContains(response, "Estado historico invisible")

    def test_get_endpoint_consultas_constantes_y_lectura(self):
        panel_url = reverse("garantias:panel_garantias")
        endpoint_url = reverse(
            "garantias:tarjetas_columna",
            args=[Garantia.Estado.SOLICITUD_NAVIERA],
        )
        self._bulk(1)
        before = Garantia.objects.count()
        with CaptureQueriesContext(connection) as panel_small:
            self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_small:
            self.client.get(endpoint_url, {"offset": "0", "loaded": ""})
        self.assertEqual(Garantia.objects.count(), before)

        self._bulk(100)
        expected = Garantia.objects.count()
        with CaptureQueriesContext(connection) as panel_large:
            panel_response = self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_large:
            endpoint_response = self.client.get(
                endpoint_url, {"offset": "0", "loaded": ""}
            )

        self.assertEqual(panel_response.status_code, 200)
        self.assertEqual(endpoint_response.status_code, 200)
        self.assertEqual(len(panel_small), len(panel_large))
        self.assertEqual(len(endpoint_small), len(endpoint_large))
        self.assertEqual(Garantia.objects.count(), expected)
        writes = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)
        self.assertFalse(
            any(
                writes.match(query["sql"])
                for query in list(panel_large) + list(endpoint_large)
            )
        )

    def test_endpoint_cargas_consecutivas_orden_parcial_y_acciones(self):
        estado = Garantia.Estado.PAGO_NAVIERA_ZAHA
        self._bulk(21, estado)
        panel = self.client.get(reverse("garantias:panel_garantias"))
        first_ids = [
            garantia.pk for garantia in self._columna(panel, estado)["items"]
        ]
        second = self._endpoint(estado, first_ids)
        second_data = second.json()
        second_ids = self._ids(second_data["html"])
        third = self._endpoint(estado, first_ids + second_ids)
        third_data = third.json()
        third_ids = self._ids(third_data["html"])
        expected = list(
            Garantia.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second_data["loaded"], 10)
        self.assertTrue(second_data["has_more"])
        self.assertEqual(second_data["next_offset"], 20)
        self.assertEqual(third_data["loaded"], 1)
        self.assertFalse(third_data["has_more"])
        combined = first_ids + second_ids + third_ids
        self.assertEqual(combined, expected)
        self.assertEqual(len(combined), len(set(combined)))
        self.assertNotIn("<html", second_data["html"].lower())
        for marker in (
            'data-garantia-state-select="1"',
            'data-garantia-modal-open="1"',
            'data-garantia-quick-edit-open="1"',
            'data-garantia-card-comments-count="1"',
            'data-garantia-card-files-count="1"',
            'data-garantia-card-links-count="1"',
        ):
            self.assertIn(marker, second_data["html"])

    def test_endpoint_reconcilia_eliminacion_movimiento_y_offset_superior(self):
        estado = Garantia.Estado.SOLICITUD_NAVIERA
        self._bulk(12, estado)
        loaded_ids = list(
            Garantia.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)[:10]
        )
        deleted_id, moved_id = loaded_ids[-2:]
        Garantia.objects.filter(pk=deleted_id).delete()
        Garantia.objects.filter(pk=moved_id).update(
            estado=Garantia.Estado.DEVOLUCION_CLIENTE
        )
        response = self._endpoint(estado, loaded_ids)
        data = response.json()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["stale_ids"], [deleted_id, moved_id])
        self.assertNotIn(deleted_id, self._ids(data["html"]))
        self.assertNotIn(moved_id, self._ids(data["html"]))

        empty = self._endpoint(
            Garantia.Estado.PAGO_NAVIERA_ZAHA,
            [999998, 999999],
        )
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.json()["next_offset"], 0)
        self.assertEqual(empty.json()["stale_ids"], [999998, 999999])

    def test_creacion_reorden_y_filtro_entre_cargas_no_duplican(self):
        estado = Garantia.Estado.SOLICITUD_NAVIERA
        self._bulk(16, estado)
        matching = list(
            Garantia.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
        )
        for garantia in matching[:12]:
            garantia.asignados.add(self.asignado)
        first_ids = [garantia.pk for garantia in matching[:10]]
        created = Garantia.objects.create(
            titulo="Creada entre cargas",
            estado=estado,
            creado_por=self.admin,
        )
        created.asignados.add(self.asignado)
        Garantia.objects.filter(pk=first_ids[-1]).update(
            fecha_creacion=timezone.now() + timedelta(days=2)
        )
        stale_assignment_id = first_ids[-2]
        Garantia.objects.get(pk=stale_assignment_id).asignados.remove(
            self.asignado
        )
        loaded_ids = [created.pk] + first_ids
        response = self._endpoint(
            estado,
            loaded_ids,
            usuario=str(self.asignado.pk),
        )
        data = response.json()
        returned_ids = self._ids(data["html"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(data["total"], 12)
        self.assertEqual(data["stale_ids"], [stale_assignment_id])
        self.assertNotIn(created.pk, returned_ids)
        self.assertNotIn(stale_assignment_id, returned_ids)
        self.assertTrue(set(first_ids).isdisjoint(returned_ids))
        self.assertNotIn("Fase 7C", self._endpoint(
            Garantia.Estado.DEVOLUCION_CLIENTE,
            usuario=str(self.asignado.pk),
        ).json()["html"])

    def test_endpoint_valida_parametros_metodos_y_permisos_reales(self):
        estado = Garantia.Estado.SOLICITUD_NAVIERA
        url = reverse("garantias:tarjetas_columna", args=[estado])
        for params in (
            {"offset": "-1"},
            {"offset": "texto"},
            {"offset": "1", "loaded": "abc"},
            {"offset": "2", "loaded": "1,1"},
            {"offset": "0", "usuario": "invalido"},
            {"offset": "0", "usuario": "999999"},
            {"offset": "0", "usuario": ["1", "2"]},
        ):
            self.assertEqual(self.client.get(url, params).status_code, 400)
        invalid_state = reverse(
            "garantias:tarjetas_columna", args=["ESTADO_INEXISTENTE"]
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

        self.client.force_login(self.ejecutivo)
        self.assertEqual(self._endpoint(estado).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("garantias:panel_garantias")).status_code,
            200,
        )
        self.client.logout()
        anonymous = self.client.get(url, {"offset": "0", "loaded": ""})
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login/", anonymous.url)

    def test_javascript_concurrencia_reconciliacion_y_delegacion(self):
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("const columnLoadRequests = new Map()", javascript)
        self.assertIn("if (existing) return existing.promise", javascript)
        self.assertIn("entry.controller.abort()", javascript)
        self.assertIn("requestVersion !== boardVersion", javascript)
        self.assertIn("Tarjeta duplicada o incompatible.", javascript)
        self.assertIn("staleIds.forEach", javascript)
        self.assertIn("data-garantia-load-more", javascript)
        self.assertIn("No se pudieron cargar las tarjetas.", javascript)
        self.assertIn("invalidateColumnLoads();", javascript)
        self.assertIn("root.dataset.panelJsInitialized = '1'", javascript)
        self.assertEqual(javascript.count("Sortable.create("), 2)
        self.assertEqual(
            javascript.count("root.addEventListener('click'"), 1
        )
        self.assertEqual(
            javascript.count("root.addEventListener('change'"), 1
        )
        self.assertIn(
            "const statusButton = e.target.closest('.kanban-status-control__option[data-status-option]');",
            javascript,
        )
        self.assertIn("handleGarantiaStateChange(stateSelect, statusButton);", javascript)
        self.assertIn("triggerElement: statusButton,", javascript)
        self.assertIn("trigger: triggerElement === stateSelect ? 'select' : 'button',", javascript)
        self.assertIn(
            "const csrfToken = window.getCSRFToken?.(triggerElement?.closest('form') || triggerElement || document);",
            javascript,
        )
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", javascript)
        self.assertIn("'X-CSRFToken': csrfToken", javascript)
        self.assertIn("button.classList.toggle('active', isActive);", javascript)


class GarantiasInlineCreateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_inline_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.client.force_login(self.admin)
        self.cliente = Cliente.objects.create(nombre="Cliente inline")
        self.asignado = User.objects.create_user(
            username="asignado_inline_create_garantias",
            password="pass123",
            first_name="Asignado",
        )
        self.etiqueta = GarantiaEtiqueta.objects.create(
            nombre="Urgente",
            color="#FF0000",
        )

    def test_panel_no_instancia_formulario_inline_y_conserva_columnas(self):
        with patch(
            "garantias.views.GarantiaInlineCreateForm",
            side_effect=AssertionError("No debe instanciarse en el GET inicial"),
        ):
            response = self.client.get(reverse("garantias:panel_garantias"))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("inline_form", response.context)
        html = response.content.decode()
        self.assertEqual(
            len(re.findall(r"<form\b[^>]*data-garantia-inline-form=", html)),
            0,
        )
        self.assertEqual(
            len(re.findall(r"<button\b[^>]*data-garantia-inline-open=", html)),
            1,
        )
        self.assertEqual(
            len(re.findall(r"<section\b[^>]*garantias-column", html)),
            3,
        )
        self.assertEqual(
            len(re.findall(r"<div\b[^>]*data-garantia-inline-shared-slot=", html)),
            1,
        )

    def test_endpoint_formulario_inline_admin_ejecutivo_y_solo_get(self):
        url = reverse("garantias:formulario_garantia_inline")
        total = Garantia.objects.count()

        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-garantia-inline-form-fragment="1"')
        self.assertContains(response, 'data-garantia-inline-form="1"')
        self.assertContains(response, 'enctype="multipart/form-data"')
        self.assertContains(response, 'data-garantia-link-rows="1"')
        for field_name in ("titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "archivos", "estado"):
            self.assertContains(response, f'name="{field_name}"')
        self.assertEqual(Garantia.objects.count(), total)

        ejecutivo = get_user_model().objects.create_user(
            username="ejecutivo_form_garantias",
            password="pass123",
            first_name="Ejecutivo",
        )
        self.client.force_login(ejecutivo)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.put(url).status_code, 405)

    def test_endpoint_formulario_inline_anonimo_redirige(self):
        self.client.logout()
        response = self.client.get(
            reverse("garantias:formulario_garantia_inline")
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_javascript_carga_unica_reintento_y_tom_select_seguro(self):
        response = self.client.get(reverse("garantias:panel_garantias"))
        html = response.content.decode()
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="panel-garantias-config"', html)
        self.assertIn("/static/garantias/js/panel_garantias.js", html)
        self.assertNotIn("let inlineFormLoadPromise = null", html)
        self.assertEqual(javascript.count("let inlineFormLoadPromise = null"), 1)
        self.assertIn("if (inlineFormLoadPromise) return inlineFormLoadPromise", javascript)
        self.assertIn("latestInlineTarget = target", javascript)
        self.assertIn("inlineFormLoadPromise = null", javascript)
        self.assertIn("redirect: 'error'", javascript)
        self.assertIn("if (inlineForm.dataset.submitting === 'true') return", javascript)
        self.assertIn("if (select.tomselect) return", javascript)
        self.assertIn("select.tomselect.destroy()", javascript)
        self.assertIn("function showToast(message, level)", javascript)
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", javascript)
        self.assertIn("error?.data?.message || extractJsonErrors(error) || requestErrorMessage(error)", javascript)
        self.assertIn("data-garantia-link-add", javascript)
        self.assertIn("data-garantia-link-remove", javascript)
        self.assertIn("if (!activeFilter) {", javascript)
        self.assertEqual(javascript.count("root.addEventListener('submit'"), 1)
        self.assertIn("async function readDetailFormResponse(response)", javascript)
        self.assertIn("if (data.status === 'validation_error') {", javascript)
        self.assertIn("let detailRequestController = null", javascript)
        self.assertIn("DETAIL_REQUEST_TIMEOUT_MS = 15000", javascript)
        self.assertIn("abortActiveDetailRequest()", javascript)
        self.assertIn("data-garantia-detail-retry=\"1\"", javascript)
        self.assertIn("Reintentar", javascript)

    def test_creacion_inline_devuelve_json_y_tarjeta(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "titulo": "Nueva garantia inline",
                "cliente": self.cliente.pk,
                "prioridad": Garantia.Prioridad.ALTA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["message"], "Garantia creada correctamente.")
        self.assertEqual(data["estado"], Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(data["column_count"], 1)
        self.assertEqual(data["garantia_id"], data["id"])
        self.assertIn("Nueva garantia inline", data["card_html"])

        garantia = Garantia.objects.get(pk=data["id"])
        self.assertEqual(garantia.creado_por, self.admin)
        self.assertEqual(garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(garantia.columna.codigo, Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(garantia.cliente_id, self.cliente.pk)

    def test_creacion_inline_invalida_devuelve_errores_y_html(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "titulo": "Demo",
                "prioridad": "INVALIDA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("prioridad", data["errors"])
        self.assertEqual(data["message"], "Revisa los campos marcados.")
        self.assertIn('data-garantia-inline-form-fragment="1"', data["html"])
        self.assertIn(
            f'value="{Garantia.Estado.SOLICITUD_NAVIERA}"',
            data["html"],
        )

    def test_creacion_inline_guarda_todos_los_campos_relaciones_y_adjuntos(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "estado": Garantia.Estado.SOLICITUD_NAVIERA,
                "titulo": "Nueva garantia completa",
                "descripcion": "Descripcion de prueba",
                "cliente": self.cliente.pk,
                "prioridad": Garantia.Prioridad.URGENTE,
                "fecha_vencimiento": "2026-08-20",
                "asignados": [self.asignado.pk],
                "etiquetas": [self.etiqueta.pk],
                "enlace_titulo": ["Factura", "Seguimiento"],
                "enlace_url": ["https://ejemplo.test/factura", "https://ejemplo.test/seguimiento"],
                "archivos": [
                    SimpleUploadedFile("evidencia-1.pdf", b"pdf", content_type="application/pdf"),
                    SimpleUploadedFile("evidencia-2.xlsx", b"xlsx", content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                ],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertEqual(data["garantia_id"], data["id"])
        self.assertIn(f'id="garantia-{data["id"]}"', data["card_html"])
        self.assertEqual(data["estado"], Garantia.Estado.SOLICITUD_NAVIERA)

        garantia = Garantia.objects.get(pk=data["id"])
        self.assertEqual(garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(garantia.columna.codigo, Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(garantia.descripcion, "Descripcion de prueba")
        self.assertEqual(garantia.prioridad, Garantia.Prioridad.URGENTE)
        self.assertEqual(str(garantia.fecha_vencimiento), "2026-08-20")
        self.assertEqual(list(garantia.asignados.values_list("pk", flat=True)), [self.asignado.pk])
        self.assertEqual(list(garantia.etiquetas.values_list("pk", flat=True)), [self.etiqueta.pk])
        self.assertEqual(GarantiaArchivo.objects.filter(garantia=garantia).count(), 2)
        self.assertEqual(GarantiaEnlace.objects.filter(garantia=garantia).count(), 2)

    def test_creacion_inline_rechaza_columna_distinta_a_la_primera_activa(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "estado": Garantia.Estado.DEVOLUCION_CLIENTE,
                "titulo": "Bloqueada por columna",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "Solo se pueden crear tarjetas desde la primera columna activa.",
        )
        self.assertFalse(
            Garantia.objects.filter(titulo="Bloqueada por columna").exists()
        )

    def test_creacion_inline_titulo_vacio_y_url_invalida_no_generan_registros_parciales(self):
        before = Garantia.objects.count()
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {"titulo": "   "},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("titulo", response.json()["errors"])
        self.assertEqual(Garantia.objects.count(), before)

        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "titulo": "Garantia con URL invalida",
                "enlace_titulo": ["Factura"],
                "enlace_url": ["nota-sin-url"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("enlaces", response.json()["errors"])
        self.assertEqual(Garantia.objects.count(), before)
        self.assertEqual(GarantiaEnlace.objects.count(), 0)
        self.assertEqual(GarantiaArchivo.objects.count(), 0)

    def test_creacion_inline_sin_ajax_falla(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "estado": Garantia.Estado.SOLICITUD_NAVIERA,
                "titulo": "Sin ajax",
            },
        )
        self.assertEqual(response.status_code, 400)


class GarantiasEstadoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_estado_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(
            titulo="Estado garantia",
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )

    def test_actualizar_estado_ajax_persiste_y_devuelve_json(self):
        response = self.client.post(
            reverse("garantias:actualizar_estado_garantia"),
            {
                "garantia_id": self.garantia.pk,
                "nuevo_estado": Garantia.Estado.DEVOLUCION_CLIENTE,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.estado, Garantia.Estado.DEVOLUCION_CLIENTE)
        self.assertEqual(self.garantia.columna.codigo, Garantia.Estado.DEVOLUCION_CLIENTE)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["estado"], Garantia.Estado.DEVOLUCION_CLIENTE)


class GarantiasColumnasDinamicasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_columnas_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.ejecutivo = User.objects.create_user(
            username="ejecutivo_columnas_garantias",
            password="pass123",
            first_name="Ejecutivo",
        )
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(
            titulo="Estado garantia columnas",
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )

    def test_columnas_iniciales_quedan_registradas_con_codigos_base(self):
        self.assertEqual(
            list(
                GarantiaColumna.objects.filter(activa=True).values_list("codigo", flat=True)
            ),
            [
                Garantia.Estado.SOLICITUD_NAVIERA,
                Garantia.Estado.PAGO_NAVIERA_ZAHA,
                Garantia.Estado.DEVOLUCION_CLIENTE,
            ],
        )
        primera_columna = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.SOLICITUD_NAVIERA
        )
        self.assertEqual(primera_columna.nombre, "En proceso")
        self.assertFalse(
            GarantiaColumna.objects.filter(codigo=Garantia.Estado.EN_PROCESO).exists()
        )

    def test_panel_muestra_una_sola_columna_en_proceso_y_sigue_primera(self):
        response = self.client.get(reverse("garantias:panel_garantias"))
        columnas = response.context["columnas_kanban"]

        self.assertEqual(response.status_code, 200)
        self.assertEqual([columna["nombre"] for columna in columnas].count("En proceso"), 1)
        self.assertEqual(columnas[0]["codigo"], Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertContains(response, "+ Nueva garant")

    def test_estado_en_proceso_legacy_se_normaliza_a_la_columna_superviviente(self):
        garantia = Garantia.objects.create(
            titulo="Estado legacy",
            creado_por=self.admin,
            estado=Garantia.Estado.EN_PROCESO,
        )

        garantia.refresh_from_db()
        self.assertEqual(garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)
        self.assertEqual(garantia.columna.codigo, Garantia.Estado.SOLICITUD_NAVIERA)

    def test_crear_columna_devuelve_html_y_codigo_generado(self):
        response = self.client.post(
            reverse("garantias:columna_crear"),
            {"nombre": "Revisión final"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["columna_codigo"], "REVISION_FINAL")
        self.assertIn('data-columna-codigo="REVISION_FINAL"', data["html"])

    def test_editar_columna_conserva_codigo_y_cambia_nombre(self):
        columna = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.PAGO_NAVIERA_ZAHA
        )
        response = self.client.post(
            reverse("garantias:columna_editar", args=[columna.pk]),
            {"nombre": "Seguimiento activo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        columna.refresh_from_db()
        self.assertEqual(columna.codigo, Garantia.Estado.PAGO_NAVIERA_ZAHA)
        self.assertEqual(columna.nombre, "Seguimiento activo")

    def test_reordenar_columnas_actualiza_orden(self):
        columnas = list(GarantiaColumna.objects.filter(activa=True).order_by("orden", "id"))
        nuevo_orden = [str(columna.pk) for columna in reversed(columnas)]
        response = self.client.post(
            reverse("garantias:columna_reordenar"),
            {"columnas[]": nuevo_orden},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            list(
                GarantiaColumna.objects.filter(activa=True)
                .order_by("orden", "id")
                .values_list("pk", flat=True)
            ),
            [int(value) for value in nuevo_orden],
        )

    def test_panel_mueve_alta_manual_a_la_nueva_primera_columna_tras_reordenar(self):
        response = self.client.get(reverse("garantias:panel_garantias"))
        html = response.content.decode()
        self.assertEqual(html.count('data-garantia-inline-open="1"'), 1)

        columnas = list(GarantiaColumna.objects.filter(activa=True).order_by("orden", "id"))
        nuevo_orden = [str(columna.pk) for columna in reversed(columnas)]
        reorder_response = self.client.post(
            reverse("garantias:columna_reordenar"),
            {"columnas[]": nuevo_orden},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(reorder_response.status_code, 200)

        nuevo_primero = GarantiaColumna.objects.filter(activa=True).order_by("orden", "id").first()
        response = self.client.get(reverse("garantias:panel_garantias"))
        html = response.content.decode()
        self.assertEqual(html.count('data-garantia-inline-open="1"'), 1)
        self.assertIn(f'data-columna-id="{nuevo_primero.pk}"', html)

    def test_eliminar_columna_con_garantias_reubica_y_sincroniza_estado(self):
        origen = GarantiaColumna.objects.create(
            nombre="Temporal",
            codigo="TEMPORAL",
            orden=99,
            creada_por=self.admin,
        )
        destino = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.PAGO_NAVIERA_ZAHA
        )
        garantia = Garantia.objects.create(
            titulo="Mover al eliminar",
            creado_por=self.admin,
            estado=origen.codigo,
            columna=origen,
        )
        response = self.client.post(
            reverse("garantias:columna_eliminar", args=[origen.pk]),
            {"columna_destino_id": str(destino.pk)},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        garantia.refresh_from_db()
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
        self.assertEqual(garantia.columna_id, destino.pk)
        self.assertEqual(garantia.estado, destino.codigo)

    def test_no_permite_eliminar_columna_base(self):
        columna = GarantiaColumna.objects.get(codigo=Garantia.Estado.SOLICITUD_NAVIERA)
        response = self.client.post(
            reverse("garantias:columna_eliminar", args=[columna.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("dependencias criticas", response.json()["error"])

    def test_estado_update_sincroniza_estado_y_columna(self):
        destino = GarantiaColumna.objects.get(codigo=Garantia.Estado.PAGO_NAVIERA_ZAHA)
        garantia = Garantia.objects.create(
            titulo="Sync estado columna",
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )
        response = self.client.post(
            reverse("garantias:actualizar_estado_garantia"),
            {
                "garantia_id": garantia.pk,
                "nuevo_estado": destino.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        garantia.refresh_from_db()
        self.assertEqual(garantia.estado, destino.codigo)
        self.assertEqual(garantia.columna_id, destino.pk)

    def test_actualizar_estado_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="admin_columnas_garantias", password="pass123")
        client.get(reverse("garantias:panel_garantias"))
        response_sin_csrf = client.post(
            reverse("garantias:actualizar_estado_garantia"),
            {
                "garantia_id": self.garantia.pk,
                "nuevo_estado": Garantia.Estado.DEVOLUCION_CLIENTE,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response_sin_csrf.status_code, 403)

    def test_detalle_layout_drawer_renderiza(self):
        response = self.client.get(
            reverse("garantias:detalle_garantia", args=[self.garantia.pk]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "garantia-drawer__panel")
        self.assertContains(response, 'name="descripcion"')
        self.assertContains(response, 'name="cliente"')

    def test_detalle_layout_modal_renderiza_clases_compartidas(self):
        response = self.client.get(
            reverse("garantias:detalle_garantia_parcial", args=[self.garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "zaha-detail-modal__header")
        self.assertContains(response, "zaha-detail-modal__body")
        self.assertContains(response, "zaha-detail-modal__footer")
        self.assertNotEqual(response.redirect_chain if hasattr(response, "redirect_chain") else [], [("", 302)])
        self.assertTrue(response.content.strip())

    def test_detalle_parcial_inexistente_devuelve_404(self):
        response = self.client.get(
            reverse("garantias:detalle_garantia_parcial", args=[999999]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 404)

    def test_detalle_get_no_modifica_fecha_ni_descripcion(self):
        self.garantia.descripcion = "Prueba"
        self.garantia.fecha_vencimiento = date(2026, 8, 25)
        self.garantia.save(update_fields=["descripcion", "fecha_vencimiento"])

        response = self.client.get(
            reverse("garantias:detalle_garantia_parcial", args=[self.garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.descripcion, "Prueba")
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 8, 25))

    def test_detalle_renderiza_fecha_dateinput_en_formato_iso(self):
        self.garantia.fecha_vencimiento = date(2026, 8, 25)
        self.garantia.save(update_fields=["fecha_vencimiento"])

        response = self.client.get(
            reverse("garantias:detalle_garantia_parcial", args=[self.garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="fecha_vencimiento"')
        self.assertContains(response, 'value="2026-08-25"')


class GarantiasCopiarPegarTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="garantias_copy_admin",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.ejecutivo = User.objects.create_user(
            username="garantias_copy_exec",
            password="pass123",
            first_name="Ejecutivo",
        )
        self.cliente = Cliente.objects.create(nombre="Cliente copiado garantias")
        self.etiqueta_a = GarantiaEtiqueta.objects.create(
            nombre="Etiqueta copy A",
            color="#AA0000",
        )
        self.etiqueta_b = GarantiaEtiqueta.objects.create(
            nombre="Etiqueta copy B",
            color="#00AA00",
        )
        self.columna_origen = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.SOLICITUD_NAVIERA
        )
        self.columna_destino = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.PAGO_NAVIERA_ZAHA
        )
        self.columna_tercera = GarantiaColumna.objects.get(
            codigo=Garantia.Estado.DEVOLUCION_CLIENTE
        )
        self.garantia = Garantia.objects.create(
            titulo="Garantia original copy",
            descripcion="Descripcion copy",
            cliente=self.cliente,
            prioridad=Garantia.Prioridad.ALTA,
            estado=self.columna_origen.codigo,
            columna=self.columna_origen,
            fecha_vencimiento=date(2026, 8, 20),
            creado_por=self.admin,
        )
        self.garantia.asignados.set([self.admin, self.ejecutivo])
        self.garantia.etiquetas.set([self.etiqueta_a, self.etiqueta_b])
        self.comentario = GarantiaComentario.objects.create(
            garantia=self.garantia,
            usuario=self.admin,
            comentario="No copiar comentario",
        )
        self.archivo = GarantiaArchivo.objects.create(
            garantia=self.garantia,
            archivo=SimpleUploadedFile(
                "garantia-copy-source.txt",
                b"contenido",
                content_type="text/plain",
            ),
            subido_por=self.admin,
        )
        self.enlace = GarantiaEnlace.objects.create(
            garantia=self.garantia,
            titulo="No copiar enlace",
            url="https://example.com/original",
            creado_por=self.admin,
        )
        self.client = Client()

    def _paste(self, user, *, columna_id=None, tarjeta_id=None, modulo="garantias"):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "garantias:tarjeta_pegar",
                args=[columna_id or self.columna_destino.pk],
            ),
            {
                "tarjeta_id": tarjeta_id or self.garantia.pk,
                "modulo": modulo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_admin_puede_copiar_y_pegar(self):
        response = self._paste(self.admin)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["columna_id"], self.columna_destino.pk)
        self.assertIn('data-garantia-card="1"', data["html"])
        self.assertIn("garantia-card__copy-btn", data["html"])
        self.assertNotIn("Acciones", data["html"])

    def test_ejecutivo_puede_copiar_y_pegar(self):
        response = self._paste(self.ejecutivo)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])

    def test_copia_no_modifica_original_y_genera_nuevo_id(self):
        snapshot = {
            "titulo": self.garantia.titulo,
            "descripcion": self.garantia.descripcion,
            "cliente_id": self.garantia.cliente_id,
            "prioridad": self.garantia.prioridad,
            "estado": self.garantia.estado,
            "columna_id": self.garantia.columna_id,
            "creado_por_id": self.garantia.creado_por_id,
        }
        response = self._paste(self.ejecutivo)
        nueva = Garantia.objects.get(pk=response.json()["tarjeta_id"])
        self.garantia.refresh_from_db()
        self.assertNotEqual(nueva.pk, self.garantia.pk)
        self.assertEqual(
            {
                "titulo": self.garantia.titulo,
                "descripcion": self.garantia.descripcion,
                "cliente_id": self.garantia.cliente_id,
                "prioridad": self.garantia.prioridad,
                "estado": self.garantia.estado,
                "columna_id": self.garantia.columna_id,
                "creado_por_id": self.garantia.creado_por_id,
            },
            snapshot,
        )

    def test_copia_sincroniza_estado_columna_y_campos_editables(self):
        response = self._paste(self.ejecutivo)
        nueva = Garantia.objects.get(pk=response.json()["tarjeta_id"])
        self.assertEqual(nueva.columna_id, self.columna_destino.pk)
        self.assertEqual(nueva.estado, self.columna_destino.codigo)
        self.assertEqual(nueva.titulo, self.garantia.titulo)
        self.assertEqual(nueva.descripcion, self.garantia.descripcion)
        self.assertEqual(nueva.cliente_id, self.garantia.cliente_id)
        self.assertEqual(nueva.prioridad, self.garantia.prioridad)
        self.assertEqual(nueva.fecha_vencimiento, self.garantia.fecha_vencimiento)
        self.assertEqual(nueva.creado_por, self.ejecutivo)

    def test_copia_relaciones_validas_y_excluye_historial_archivos_enlaces(self):
        response = self._paste(self.admin)
        nueva = Garantia.objects.get(pk=response.json()["tarjeta_id"])
        self.assertEqual(
            list(nueva.asignados.order_by("pk").values_list("pk", flat=True)),
            list(self.garantia.asignados.order_by("pk").values_list("pk", flat=True)),
        )
        self.assertEqual(
            list(nueva.etiquetas.order_by("pk").values_list("pk", flat=True)),
            list(self.garantia.etiquetas.order_by("pk").values_list("pk", flat=True)),
        )
        self.assertFalse(nueva.comentarios.exists())
        self.assertFalse(nueva.archivos.exists())
        self.assertFalse(nueva.enlaces.exists())

    def test_modelo_no_tiene_one_to_one_ni_identificadores_unicos_copiables(self):
        one_to_one_fields = [
            field.name for field in Garantia._meta.get_fields()
            if getattr(field, "one_to_one", False) and not getattr(field, "auto_created", False)
        ]
        unique_fields = [
            field.name for field in Garantia._meta.fields
            if getattr(field, "unique", False) and not field.primary_key
        ]
        self.assertEqual(one_to_one_fields, [])
        self.assertEqual(unique_fields, [])
        self.assertEqual(self._paste(self.admin).status_code, 201)

    def test_no_puede_pegar_en_columna_inexistente_o_inactiva(self):
        inexistente = self._paste(self.admin, columna_id=999999)
        self.assertEqual(inexistente.status_code, 404)

        self.columna_destino.activa = False
        self.columna_destino.save(update_fields=["activa"])
        inactiva = self._paste(self.admin)
        self.assertEqual(inactiva.status_code, 404)

    def test_no_puede_copiar_tarjeta_inexistente_peticion_invalida_o_modulo_ajeno(self):
        total_antes = Garantia.objects.count()
        inexistente = self._paste(self.admin, tarjeta_id=999999)
        self.assertEqual(inexistente.status_code, 404)

        invalida = self.client.post(
            reverse("garantias:tarjeta_pegar", args=[self.columna_destino.pk]),
            {"tarjeta_id": "abc", "modulo": "garantias"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalida.status_code, 400)

        modulo_ajeno = self._paste(self.admin, modulo="operaciones")
        self.assertEqual(modulo_ajeno.status_code, 400)
        self.assertEqual(Garantia.objects.count(), total_antes)

    def test_usuario_sin_permiso_recibe_403(self):
        self.client.force_login(self.admin)
        with patch("garantias.views._puede_operar_garantias", return_value=False):
            response = self.client.post(
                reverse("garantias:tarjeta_pegar", args=[self.columna_destino.pk]),
                {"tarjeta_id": self.garantia.pk, "modulo": "garantias"},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            Garantia.objects.filter(
                titulo=self.garantia.titulo,
                columna=self.columna_destino,
                creado_por=self.admin,
            )
            .exclude(pk=self.garantia.pk)
            .exists()
        )

    def test_respuesta_exitosa_incluye_html_y_tarjeta_resultante_se_puede_mover(self):
        response = self._paste(self.admin)
        data = response.json()
        self.assertIn("<article", data["html"])
        nueva = Garantia.objects.get(pk=data["tarjeta_id"])

        self.client.force_login(self.admin)
        move_response = self.client.post(
            reverse("garantias:actualizar_estado_garantia"),
            {
                "garantia_id": nueva.pk,
                "nuevo_estado": self.columna_tercera.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(move_response.status_code, 200)
        nueva.refresh_from_db()
        self.assertEqual(nueva.columna_id, self.columna_tercera.pk)
        self.assertEqual(nueva.estado, self.columna_tercera.codigo)

class GarantiasInlineUpdateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_inline_update_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.asignado = User.objects.create_user(
            username="asignado_inline_garantias",
            password="pass123",
            first_name="Asignado",
        )
        self.cliente = Cliente.objects.create(nombre="Cliente update")
        self.otro_cliente = Cliente.objects.create(nombre="Otro cliente update")
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(
            titulo="Original",
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )
        self.garantia.cliente = self.cliente
        self.garantia.descripcion = "Descripcion que debe conservarse"
        self.garantia.prioridad = Garantia.Prioridad.ALTA
        self.garantia.fecha_vencimiento = date(2026, 2, 20)
        self.garantia.save()
        self.garantia.asignados.add(self.asignado)

    def assert_campos_ajenos_conservados(self):
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.titulo, "Original")
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.descripcion, "Descripcion que debe conservarse")
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.ALTA)
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 2, 20))
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])
        self.assertEqual(self.garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)

    def quick_edit_data(self, **changes):
        data = {
            "titulo": "Original",
            "descripcion": "Descripcion que debe conservarse",
            "cliente": self.cliente.pk,
            "prioridad": Garantia.Prioridad.ALTA,
            "fecha_vencimiento": date(2026, 2, 20).isoformat(),
            "asignados": [self.asignado.pk],
        }
        data.update(changes)
        return data

    def test_inline_update_titulo(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(titulo="Nuevo titulo"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.titulo, "Nuevo titulo")
        self.assertTrue(response.json()["ok"])
        self.assertIn('data-garantia-card="1"', response.json()["html"])

    def test_inline_update_preserva_los_campos_ajenos_y_devuelve_tarjeta_completa(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(titulo="Solo cambia el titulo"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.descripcion, "Descripcion que debe conservarse")
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.ALTA)
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 2, 20))
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])
        html = response.json()["html"]
        self.assertNotIn("Descripcion que debe conservarse", html)
        self.assertNotIn(str(self.cliente), html)
        self.assertIn('data-garantia-state-select="1"', html)

    def test_inline_update_fecha_vencimiento(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(fecha_vencimiento=date(2026, 1, 15).isoformat()),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 1, 15))
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.ALTA)
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])
        self.assertTrue(response.json()["ok"])

    def test_inline_update_prioridad_conserva_los_demas_campos(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(prioridad=Garantia.Prioridad.BAJA),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.BAJA)
        self.assertEqual(self.garantia.titulo, "Original")
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.descripcion, "Descripcion que debe conservarse")
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 2, 20))
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])
        self.assertEqual(self.garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)

    def test_inline_update_cliente_conserva_los_demas_campos(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(cliente=self.otro_cliente.pk),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.cliente, self.otro_cliente)
        self.assertEqual(self.garantia.titulo, "Original")
        self.assertEqual(self.garantia.descripcion, "Descripcion que debe conservarse")
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.ALTA)
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 2, 20))
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])
        self.assertEqual(self.garantia.estado, Garantia.Estado.SOLICITUD_NAVIERA)

    def test_inline_update_permite_vaciar_fecha_vencimiento(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(fecha_vencimiento=""),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertIsNone(self.garantia.fecha_vencimiento)
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.ALTA)
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])

    def test_inline_update_asignados(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(
            list(self.garantia.asignados.values_list("pk", flat=True)),
            [self.asignado.pk],
        )

    def test_inline_update_asignados_permite_vaciar_la_relacion(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(asignados=[]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.garantia.asignados.exists())

    def test_inline_update_sin_asignados_no_modifica_la_relacion(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(titulo="Sin tocar asignados"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])

    def test_inline_update_invalido_no_modifica_la_garantia(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(fecha_vencimiento="fecha-invalida"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("fecha_vencimiento", response.json()["errors"])
        self.assert_campos_ajenos_conservados()

    def test_inline_update_exitosa_devuelve_tarjeta_completa(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(titulo="Tarjeta completa"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        html = response.json()["html"]
        self.assertIn(f'id="garantia-{self.garantia.pk}"', html)
        self.assertIn("garantia-card card", html)
        self.assertIn('data-garantia-card="1"', html)
        self.assertIn('data-garantia-id="', html)
        self.assertIn('data-garantia-state-select="1"', html)
        self.assertIn('data-status-option="', html)
        self.assertIn('data-garantia-modal-open="1"', html)
        self.assertIn("garantia-card__comments", html)

    def test_inline_update_get_devuelve_formulario_completo(self):
        response = self.client.get(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn('data-garantia-quick-edit-form="1"', response.json()["html"])

    def test_inline_update_invalido_devuelve_formulario_con_errores(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            self.quick_edit_data(fecha_vencimiento="invalida"),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertIn('data-garantia-quick-edit-form="1"', response.json()["html"])


class GarantiasComentarioTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_comentarios_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(
            titulo="Garantia comentarios",
            creado_por=self.admin,
            estado=Garantia.Estado.EN_PROCESO,
        )
        self.otra_garantia = Garantia.objects.create(
            titulo="Otra garantia comentarios",
            creado_por=self.admin,
            estado=Garantia.Estado.EN_PROCESO,
        )

    def test_comentario_ajax_devuelve_html_parcial_y_contador(self):
        response = self.client.post(
            reverse("garantias:agregar_comentario", args=[self.garantia.pk]),
            {
                "comentario": "Primer comentario",
                "layout": "drawer",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["comentarios_count"], 1)
        self.assertIn('data-garantia-comments-section="1"', data["html"])
        self.assertIn("Primer comentario", data["html"])
        self.assertEqual(GarantiaComentario.objects.filter(garantia=self.garantia).count(), 1)

    def test_comentario_ajax_invalido_conserva_formulario_y_errores(self):
        response = self.client.post(
            reverse("garantias:agregar_comentario", args=[self.garantia.pk]),
            {
                "comentario": "",
                "layout": "modal",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertEqual(data["status"], "error")
        self.assertIn("comentario", data["errors"])
        self.assertIn('data-garantia-comentario-form="1"', data["html"])
        self.assertEqual(GarantiaComentario.objects.filter(garantia=self.garantia).count(), 0)

    def test_comentario_se_asocia_solo_a_la_garantia_correcta(self):
        response = self.client.post(
            reverse("garantias:agregar_comentario", args=[self.garantia.pk]),
            {
                "comentario": "Comentario garantia A",
                "layout": "drawer",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(
            GarantiaComentario.objects.filter(
                garantia=self.garantia,
                comentario="Comentario garantia A",
            ).exists()
        )
        self.assertFalse(
            GarantiaComentario.objects.filter(
                garantia=self.otra_garantia,
                comentario="Comentario garantia A",
            ).exists()
        )

    def test_agregar_comentario_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="admin_comentarios_garantias", password="pass123")

        response_sin_csrf = client.post(
            reverse("garantias:agregar_comentario", args=[self.garantia.pk]),
            {"comentario": "Comentario sin CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response_sin_csrf.status_code, 403)
        self.assertFalse(GarantiaComentario.objects.filter(comentario="Comentario sin CSRF").exists())

        request = HttpRequest()
        csrftoken = get_token(request)
        client.cookies.load({"csrftoken": csrftoken})

        response_con_csrf = client.post(
            reverse("garantias:agregar_comentario", args=[self.garantia.pk]),
            {"comentario": "Comentario con CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken
        )
        self.assertEqual(response_con_csrf.status_code, 200)
        data = response_con_csrf.json()
        self.assertTrue(data["success"])
        self.assertTrue(GarantiaComentario.objects.filter(comentario="Comentario con CSRF").exists())


class GarantiaDetalleEdicionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_detalle_edicion_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
            first_name="Admin",
        )
        self.client.force_login(self.admin)
        self.cliente = Cliente.objects.create(nombre="Cliente detalle")
        self.asignado = User.objects.create_user(
            username="asignado_detalle_edicion_garantias",
            password="pass123",
            first_name="Asignado",
        )
        self.garantia = Garantia.objects.create(
            titulo="Garantia detalle",
            descripcion="Descripcion inicial",
            cliente=self.cliente,
            prioridad=Garantia.Prioridad.MEDIA,
            fecha_vencimiento=date(2026, 8, 25),
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )
        self.garantia.asignados.add(self.asignado)

    def test_detalle_precarga_descripcion(self):
        response = self.client.get(
            reverse("garantias:detalle_garantia_parcial", args=[self.garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="descripcion"')
        self.assertContains(response, "Descripcion inicial")

    def test_editar_garantia_persiste_descripcion_y_conserva_otros_campos(self):
        response = self.client.post(
            reverse("garantias:editar_garantia", args=[self.garantia.pk]),
            {
                "titulo": "Garantia detalle",
                "descripcion": "Descripcion modificada",
                "cliente": self.cliente.pk,
                "prioridad": Garantia.Prioridad.MEDIA,
                "fecha_vencimiento": "2026-08-25",
                "asignados": [self.asignado.pk],
                "layout": "modal",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.descripcion, "Descripcion modificada")
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 8, 25))
        self.assertEqual(self.garantia.cliente, self.cliente)
        self.assertEqual(self.garantia.prioridad, Garantia.Prioridad.MEDIA)
        self.assertEqual(list(self.garantia.asignados.all()), [self.asignado])


class GarantiasArchivosAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_archivos_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(titulo="Garantia archivos", creado_por=self.admin)

    def test_sube_archivo_y_devuelve_solo_su_seccion_y_contador(self):
        response = self.client.post(
            reverse("garantias:agregar_archivos", args=[self.garantia.pk]),
            {"archivos": SimpleUploadedFile("evidencia.txt", b"contenido", content_type="text/plain")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["files_count"], 1)
        self.assertIn('data-garantia-files-section="1"', data["files_html"])
        self.assertTrue(GarantiaArchivo.objects.filter(garantia=self.garantia).exists())

    def test_rechaza_archivo_no_permitido_sin_crearlo(self):
        response = self.client.post(
            reverse("garantias:agregar_archivos", args=[self.garantia.pk]),
            {"archivos": SimpleUploadedFile("ejecutable.exe", b"x")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertEqual(GarantiaArchivo.objects.filter(garantia=self.garantia).count(), 0)

    def test_elimina_solo_archivo_de_la_garantia_actual(self):
        archivo = GarantiaArchivo.objects.create(
            garantia=self.garantia,
            archivo=SimpleUploadedFile("evidencia.txt", b"contenido"),
            subido_por=self.admin,
        )
        otra = Garantia.objects.create(titulo="Otra garantia", creado_por=self.admin)
        ajeno = GarantiaArchivo.objects.create(
            garantia=otra,
            archivo=SimpleUploadedFile("ajeno.txt", b"contenido"),
            subido_por=self.admin,
        )
        response = self.client.post(
            reverse("garantias:eliminar_archivo", args=[self.garantia.pk, archivo.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(GarantiaArchivo.objects.filter(pk=archivo.pk).exists())
        self.assertTrue(GarantiaArchivo.objects.filter(pk=ajeno.pk).exists())


class GarantiasEnlacesAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_enlaces_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(titulo="Garantia enlaces", creado_por=self.admin)

    def test_crea_enlace_y_devuelve_solo_su_seccion_y_contador(self):
        response = self.client.post(
            reverse("garantias:agregar_enlace", args=[self.garantia.pk]),
            {"titulo": "Factura", "url": "https://ejemplo.test/factura"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["links_count"], 1)
        self.assertIn('data-garantia-links-section="1"', data["links_html"])
        self.assertTrue(GarantiaEnlace.objects.filter(garantia=self.garantia).exists())

    def test_rechaza_url_insegura_o_con_credenciales(self):
        response = self.client.post(
            reverse("garantias:agregar_enlace", args=[self.garantia.pk]),
            {"titulo": "Inseguro", "url": "ftp://usuario:clave@ejemplo.test/archivo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertFalse(GarantiaEnlace.objects.filter(garantia=self.garantia).exists())


class GarantiaEditarCSRFTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_csrf_editar",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.garantia = Garantia.objects.create(
            titulo="Garantia para CSRF",
            creado_por=self.admin,
        )

    def test_editar_garantia_csrf_validation(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="admin_csrf_editar", password="pass123")

        # 1. Hacer GET al panel/formulario para obtener cookie csrftoken
        panel_url = reverse("garantias:panel_garantias")
        client.get(panel_url)

        # 2. Intentar POST sin cabecera X-CSRFToken -> 403
        edit_url = reverse("garantias:editar_garantia", args=[self.garantia.pk])
        response_sin_csrf = client.post(
            edit_url,
            {"titulo": "Nuevo Titulo Sin CSRF"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response_sin_csrf.status_code, 403)

        # 3. Intentar POST con cabecera X-CSRFToken -> 200 (ya que es AJAX y responde JSON con status 200 en éxito)
        request = HttpRequest()
        csrftoken = get_token(request)
        client.cookies.load({"csrftoken": csrftoken})

        response_con_csrf = client.post(
            edit_url,
            {"titulo": "Nuevo Titulo Con CSRF"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken
        )
        self.assertEqual(response_con_csrf.status_code, 200)
        self.garantia.refresh_from_db()


class GarantiaAtomicidadTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_atomic_garantias",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(self.admin)
        self.cliente = Cliente.objects.create(nombre="Cliente atomicidad")
        self.garantia = Garantia.objects.create(
            titulo="Garantia base",
            cliente=self.cliente,
            creado_por=self.admin,
        )

    def test_crear_garantia_revierte_si_falla_guardado_de_adjuntos_o_enlaces(self):
        before = Garantia.objects.count()

        with patch(
            "garantias.views._guardar_adjuntos_enlaces",
            side_effect=RuntimeError("fallo adjuntos"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("garantias:crear_garantia"),
                    {
                        "titulo": "Garantia con fallo",
                        "cliente": self.cliente.pk,
                        "prioridad": Garantia.Prioridad.MEDIA,
                    },
                )

        self.assertEqual(Garantia.objects.count(), before)

    def test_editar_garantia_revierte_si_falla_guardado_de_adjuntos_o_enlaces(self):
        with patch(
            "garantias.views._guardar_adjuntos_enlaces",
            side_effect=RuntimeError("fallo adjuntos"),
        ):
            with self.assertRaises(RuntimeError):
                self.client.post(
                    reverse("garantias:editar_garantia", args=[self.garantia.pk]),
                    {
                        "titulo": "Titulo editado",
                        "descripcion": "",
                        "cliente": self.cliente.pk,
                        "prioridad": Garantia.Prioridad.ALTA,
                        "fecha_vencimiento": "",
                    },
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )

        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.titulo, "Garantia base")


class GarantiaEliminarCSRFTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin_csrf_eliminar",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.garantia = Garantia.objects.create(
            titulo="Garantia para eliminar",
            creado_por=self.admin,
        )

    def _csrf_client(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="admin_csrf_eliminar", password="pass123")
        client.get(reverse("garantias:panel_garantias"))
        return client, client.cookies["csrftoken"].value

    def test_post_ajax_con_csrf_elimina_y_devuelve_json(self):
        client, csrftoken = self._csrf_client()
        url = reverse("garantias:eliminar_garantia", args=[self.garantia.pk])

        self.assertTrue(Garantia.objects.filter(pk=self.garantia.pk).exists())

        response = client.post(
            url,
            {"layout": "drawer", "csrfmiddlewaretoken": csrftoken},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken,
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "status": "ok",
                "ok": True,
                "deleted": True,
                "id": self.garantia.pk,
                "garantia_id": self.garantia.pk,
                "message": "La tarjeta se envió a la papelera correctamente.",
            },
        )
        self.garantia.refresh_from_db()
        self.assertIsNotNone(self.garantia.eliminado_en)
        self.assertEqual(self.garantia.eliminado_por, self.admin)

    def test_post_sin_csrf_devuelve_403_y_no_elimina(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="admin_csrf_eliminar", password="pass123")
        url = reverse("garantias:eliminar_garantia", args=[self.garantia.pk])

        response = client.post(
            url,
            {"layout": "modal"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Garantia.objects.filter(pk=self.garantia.pk).exists())

    def test_get_no_elimina_y_responde_405(self):
        self.client.force_login(self.admin)
        url = reverse("garantias:eliminar_garantia", args=[self.garantia.pk])

        response = self.client.get(url)

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Garantia.objects.filter(pk=self.garantia.pk).exists())

    def test_usuario_no_autenticado_no_puede_eliminar(self):
        url = reverse("garantias:eliminar_garantia", args=[self.garantia.pk])

        response = self.client.post(url, {"layout": "modal"})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertTrue(Garantia.objects.filter(pk=self.garantia.pk).exists())



class GarantiaEtiquetasAjaxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpassword', is_superuser=True)
        self.client.login(username='testuser', password='testpassword')
        self.garantia_a = Garantia.objects.create(
            titulo='Garantia A',
            creado_por=self.user,
            estado=Garantia.Estado.EN_PROCESO,
            prioridad=Garantia.Prioridad.MEDIA,
        )
        self.garantia_b = Garantia.objects.create(
            titulo='Garantia B',
            creado_por=self.user,
            estado=Garantia.Estado.EN_PROCESO,
            prioridad=Garantia.Prioridad.MEDIA,
        )
        self.etiqueta1 = GarantiaEtiqueta.objects.create(nombre='Etiqueta 1', color='#ff0000')
        self.etiqueta2 = GarantiaEtiqueta.objects.create(nombre='Etiqueta 2', color='#00ff00')

    def test_asignar_etiqueta_existente(self):
        url = reverse('garantias:agregar_etiqueta_garantia', args=[self.garantia_a.id])
        response = self.client.post(url, {'etiquetas': [self.etiqueta1.id]}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.garantia_a.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_crear_y_asignar(self):
        url = reverse('garantias:crear_etiqueta_garantia', args=[self.garantia_a.id])
        response = self.client.post(url, {'nombre': 'Nueva Etiqueta', 'color': '#0000ff'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(GarantiaEtiqueta.objects.filter(nombre='Nueva Etiqueta').exists())
        self.assertTrue(self.garantia_a.etiquetas.filter(nombre='Nueva Etiqueta').exists())

    def test_desasignar_una(self):
        self.garantia_a.etiquetas.add(self.etiqueta1)
        url = reverse('garantias:quitar_etiqueta_garantia', args=[self.garantia_a.id, self.etiqueta1.id])
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.garantia_a.etiquetas.filter(id=self.etiqueta1.id).exists())
        
        # Test que NO se elimina de la BD global
        self.assertTrue(GarantiaEtiqueta.objects.filter(id=self.etiqueta1.id).exists())

    def test_desasignar_de_tarjeta_a_no_afecta_tarjeta_b(self):
        self.garantia_a.etiquetas.add(self.etiqueta1)
        self.garantia_b.etiquetas.add(self.etiqueta1)
        url = reverse('garantias:quitar_etiqueta_garantia', args=[self.garantia_a.id, self.etiqueta1.id])
        self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertFalse(self.garantia_a.etiquetas.filter(id=self.etiqueta1.id).exists())
        self.assertTrue(self.garantia_b.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_guardar_formulario_general_conserva_etiquetas(self):
        self.garantia_a.etiquetas.add(self.etiqueta1)
        url = reverse('garantias:editar_garantia', args=[self.garantia_a.id])
        # Actualizamos titulo
        response = self.client.post(url, {
            'titulo': 'Nuevo Titulo',
            'prioridad': Garantia.Prioridad.ALTA,
            'cliente': '',
            'layout': 'modal',
        })
        if response.status_code != 200 and response.status_code != 302:
            print(response.content.decode('utf-8'))
        self.garantia_a.refresh_from_db()
        self.assertTrue(self.garantia_a.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_rechazo_sin_ajax(self):
        url = reverse('garantias:agregar_etiqueta_garantia', args=[self.garantia_a.id])
        response = self.client.post(url, {'etiquetas': [self.etiqueta1.id]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Solicitud AJAX requerida.')

