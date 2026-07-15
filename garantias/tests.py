from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from datetime import date

from clientes.models import Cliente

from .models import Garantia, GarantiaComentario


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
        self.client.force_login(self.admin)
        self.garantia = Garantia.objects.create(
            titulo="Original",
            creado_por=self.admin,
            estado=Garantia.Estado.SOLICITUD_NAVIERA,
        )

    def test_inline_update_titulo(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            {"field": "titulo", "titulo": "Nuevo titulo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.titulo, "Nuevo titulo")
        self.assertTrue(response.json()["ok"])

    def test_inline_update_fecha_vencimiento(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            {
                "field": "fecha_vencimiento",
                "fecha_vencimiento": date(2026, 1, 15).isoformat(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.fecha_vencimiento, date(2026, 1, 15))
        self.assertTrue(response.json()["ok"])

    def test_inline_update_asignados(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            {"field": "asignados", "asignados": [self.asignado.pk]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.garantia.refresh_from_db()
        self.assertEqual(
            list(self.garantia.asignados.values_list("pk", flat=True)),
            [self.asignado.pk],
        )

    def test_inline_update_rechaza_campo_no_permitido(self):
        response = self.client.post(
            reverse("garantias:actualizar_garantia_inline", args=[self.garantia.pk]),
            {"field": "descripcion", "descripcion": "No permitido"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])


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
