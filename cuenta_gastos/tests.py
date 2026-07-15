from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from clientes.models import Cliente
from .models import CuentaGastos, CuentaGastosArchivo, CuentaGastosEnlace, CuentaGastosEtiqueta, CuentaGastosOpcion


@override_settings(
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

    def test_panel_filtra_por_usuario(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"), {"usuario": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Laptop HP")

    def test_detalle_cuenta_gastos_view(self):
        resp = self.client.get(reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 200)

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
