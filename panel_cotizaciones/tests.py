from datetime import date

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import reverse

from clientes.models import Cliente

from .forms import PanelCotizacionCreateForm
from .models import PanelCotizacion

User = get_user_model()


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
