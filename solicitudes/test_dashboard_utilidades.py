import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente


class InicioDashboardUtilidadesTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="dashboard", password="pass")
        self.client.force_login(self.usuario)

    def test_clientes_con_mas_utilidades_ordenados_por_utilidad_desc_y_top_5(self):
        Cliente.objects.create(nombre="CLIENTE A", ingresos=1000, gastos=800)
        Cliente.objects.create(nombre="CLIENTE B", ingresos=5000, gastos=1000)
        Cliente.objects.create(nombre="CLIENTE C", ingresos=3000, gastos=1000)
        Cliente.objects.create(nombre="CLIENTE D", ingresos=100, gastos=50)
        Cliente.objects.create(nombre="CLIENTE E", ingresos=90, gastos=50)
        Cliente.objects.create(nombre="CLIENTE F", ingresos=80, gastos=50)

        response = self.client.get(reverse("inicio"))

        self.assertEqual(response.status_code, 200)
        labels = json.loads(response.context["clientes_utilidades_labels"])
        data = json.loads(response.context["clientes_utilidades_data"])
        self.assertEqual(
            labels,
            ["CLIENTE B", "CLIENTE C", "CLIENTE A", "CLIENTE D", "CLIENTE E"],
        )
        self.assertEqual(data, ["4000", "2000", "200", "50", "40"])
