from __future__ import annotations

from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from cuenta_gastos.models import CuentaGastos
from garantias.models import Garantia
from operaciones.models import Operacion
from panel_cotizaciones.models import PanelCotizacion
from solicitudes.models import Cotizacion, Referencia, Solicitud
from solicitudes_app.trash import enviar_a_papelera


class PapeleraViewsAndCommandTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="papelera_admin",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.usuario = user_model.objects.create_user(
            username="papelera_user",
            password="pass123",
        )
        self.client = Client()
        self.client.force_login(self.admin)

    def test_panel_lista_elementos_eliminados_y_permite_filtrar(self):
        operacion = Operacion.objects.create(
            titulo="Operación papelera",
            creado_por=self.usuario,
        )
        garantia = Garantia.objects.create(
            titulo="Garantía papelera",
            creado_por=self.admin,
        )
        enviar_a_papelera(operacion, self.admin)
        enviar_a_papelera(garantia, self.admin)

        response = self.client.get(reverse("papelera"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Operación papelera")
        self.assertContains(response, "Garantía papelera")
        self.assertEqual(response.context["papelera_total"], 2)

        filtrado = self.client.get(reverse("papelera"), {"tipo": "garantia"})
        self.assertEqual(filtrado.status_code, 200)
        self.assertContains(filtrado, "Garantía papelera")
        self.assertNotContains(filtrado, "Operación papelera")

    def test_restaurar_elemento_lo_reactiva(self):
        operacion = Operacion.objects.create(
            titulo="Operación restaurable",
            creado_por=self.usuario,
        )
        enviar_a_papelera(operacion, self.admin)

        response = self.client.post(
            reverse("papelera_restaurar", args=["operacion", operacion.pk])
        )

        self.assertEqual(response.status_code, 200)
        operacion.refresh_from_db()
        self.assertIsNone(operacion.eliminado_en)
        self.assertIsNone(operacion.eliminado_por)

    def test_purgar_papelera_elimina_solo_elementos_fuera_de_retencion(self):
        antigua = Operacion.objects.create(
            titulo="Operación antigua",
            creado_por=self.usuario,
        )
        reciente = CuentaGastos.objects.create(
            titulo="Cuenta reciente",
            creado_por=self.usuario,
        )
        cotizacion = PanelCotizacion.objects.create(
            titulo="Cotización antigua",
            creado_por=self.usuario,
        )
        enviar_a_papelera(antigua, self.admin)
        enviar_a_papelera(reciente, self.admin)
        enviar_a_papelera(cotizacion, self.admin)

        Operacion.objects.filter(pk=antigua.pk).update(
            eliminado_en=timezone.now() - timedelta(days=45)
        )
        PanelCotizacion.objects.filter(pk=cotizacion.pk).update(
            eliminado_en=timezone.now() - timedelta(days=31)
        )
        CuentaGastos.objects.filter(pk=reciente.pk).update(
            eliminado_en=timezone.now() - timedelta(days=5)
        )

        stdout = StringIO()
        call_command("purgar_papelera", stdout=stdout)

        self.assertFalse(Operacion.objects.filter(pk=antigua.pk).exists())
        self.assertFalse(PanelCotizacion.objects.filter(pk=cotizacion.pk).exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=reciente.pk).exists())
        self.assertIn("Purga completada: 2 elemento(s) eliminado(s).", stdout.getvalue())


class SolicitudesIntegracionPapeleraTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.admin = user_model.objects.create_user(
            username="sol_admin",
            password="pass123",
            is_superuser=True,
            is_staff=True,
        )
        self.ejecutivo = user_model.objects.create_user(
            username="sol_ejecutivo",
            password="pass123",
            first_name="Eva",
        )
        self.client.force_login(self.admin)

    def test_papelera_admite_solicitud_cotizacion_ref_y_referencia(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26999",
            cliente="CLIENTE PAPELERA",
            fecha_recepcion=timezone.localdate(),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            aerea=True,
            estado_aereo="Pendiente",
        )
        cotizacion = Cotizacion.objects.create(
            anio=2026,
            consecutivo="C26999",
            cliente="PROSPECTO PAPELERA",
            fecha_solicitud=timezone.localdate(),
            tipo="Servicio",
            ejecutivo=self.ejecutivo,
        )
        referencia = Referencia.objects.create(
            referencia="BC26999",
            consecutivo=999,
            cliente="CLIENTE REFERENCIA",
            servicio="importacion",
            ejecutivo=self.ejecutivo,
            fecha=timezone.localdate(),
        )
        enviar_a_papelera(solicitud, self.admin)
        enviar_a_papelera(cotizacion, self.admin)
        enviar_a_papelera(referencia, self.admin)

        response = self.client.get(reverse("papelera"))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solicitudes")
        self.assertContains(response, "Cotizaciones-ref")
        self.assertContains(response, "Referencias")
        self.assertContains(response, "SG26999")
        self.assertContains(response, "C26999")
        self.assertContains(response, "BC26999")

    def test_ejecutivo_puede_abrir_papelera_y_restaurar_su_solicitud(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26077",
            cliente="CLIENTE EVA",
            fecha_recepcion=timezone.localdate(),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            aerea=True,
            estado_aereo="Pendiente",
        )
        enviar_a_papelera(solicitud, self.admin)
        self.client.force_login(self.ejecutivo)

        panel = self.client.get(reverse("papelera"))
        restore = self.client.post(reverse("papelera_restaurar", args=["solicitud", solicitud.pk]))

        self.assertEqual(panel.status_code, 200)
        self.assertEqual(restore.status_code, 200)
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.eliminado_en)

    def test_ejecutivo_no_puede_eliminar_definitivamente(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26078",
            cliente="CLIENTE SEGURIDAD",
            fecha_recepcion=timezone.localdate(),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            aerea=True,
            estado_aereo="Pendiente",
        )
        enviar_a_papelera(solicitud, self.admin)
        self.client.force_login(self.ejecutivo)

        response = self.client.post(
            reverse("papelera_eliminar_definitivamente", args=["solicitud", solicitud.pk])
        )

        self.assertEqual(response.status_code, 403)
        self.assertTrue(Solicitud.objects.filter(pk=solicitud.pk).exists())

    def test_borrado_logico_y_boton_directo_en_listados_clasicos(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26079",
            cliente="CLIENTE LISTA",
            fecha_recepcion=timezone.localdate(),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            aerea=True,
            estado_aereo="Pendiente",
        )
        cotizacion = Cotizacion.objects.create(
            anio=2026,
            consecutivo="C26079",
            cliente="PROSPECTO LISTA",
            fecha_solicitud=timezone.localdate(),
            tipo="Servicio",
            ejecutivo=self.ejecutivo,
        )
        referencia = Referencia.objects.create(
            referencia="BC26079",
            consecutivo=79,
            cliente="CLIENTE REF LISTA",
            servicio="importacion",
            ejecutivo=self.ejecutivo,
            fecha=timezone.localdate(),
        )

        solicitudes_html = self.client.get(reverse("lista_solicitudes"), {"anio": 2026}).content.decode("utf-8")
        cotizaciones_html = self.client.get(reverse("lista_cotizaciones"), {"anio": 2026}).content.decode("utf-8")
        referencias_html = self.client.get(reverse("lista_referencias")).content.decode("utf-8")

        self.assertIn(
            f'data-trash-endpoint="{reverse("eliminar_solicitud", args=[solicitud.pk])}',
            solicitudes_html,
        )
        self.assertIn("?next=/solicitudes/%3Fanio%3D2026", solicitudes_html)
        self.assertIn(
            f'data-trash-endpoint="{reverse("eliminar_cotizacion", args=[cotizacion.pk])}',
            cotizaciones_html,
        )
        self.assertIn("?next=/cotizaciones/%3Fanio%3D2026", cotizaciones_html)
        self.assertIn(
            f'data-trash-endpoint="{reverse("eliminar_referencia", args=[referencia.pk])}',
            referencias_html,
        )
        self.assertIn("?next=/referencias/", referencias_html)

        self.client.post(reverse("eliminar_solicitud", args=[solicitud.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.post(reverse("eliminar_cotizacion", args=[cotizacion.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.client.post(reverse("eliminar_referencia", args=[referencia.pk]), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        solicitud.refresh_from_db()
        cotizacion.refresh_from_db()
        referencia.refresh_from_db()
        self.assertIsNotNone(solicitud.eliminado_en)
        self.assertIsNotNone(cotizacion.eliminado_en)
        self.assertIsNotNone(referencia.eliminado_en)
