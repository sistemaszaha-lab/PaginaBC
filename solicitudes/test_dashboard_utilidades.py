import json

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from clientes.models import Cliente
from solicitudes.models import Referencia, MovimientoReferencia


class InicioDashboardUtilidadesTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="dashboard", password="pass")
        self.client.force_login(self.usuario)

    def test_clientes_con_mas_utilidades_ordenados_por_utilidad_desc_y_top_5(self):
        clientes = ["CLIENTE A", "CLIENTE B", "CLIENTE C", "CLIENTE D", "CLIENTE E", "CLIENTE F"]
        utilidades = [(1000, 800), (5000, 1000), (3000, 1000), (100, 50), (90, 50), (80, 50)]
        for nombre, (ingreso, gasto) in zip(clientes, utilidades):
            Cliente.objects.create(nombre=nombre)
            referencia = Referencia.objects.create(referencia=f"REF-{nombre[-1]}", consecutivo=len(nombre), cliente=nombre)
            MovimientoReferencia.objects.create(referencia=referencia, tipo=MovimientoReferencia.INGRESO, monto=ingreso, registrado_por=self.usuario)
            MovimientoReferencia.objects.create(referencia=referencia, tipo=MovimientoReferencia.GASTO, monto=gasto, registrado_por=self.usuario)

        response = self.client.get(reverse("inicio"))

        self.assertEqual(response.status_code, 200)
        labels = json.loads(response.context["clientes_utilidades_labels"])
        data = json.loads(response.context["clientes_utilidades_data"])
        self.assertEqual(
            labels,
            ["CLIENTE B", "CLIENTE C", "CLIENTE A", "CLIENTE D", "CLIENTE E"],
        )
        self.assertEqual(data, ["4000", "2000", "200", "50", "40"])
