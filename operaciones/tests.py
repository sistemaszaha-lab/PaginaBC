from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from .models import Operacion


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesPanelFiltroUsuariosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.asignado = User.objects.create_user(username="asignado", password="pass", first_name="Asignado")

        self.operacion = Operacion.objects.create(
            titulo="Op 1",
            creado_por=self.user,
        )
        self.operacion.asignados.add(self.asignado)

        self.client = Client()
        self.client.force_login(self.user)

    def test_panel_sin_param_usuarios(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"))
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_param_vacio_no_explota(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuarios": ""})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_all_no_explota(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuarios": "all"})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_ids_filtra(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuarios": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesDetalleModalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.operacion = Operacion.objects.create(titulo="Op 1", creado_por=self.user)

        self.client = Client()
        self.client.force_login(self.user)

    def test_detalle_operacion_endpoint(self):
        resp = self.client.get(reverse("operaciones:detalle_operacion", args=[self.operacion.id]))
        self.assertEqual(resp.status_code, 200)

    def test_editar_operacion_preserva_valores(self):
        # Crear asignados y etiquetas
        User = get_user_model()
        usuario_2 = User.objects.create_user(username="tester2", password="pass")
        from operaciones.models import OperacionEtiqueta
        etiqueta = OperacionEtiqueta.objects.create(nombre="Urgente")
        
        self.operacion.titulo = "Laptop"
        self.operacion.fecha_vencimiento = "2026-05-22"
        self.operacion.prioridad = "ALTA"
        self.operacion.save()
        self.operacion.asignados.add(usuario_2)
        self.operacion.etiquetas.add(etiqueta)

        # Hacemos un POST mandando valores vacíos/None
        post_data = {
            "titulo": "",
            "fecha_vencimiento": "",
            "prioridad": "MEDIA",  # Queremos cambiar solo la prioridad
            "asignados": [],
            "etiquetas": [],
        }
        
        resp = self.client.post(
            reverse("operaciones:editar_operacion", args=[self.operacion.id]),
            post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        
        self.operacion.refresh_from_db()
        # Verificar que la prioridad cambió a MEDIA
        self.assertEqual(self.operacion.prioridad, "MEDIA")
        # Verificar que el título y fecha de vencimiento se mantuvieron intactos
        self.assertEqual(self.operacion.titulo, "Laptop")
        self.assertEqual(str(self.operacion.fecha_vencimiento), "2026-05-22")
        # Verificar que los asignados y etiquetas se mantuvieron
        self.assertIn(usuario_2, self.operacion.asignados.all())
        self.assertIn(etiqueta, self.operacion.etiquetas.all())
