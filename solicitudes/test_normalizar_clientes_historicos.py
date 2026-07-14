from datetime import date
from io import StringIO

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase

from clientes.models import Cliente
from panel_cotizaciones.models import PanelCotizacion
from solicitudes.models import Cotizacion, Referencia, Solicitud


class NormalizarClientesHistoricosCommandTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="hist_user", password="hist123", first_name="Hist"
        )

    def _crear_datos_historicos(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26801",
            cliente="LIMPIO",
            fecha_recepcion=date(2026, 3, 1),
            tipo="Operacion",
            ejecutivo=self.user,
            aerea=True,
            estado_aereo="Pendiente",
        )
        Solicitud.objects.filter(pk=solicitud.pk).update(cliente=" empresa   vargas ")

        cotizacion = Cotizacion.objects.create(
            anio=2026,
            consecutivo="C26801",
            cliente="empresa vargas",
            fecha_solicitud=date(2026, 3, 2),
            tipo="Importación aérea",
            ejecutivo=self.user,
            tiempo_entrega="",
            aerea="Aérea",
            maritima="",
            terrestre="",
        )
        Cotizacion.objects.filter(pk=cotizacion.pk).update(
            cliente=" méxico  & cia. - log / sur "
        )

        referencia = Referencia.objects.create(
            referencia="BC26801",
            consecutivo=801,
            ejecutivo=self.user,
            cliente="LIMPIO",
            servicio="importacion",
            agencia_aduanal="Agencia",
            fecha=date(2026, 3, 3),
        )
        Referencia.objects.filter(pk=referencia.pk).update(cliente=" aldo ")

        referencia_2 = Referencia.objects.create(
            referencia="BC26802",
            consecutivo=802,
            ejecutivo=self.user,
            cliente="LIMPIO",
            servicio="importacion",
            agencia_aduanal="Agencia",
            fecha=date(2026, 3, 4),
        )
        Referencia.objects.filter(pk=referencia_2.pk).update(cliente="Aldo")

        panel = PanelCotizacion.objects.create(
            titulo="Panel",
            descripcion="Desc",
            cliente="LIMPIO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        PanelCotizacion.objects.filter(pk=panel.pk).update(
            cliente=" / sur  logistics & co. "
        )

        return {
            "solicitud": solicitud.pk,
            "cotizacion": cotizacion.pk,
            "referencia": referencia.pk,
            "referencia_2": referencia_2.pk,
            "panel": panel.pk,
        }

    def test_dry_run_no_modifica_registros(self):
        ids = self._crear_datos_historicos()
        salida = StringIO()

        call_command("normalizar_clientes_historicos", "--dry-run", stdout=salida)

        texto = salida.getvalue()
        self.assertIn("Solicitud ID", texto)
        self.assertIn("Cotizacion ID", texto)
        self.assertIn("Referencia ID", texto)
        self.assertIn("PanelCotizacion ID", texto)

        self.assertEqual(
            Solicitud.objects.get(pk=ids["solicitud"]).cliente, " empresa   vargas "
        )
        self.assertEqual(
            Cotizacion.objects.get(pk=ids["cotizacion"]).cliente,
            " méxico  & cia. - log / sur ",
        )
        self.assertEqual(
            Referencia.objects.get(pk=ids["referencia"]).cliente, " aldo "
        )
        self.assertEqual(
            PanelCotizacion.objects.get(pk=ids["panel"]).cliente,
            " / sur  logistics & co. ",
        )

    def test_ejecucion_real_normaliza_solicitud(self):
        ids = self._crear_datos_historicos()

        call_command("normalizar_clientes_historicos", "--modelo", "solicitud")

        solicitud = Solicitud.objects.get(pk=ids["solicitud"])
        self.assertEqual(solicitud.cliente, "EMPRESA VARGAS")
        self.assertEqual(solicitud.tipo, "Operacion")

    def test_ejecucion_real_normaliza_cotizacion(self):
        ids = self._crear_datos_historicos()
        clientes_antes = Cliente.objects.count()

        call_command("normalizar_clientes_historicos", "--modelo", "cotizacion")

        cotizacion = Cotizacion.objects.get(pk=ids["cotizacion"])
        self.assertEqual(cotizacion.cliente, "MÉXICO & CIA. - LOG / SUR")
        self.assertEqual(cotizacion.tipo, "Importación aérea")
        self.assertEqual(Cliente.objects.count(), clientes_antes)

    def test_ejecucion_real_normaliza_referencia(self):
        ids = self._crear_datos_historicos()

        call_command("normalizar_clientes_historicos", "--modelo", "referencia")

        referencia = Referencia.objects.get(pk=ids["referencia"])
        self.assertEqual(referencia.cliente, "ALDO")
        self.assertEqual(referencia.agencia_aduanal, "Agencia")

    def test_ejecucion_real_normaliza_panel_cotizacion(self):
        ids = self._crear_datos_historicos()

        call_command("normalizar_clientes_historicos", "--modelo", "panel_cotizacion")

        panel = PanelCotizacion.objects.get(pk=ids["panel"])
        self.assertEqual(panel.cliente, "/ SUR LOGISTICS & CO.")
        self.assertEqual(panel.titulo, "Panel")

    def test_filtro_modelo_modifica_unicamente_el_indicado(self):
        ids = self._crear_datos_historicos()

        call_command("normalizar_clientes_historicos", "--modelo", "solicitud")

        self.assertEqual(
            Solicitud.objects.get(pk=ids["solicitud"]).cliente, "EMPRESA VARGAS"
        )
        self.assertEqual(
            Cotizacion.objects.get(pk=ids["cotizacion"]).cliente,
            " méxico  & cia. - log / sur ",
        )
        self.assertEqual(
            Referencia.objects.get(pk=ids["referencia"]).cliente, " aldo "
        )
        self.assertEqual(
            PanelCotizacion.objects.get(pk=ids["panel"]).cliente,
            " / sur  logistics & co. ",
        )

    def test_resumen_identifica_variantes_historicas(self):
        self._crear_datos_historicos()
        salida = StringIO()

        call_command("normalizar_clientes_historicos", "--dry-run", stdout=salida)

        texto = salida.getvalue()
        self.assertIn("Valor normalizado: ALDO", texto)
        self.assertIn("Variantes encontradas:", texto)
        self.assertIn("-  aldo ", texto)
        self.assertIn("- Aldo", texto)
