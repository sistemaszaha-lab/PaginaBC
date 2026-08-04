from __future__ import annotations

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from solicitudes_app.trash import enviar_a_papelera

from .models import PanelCotizacion, PanelCotizacionColumna


class PanelCotizacionesPapeleraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.usuario = user_model.objects.create_user(
            username="panel_papelera",
            password="pass123",
        )
        self.client.force_login(self.usuario)

    def test_eliminar_cotizacion_la_envia_a_papelera(self):
        cotizacion = PanelCotizacion.objects.create(
            titulo="Cotización eliminable",
            creado_por=self.usuario,
        )

        response = self.client.post(
            reverse("panel_cotizaciones:eliminar", args=[cotizacion.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        cotizacion.refresh_from_db()
        self.assertIsNotNone(cotizacion.eliminado_en)
        self.assertEqual(cotizacion.eliminado_por, self.usuario)

    def test_eliminar_columna_ignora_tarjetas_en_papelera(self):
        origen = PanelCotizacionColumna.objects.create(
            nombre="Temporal papelera",
            codigo="TEMP_PAPELERA_COT",
            orden=100,
            activa=True,
            creada_por=self.usuario,
        )
        cotizacion = PanelCotizacion.objects.create(
            titulo="Cotización oculta",
            columna=origen,
            estado=origen.codigo,
            creado_por=self.usuario,
        )
        enviar_a_papelera(cotizacion, self.usuario)

        response = self.client.post(
            reverse("panel_cotizaciones:columna_eliminar", args=[origen.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
