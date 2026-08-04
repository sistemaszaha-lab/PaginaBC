from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Operacion, OperacionColumna
from solicitudes_app.trash import enviar_a_papelera


class OperacionesPapeleraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.usuario = user_model.objects.create_user(
            username="operaciones_papelera",
            password="pass123",
        )
        self.client.force_login(self.usuario)

    def test_eliminar_operacion_la_envia_a_papelera(self):
        operacion = Operacion.objects.create(
            titulo="Operación eliminable",
            creado_por=self.usuario,
        )

        response = self.client.post(
            reverse("operaciones:eliminar_operacion", args=[operacion.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        operacion.refresh_from_db()
        self.assertIsNotNone(operacion.eliminado_en)
        self.assertEqual(operacion.eliminado_por, self.usuario)

    def test_eliminar_columna_ignora_operaciones_en_papelera(self):
        origen = OperacionColumna.objects.create(
            nombre="Temporal papelera",
            codigo="TEMP_PAPELERA_OP",
            orden=100,
            creada_por=self.usuario,
        )
        operacion = Operacion.objects.create(
            titulo="Operación oculta",
            columna=origen,
            estado=origen.codigo,
            creado_por=self.usuario,
        )
        enviar_a_papelera(operacion, self.usuario)

        response = self.client.post(
            reverse("operaciones:columna_eliminar", args=[origen.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
