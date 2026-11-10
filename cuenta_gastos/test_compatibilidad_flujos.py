"""Regresiones de los conflictos reproducidos contra dd11dcf."""
from io import StringIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from operaciones.models import Operacion, OperacionColumna
from garantias.models import Garantia, GarantiaColumna
from garantias.services import enviar_garantia_a_cuenta_gastos
from solicitudes_app.trash import enviar_a_papelera, restaurar_desde_papelera
from .models import CuentaGastos, CuentaGastosColumna
from .services import (
    crear_copia_flete_desde_operacion,
    crear_copia_vobo_angie_si_corresponde,
    crear_cuenta_gastos_desde_operacion_si_corresponde,
)


class AislamientoFlujosTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_superuser(username='compatibilidad', password='pass')
        self.client.force_login(self.user)
        self.vobo = CuentaGastosColumna.objects.get(codigo='VOBO_ANGIE')
        self.geo = CuentaGastosColumna.objects.get(codigo='SOLICITUDES_GEO_1')

    def pareja_historica(self):
        op = Operacion.objects.create(creado_por=self.user, estado='SOLICITUD_CUENTA_GASTOS')
        cuenta, _ = crear_cuenta_gastos_desde_operacion_si_corresponde(op, creado_por=self.user)
        cuenta.columna = self.vobo
        cuenta.save()
        return op, cuenta

    def test_reutilizar_espejo_historico_no_dispara_geo_ni_modifica_datos(self):
        op, cuenta = self.pareja_historica()
        antes = CuentaGastos.objects.values().get(pk=cuenta.pk)
        with patch('cuenta_gastos.services.crear_copia_vobo_angie_si_corresponde') as geo:
            resultado, creada = crear_cuenta_gastos_desde_operacion_si_corresponde(op, creado_por=self.user)
        geo.assert_not_called()
        self.assertFalse(creada)
        self.assertEqual(resultado.pk, cuenta.pk)
        self.assertEqual(CuentaGastos.objects.values().get(pk=cuenta.pk), antes)
        self.assertEqual(CuentaGastos.objects.count(), 1)

    def test_endpoint_anterior_responde_200_aunque_geo_este_inactivo(self):
        op, cuenta = self.pareja_historica()
        self.geo.activa = False
        self.geo.save()
        response = self.client.post(reverse('operaciones:mover_operacion', args=[op.pk]),
                                    {'estado': 'SOLICITUD_CUENTA_GASTOS'})
        self.assertEqual(response.status_code, 200, response.content)
        self.assertEqual(CuentaGastos.objects.count(), 1)
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.columna_id, self.vobo.pk)

    def test_comando_simulacion_y_ejecucion_solo_regularizan_espejos_historicos(self):
        _, existente = self.pareja_historica()
        nueva = Operacion.objects.create(creado_por=self.user, estado='SOLICITUD_CUENTA_GASTOS')
        self.geo.activa = False
        self.geo.save()
        antes = list(CuentaGastos.objects.values())
        simulacion = StringIO()
        call_command('duplicar_tarjetas_pendientes', dry_run=True, stdout=simulacion)
        self.assertEqual(list(CuentaGastos.objects.values()), antes)
        self.assertIn('[SKIP]', simulacion.getvalue())
        self.assertIn('[NEW]', simulacion.getvalue())
        real = StringIO()
        errores = StringIO()
        call_command('duplicar_tarjetas_pendientes', stdout=real, stderr=errores)
        self.assertEqual(errores.getvalue(), '')
        self.assertIn('Creadas:      1', real.getvalue())
        self.assertIn('Ya existían:  1', real.getvalue())
        self.assertEqual(CuentaGastos.objects.count(), 2)
        self.assertEqual(CuentaGastos.objects.get(operacion_origen=nueva).estado, 'SOLICITUD_CUENTA_GASTOS')
        self.assertFalse(CuentaGastos.objects.filter(vobo_angie_origen__isnull=False).exists())
        enviar_a_papelera(existente, self.user)
        otra = StringIO()
        call_command('duplicar_tarjetas_pendientes', stdout=otra)
        self.assertIn('Creadas:      0', otra.getvalue())
        self.assertEqual(CuentaGastos.objects.count(), 2)

    def test_reutilizar_copia_flete_movida_a_vobo_no_dispara_geo(self):
        op = Operacion.objects.create(creado_por=self.user, estado='FACTURA_FLETES_1')
        cuenta, _ = crear_copia_flete_desde_operacion(op, creado_por=self.user)
        cuenta.columna = self.vobo
        cuenta.save()
        self.geo.activa = False
        self.geo.save()
        resultado, creada = crear_copia_flete_desde_operacion(op, creado_por=self.user)
        self.assertFalse(creada)
        self.assertEqual(resultado.pk, cuenta.pk)
        self.assertEqual(CuentaGastos.objects.count(), 1)

    def test_repetir_misma_columna_no_activa_historicos_pero_reentrada_si(self):
        _, cuenta = self.pareja_historica()
        url = reverse('cuenta_gastos:mover_cuenta_gastos', args=[cuenta.pk])
        self.assertEqual(self.client.post(url, {'estado': 'VOBO_ANGIE'}).status_code, 200)
        self.assertEqual(CuentaGastos.objects.count(), 1)
        self.assertEqual(self.client.post(url, {'estado': 'SOLICITUD_PAGO'}).status_code, 200)
        self.assertEqual(self.client.post(url, {'estado': 'VOBO_ANGIE'}).status_code, 200)
        copia = CuentaGastos.objects.get(vobo_angie_origen=cuenta)
        self.assertEqual(copia.columna_id, self.geo.pk)
        self.assertEqual(self.client.post(url, {'estado': 'VOBO_ANGIE'}).status_code, 200)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=cuenta).count(), 1)

    def test_nuevos_codigos_no_activan_flujos_anteriores(self):
        op = Operacion.objects.create(creado_por=self.user)
        response = self.client.post(reverse('operaciones:mover_operacion', args=[op.pk]),
                                    {'estado': 'FACTURA_FLETES_1'})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(CuentaGastos.objects.filter(operacion_origen=op).exists())
        self.assertFalse(Garantia.objects.exists())
        cuenta = CuentaGastos.objects.get(operacion_flete_origen=op)
        self.assertEqual(self.client.post(reverse('cuenta_gastos:mover_cuenta_gastos', args=[cuenta.pk]),
                                         {'estado': self.geo.codigo}).status_code, 200)
        self.assertEqual(CuentaGastos.objects.count(), 1)


class RenombradoGarantiasTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='renombrado')

    def test_nuevas_columnas_renombradas_no_desvian_ni_bloquean_destino_historico(self):
        destino = CuentaGastosColumna.objects.get(codigo='DEVOLUCION_A_GARANTIAS')
        CuentaGastosColumna.objects.filter(codigo__in=['FACTURA_FLETES_1', 'SOLICITUDES_GEO_1']).update(
            nombre='Devolución a garantías')
        # Conserva también el fallback histórico para instalaciones con otro código.
        for codigo in ('DEVOLUCION_A_GARANTIAS', 'CODIGO_PRODUCCION'):
            with self.subTest(codigo=codigo):
                destino.codigo = codigo
                destino.save()
                garantia = Garantia.objects.create(creado_por=self.user, estado='DEVOLUCION_CLIENTE')
                cuenta, creada = enviar_garantia_a_cuenta_gastos(garantia, creado_por=self.user)
                self.assertTrue(creada)
                self.assertEqual(cuenta.columna_id, destino.pk)
                self.assertIsNone(cuenta.vobo_angie_origen_id)
                self.assertIsNone(cuenta.operacion_flete_origen_id)

    def test_sin_destino_historico_no_adopta_nueva_columna_homonima(self):
        CuentaGastosColumna.objects.filter(codigo='DEVOLUCION_A_GARANTIAS').delete()
        CuentaGastosColumna.objects.filter(codigo='FACTURA_FLETES_1').update(nombre='Devolución a garantías')
        garantia = Garantia.objects.create(creado_por=self.user, estado='DEVOLUCION_CLIENTE')
        with self.assertRaisesRegex(ValueError, 'No existe'):
            enviar_garantia_a_cuenta_gastos(garantia, creado_por=self.user)
        self.assertFalse(CuentaGastos.objects.exists())


class RestauracionSinTransferenciasTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username='restauracion')

    def test_restaurar_en_origen_activo_no_crea_copias_historicas(self):
        for modelo, codigo in ((Operacion, 'FACTURA_FLETES_1'), (CuentaGastos, 'VOBO_ANGIE')):
            with self.subTest(modelo=modelo):
                obj = modelo.objects.create(creado_por=self.user, estado=codigo)
                enviar_a_papelera(obj, self.user)
                total = CuentaGastos.objects.count()
                restaurar_desde_papelera(obj, self.user)
                self.assertEqual(CuentaGastos.objects.count(), total)
                obj.refresh_from_db()
                self.assertIsNone(obj.eliminado_en)
                self.assertEqual(obj.estado, codigo)

    def test_fallback_a_origen_automatizado_no_dispara_ni_depende_del_destino(self):
        for modelo, columnas, codigo in ((Operacion, OperacionColumna, 'FACTURA_FLETES_1'),
                                         (CuentaGastos, CuentaGastosColumna, 'VOBO_ANGIE')):
            with self.subTest(modelo=modelo):
                origen = columnas.objects.get(codigo=codigo)
                temporal = columnas.objects.create(codigo='TEMP_RESTORE', nombre='Temporal')
                obj = modelo.objects.create(creado_por=self.user, columna=temporal, estado=temporal.codigo)
                enviar_a_papelera(obj, self.user)
                columnas.objects.exclude(pk=origen.pk).update(activa=False)
                CuentaGastosColumna.objects.filter(codigo='SOLICITUDES_GEO_1').update(activa=False)
                obj.refresh_from_db()
                total = CuentaGastos.objects.count()
                restaurar_desde_papelera(obj, self.user)
                obj.refresh_from_db()
                self.assertEqual(obj.columna_id, origen.pk)
                self.assertIsNone(obj.eliminado_en)
                self.assertEqual(CuentaGastos.objects.count(), total)
                columnas.objects.update(activa=True)

    def test_restaurar_con_copia_existente_conserva_su_identidad_y_ediciones(self):
        origen = CuentaGastos.objects.create(creado_por=self.user, estado='VOBO_ANGIE')
        copia, _ = crear_copia_vobo_angie_si_corresponde(origen, creado_por=self.user)
        copia.titulo = 'Edición independiente'
        copia.save()
        for obj in (origen, copia):
            enviar_a_papelera(obj, self.user)
            restaurar_desde_papelera(obj, self.user)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=origen).count(), 1)
        copia.refresh_from_db()
        self.assertEqual(copia.titulo, 'Edición independiente')

    def test_restaurar_garantia_no_cambia_la_regla_historica(self):
        garantia = Garantia.objects.create(creado_por=self.user, estado='DEVOLUCION_CLIENTE')
        enviar_a_papelera(garantia, self.user)
        restaurar_desde_papelera(garantia, self.user)
        self.assertFalse(CuentaGastos.objects.filter(garantia_origen=garantia).exists())
