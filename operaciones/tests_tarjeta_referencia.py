from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from solicitudes.models import Referencia

from .models import Operacion, OperacionColumna


class DatosReferenciaTarjetaOperacionTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="tarjeta-referencia", password="pass"
        )
        self.client.force_login(self.usuario)
        columna, _ = OperacionColumna.objects.get_or_create(
            codigo=Operacion.Estado.PENDIENTE,
            defaults={"nombre": "Pendientes", "orden": 1, "activa": True},
        )
        self.columna = columna

    def _crear_operacion(self, *, referencia=None):
        operacion = Operacion.objects.create(
            titulo="Operación de referencia",
            creado_por=self.usuario,
            columna=self.columna,
            estado=self.columna.codigo,
            referencia_origen=referencia,
        )
        operacion.asignados.add(self.usuario)
        return operacion

    def _tablero(self):
        return self.client.get(reverse("operaciones:panel_operaciones"))

    def test_tarjeta_muestra_agencia_y_medio_de_referencia_origen(self):
        referencia = Referencia.objects.create(
            referencia="REF-TARJETA-1",
            consecutivo=901,
            agencia_aduanal="Agencia del Puerto",
            medio_operacion="maritima",
        )
        self._crear_operacion(referencia=referencia)

        response = self._tablero()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Agencia del Puerto")
        self.assertContains(response, "operaciones-card__origin-detail--agency")
        self.assertContains(response, "operaciones-card__origin-indicator")
        self.assertContains(response, "🚢")
        self.assertContains(response, "Marítima")

    def test_tarjeta_usa_emoji_correcto_para_cada_medio_reconocido(self):
        medios = (("maritima", "🚢", "Marítima"), ("aerea", "✈️", "Aérea"), ("terrestre", "🚛", "Terrestre"))
        for indice, (medio, emoji, etiqueta) in enumerate(medios, start=10):
            with self.subTest(medio=medio):
                referencia = Referencia.objects.create(
                    referencia=f"REF-TARJETA-{indice}",
                    consecutivo=indice,
                    medio_operacion=medio,
                )
                self._crear_operacion(referencia=referencia)

                response = self._tablero()

                self.assertContains(response, emoji)
                self.assertContains(response, etiqueta)
                self.assertContains(response, 'class="operaciones-card__origin-indicator"')

    def test_tarjeta_muestra_solo_datos_disponibles_de_referencia(self):
        referencia = Referencia.objects.create(
            referencia="REF-TARJETA-2",
            consecutivo=902,
            agencia_aduanal="Agencia Parcial",
        )
        self._crear_operacion(referencia=referencia)

        response = self._tablero()

        self.assertContains(response, "Agencia Parcial")
        self.assertContains(response, "operaciones-card__origin-detail--agency")
        self.assertNotContains(response, "operaciones-card__origin-indicator")

    def test_tarjeta_sin_referencia_no_falla_ni_muestra_datos_de_referencia(self):
        self._crear_operacion()

        response = self._tablero()

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "operaciones-card__origin-detail")
        self.assertNotContains(response, "operaciones-card__origin-indicator")
