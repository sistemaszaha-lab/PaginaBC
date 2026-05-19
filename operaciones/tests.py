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
