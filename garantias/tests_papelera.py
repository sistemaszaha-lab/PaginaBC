from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from solicitudes_app.trash import enviar_a_papelera

from .models import Garantia, GarantiaColumna


class GarantiasPapeleraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="garantias_papelera_admin",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.client.force_login(self.admin)

    def test_eliminar_garantia_la_envia_a_papelera(self):
        garantia = Garantia.objects.create(
            titulo="Garantía eliminable",
            creado_por=self.admin,
        )

        response = self.client.post(
            reverse("garantias:eliminar_garantia", args=[garantia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        garantia.refresh_from_db()
        self.assertIsNotNone(garantia.eliminado_en)
        self.assertEqual(garantia.eliminado_por, self.admin)

    def test_eliminar_columna_ignora_garantias_en_papelera(self):
        origen = GarantiaColumna.objects.create(
            nombre="Temporal papelera",
            codigo="TEMP_PAPELERA_GAR",
            orden=100,
            creada_por=self.admin,
        )
        garantia = Garantia.objects.create(
            titulo="Garantía oculta",
            columna=origen,
            estado=origen.codigo,
            creado_por=self.admin,
        )
        enviar_a_papelera(garantia, self.admin)

        response = self.client.post(
            reverse("garantias:columna_eliminar", args=[origen.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
