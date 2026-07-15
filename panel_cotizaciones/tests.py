from datetime import date

from django.contrib.auth import get_user_model
from django.test import Client, TestCase
from django.urls import reverse

from clientes.models import Cliente
from .forms import PanelCotizacionCreateForm
from .models import PanelCotizacion


User = get_user_model()


class PanelCotizacionClienteNormalizacionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="panel_user", password="panel123", first_name="Panel")

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
        panel.cliente = " méxico  & cia. - log / sur "
        panel.save()
        panel.refresh_from_db()

        self.assertEqual(panel.cliente, "MÉXICO & CIA. - LOG / SUR")


class PanelCotizacionFiltroTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="panel_admin", password="panel123", first_name="Panel")
        self.asignado = User.objects.create_user(username="panel_asignado", password="panel123", first_name="Asignado")
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

    def test_panel_filtra_por_usuario(self):
        response = self.client.get(reverse("panel_cotizaciones:panel_cotizaciones"), {"usuario": str(self.asignado.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
