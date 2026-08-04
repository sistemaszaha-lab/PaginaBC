from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from solicitudes_app.trash import enviar_a_papelera

from .models import CuentaGastos, CuentaGastosColumna


class CuentaGastosPapeleraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.usuario = user_model.objects.create_user(
            username="cuenta_papelera",
            password="pass123",
        )
        self.client.force_login(self.usuario)

    def test_eliminar_cuenta_la_envia_a_papelera(self):
        cuenta = CuentaGastos.objects.create(
            titulo="Cuenta eliminable",
            creado_por=self.usuario,
        )

        response = self.client.post(
            reverse("cuenta_gastos:eliminar_cuenta", args=[cuenta.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        cuenta.refresh_from_db()
        self.assertIsNotNone(cuenta.eliminado_en)
        self.assertEqual(cuenta.eliminado_por, self.usuario)

    def test_editor_inline_no_expone_cuentas_en_papelera(self):
        cuenta = CuentaGastos.objects.create(
            titulo="Cuenta oculta",
            creado_por=self.usuario,
        )
        enviar_a_papelera(cuenta, self.usuario)

        response = self.client.get(
            reverse("cuenta_gastos:editor_cuenta_inline", args=[cuenta.pk]),
            {"field": "titulo"},
        )

        self.assertEqual(response.status_code, 404)

    def test_eliminar_columna_ignora_cuentas_en_papelera(self):
        origen = CuentaGastosColumna.objects.create(
            nombre="Temporal papelera",
            codigo="TEMP_PAPELERA_CG",
            orden=100,
            creada_por=self.usuario,
        )
        cuenta = CuentaGastos.objects.create(
            titulo="Cuenta oculta en columna",
            columna=origen,
            estado=origen.codigo,
            creado_por=self.usuario,
        )
        enviar_a_papelera(cuenta, self.usuario)

        response = self.client.post(
            reverse("cuenta_gastos:columna_eliminar", args=[origen.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
