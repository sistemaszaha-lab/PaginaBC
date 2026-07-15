from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Garantia


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
        self.asignado = User.objects.create_user(username="asignado_garantias", password="pass123", first_name="Asignado")
        self.otro = User.objects.create_user(username="otro_garantias", password="pass123", first_name="Otro")

        self.garantia = Garantia.objects.create(titulo="Garantia Visible", creado_por=self.admin)
        self.garantia.asignados.add(self.asignado, self.asignado)

        self.client.force_login(self.admin)

    def test_panel_filtra_por_usuario(self):
        response = self.client.get(reverse("garantias:panel_garantias"), {"usuario": str(self.asignado.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Garantia Visible")

    def test_panel_no_duplica_por_many_to_many(self):
        response = self.client.get(reverse("garantias:panel_garantias"), {"usuario": str(self.asignado.id)})
        self.assertEqual(response.content.decode("utf-8").count("Garantia Visible"), 1)

    def test_panel_filtra_sin_resultados(self):
        response = self.client.get(reverse("garantias:panel_garantias"), {"usuario": str(self.otro.id)})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Sin garantias.")
