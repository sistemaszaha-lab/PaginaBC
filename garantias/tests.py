import re
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
from datetime import date, timedelta

from clientes.models import Cliente

from .models import Garantia, GarantiaArchivo, GarantiaComentario, GarantiaEnlace

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

    def test_get_limita_diez_total_real_cuatro_columnas_y_sin_formularios(self):
        self._bulk(21)
        before = Garantia.objects.count()
        response = self.client.get(reverse("garantias:panel_garantias"))
        columna = self._columna(
            response, Garantia.Estado.SOLICITUD_NAVIERA
        )
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columnas_kanban"]), 4)
        self.assertEqual(columna["count"], 21)
        self.assertEqual(columna["loaded"], 10)
        self.assertEqual(len(columna["items"]), 10)
        self.assertTrue(columna["has_more"])
        self.assertEqual(html.count('data-garantia-card="1"'), 10)
        self.assertEqual(html.count('data-garantia-column="1"'), 4)
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

    def test_cuatro_columnas_limite_independiente_e_historicos_excluidos(self):
        for estado in Garantia.Estado.values:
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
            [10, 10, 10, 10],
        )
        self.assertEqual(
            sum(
                columna["has_more"]
                for columna in response.context["columnas_kanban"]
            ),
            4,
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
        estado = Garantia.Estado.EN_PROCESO
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
        self.assertEqual(javascript.count("Sortable.create("), 1)
        self.assertEqual(
            javascript.count("root.addEventListener('click'"), 1
        )
        self.assertEqual(
            javascript.count("root.addEventListener('change'"), 1
        )


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
            4,
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
        for field_name in ("titulo", "cliente", "prioridad", "estado"):
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
        self.assertIn("if (!activeFilter) {", javascript)
        self.assertEqual(javascript.count("root.addEventListener('submit'"), 1)

    def test_creacion_inline_devuelve_json_y_tarjeta(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "estado": Garantia.Estado.EN_PROCESO,
                "titulo": "Nueva garantia inline",
                "cliente": self.cliente.pk,
                "prioridad": Garantia.Prioridad.ALTA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estado"], Garantia.Estado.EN_PROCESO)
        self.assertEqual(data["column_count"], 1)
        self.assertIn("Nueva garantia inline", data["html"])

        garantia = Garantia.objects.get(pk=data["id"])
        self.assertEqual(garantia.creado_por, self.admin)
        self.assertEqual(garantia.estado, Garantia.Estado.EN_PROCESO)
        self.assertEqual(garantia.cliente_id, self.cliente.pk)

    def test_creacion_inline_invalida_devuelve_errores_y_html(self):
        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {"estado": "INVALIDO", "titulo": "Demo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("estado", data["errors"])

        response = self.client.post(
            reverse("garantias:crear_garantia_inline"),
            {
                "estado": Garantia.Estado.EN_PROCESO,
                "titulo": "Demo",
                "prioridad": "INVALIDA",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("prioridad", data["errors"])
        self.assertIn('data-garantia-inline-form-fragment="1"', data["html"])
        self.assertIn(
            f'value="{Garantia.Estado.EN_PROCESO}"',
            data["html"],
        )

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
        data = response.json()
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["estado"], Garantia.Estado.DEVOLUCION_CLIENTE)

    def test_detalle_layout_drawer_renderiza(self):
        response = self.client.get(
            reverse("garantias:detalle_garantia", args=[self.garantia.pk]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "garantia-drawer__panel")


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
        self.assertIn("Descripcion que debe conservarse", html)
        self.assertIn(str(self.cliente), html)
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
        self.assertEqual(self.garantia.titulo, "Nuevo Titulo Con CSRF")

