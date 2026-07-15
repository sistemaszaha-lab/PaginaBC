from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from .models import Operacion, OperacionArchivo, OperacionEnlace


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
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": ""})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_all_no_explota(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": "all"})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_ids_filtra(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Op 1")


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

    def test_usuario_sin_permiso_no_puede_eliminar_archivo(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_archivo", password="pass")
        archivo = OperacionArchivo.objects.create(
            operacion=self.operacion,
            archivo=SimpleUploadedFile("evidencia.txt", b"hola"),
            subido_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("operaciones:eliminar_archivo", args=[self.operacion.id]),
            {"archivo_id": archivo.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(OperacionArchivo.objects.filter(id=archivo.id).exists())

    def test_usuario_sin_permiso_no_puede_eliminar_enlace(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_enlace", password="pass")
        enlace = OperacionEnlace.objects.create(
            operacion=self.operacion,
            titulo="Documento",
            url="https://example.com/doc",
            creado_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("operaciones:eliminar_enlace", args=[self.operacion.id]),
            {"enlace_id": enlace.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(OperacionEnlace.objects.filter(id=enlace.id).exists())
