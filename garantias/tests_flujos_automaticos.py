from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from cuenta_gastos.models import CuentaGastos, CuentaGastosColumna
from .models import Garantia, GarantiaColumna
from .services import enviar_garantia_a_cuenta_gastos


class TransferenciaAutomaticaTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username='flujo-admin', is_superuser=True)
        self.client.force_login(self.usuario)
        self.origen = GarantiaColumna.objects.get(codigo=Garantia.Estado.SOLICITUD_NAVIERA)
        self.destino = GarantiaColumna.objects.get(codigo=Garantia.Estado.DEVOLUCION_CLIENTE)
        self.garantia = Garantia.objects.create(titulo='Conservar datos', descripcion='Descripción',
            creado_por=self.usuario, estado=self.origen.codigo, columna=self.origen)
        self.garantia.asignados.add(self.usuario)

    def mover(self, alternativa=False, estado=None):
        return self.client.post(
            reverse('garantias:cambiar_estado_garantia', args=[self.garantia.pk]) if alternativa
            else reverse('garantias:actualizar_estado_garantia'),
            {'garantia_id': self.garantia.pk, 'nuevo_estado': estado or self.destino.codigo},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest')

    def test_ambos_endpoints_conservan_origen_datos_y_asignados_sin_duplicar(self):
        for alternativa in (False, True):
            with self.subTest(alternativa=alternativa):
                self.mover(estado=self.origen.codigo)
                with patch('garantias.views.enviar_garantia_a_cuenta_gastos', wraps=enviar_garantia_a_cuenta_gastos) as enviar:
                    self.assertEqual(self.mover(alternativa).status_code, 200)
                    self.assertEqual(self.mover(alternativa).status_code, 200)
                    enviar.assert_called_once()
                self.garantia.refresh_from_db()
                self.assertEqual(self.garantia.estado, self.destino.codigo)
                self.assertEqual(Garantia.objects.count(), 1)
                cuenta = CuentaGastos.objects.get(garantia_origen=self.garantia)
                self.assertEqual(cuenta.columna.codigo, 'DEVOLUCION_A_GARANTIAS')
                self.assertEqual(cuenta.estado, 'DEVOLUCION_A_GARANTIAS')
                self.assertEqual(cuenta.titulo, self.garantia.titulo)
                self.assertEqual(cuenta.descripcion, self.garantia.descripcion)
                self.assertEqual(list(cuenta.asignados.all()), [self.usuario])
                self.assertEqual(CuentaGastos.objects.count(), 1)

    def test_destino_se_resuelve_por_nombre_y_usa_el_codigo_del_catalogo_activo(self):
        destino = CuentaGastosColumna.objects.get(nombre='Devolución a garantías')
        destino.codigo = 'CODIGO_PRODUCCION'
        destino.save(update_fields=['codigo'])

        self.assertEqual(self.mover().status_code, 200)

        cuenta = CuentaGastos.objects.get(garantia_origen=self.garantia)
        self.assertEqual(cuenta.columna_id, destino.pk)
        self.assertEqual(cuenta.estado, 'CODIGO_PRODUCCION')

    def test_destino_ambiguo_no_adivina_y_revierte_el_movimiento(self):
        CuentaGastosColumna.objects.create(
            nombre='Devolución a garantías', codigo='OTRO_CODIGO', orden=999,
        )

        self.assertEqual(self.mover().status_code, 400)

        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.columna_id, self.origen.pk)
        self.assertFalse(CuentaGastos.objects.exists())

    def test_error_despues_de_crear_cuenta_revierte_cuenta_y_movimiento(self):
        def fallar(*args, **kwargs):
            enviar_garantia_a_cuenta_gastos(*args, **kwargs)
            raise RuntimeError('Fallo posterior')
        for alternativa in (False, True):
            with self.subTest(alternativa=alternativa), patch('garantias.views.enviar_garantia_a_cuenta_gastos', side_effect=fallar):
                with self.assertRaisesMessage(RuntimeError, 'Fallo posterior'):
                    self.mover(alternativa)
                self.garantia.refresh_from_db()
                self.assertEqual(self.garantia.estado, self.origen.codigo)
                self.assertEqual(self.garantia.columna_id, self.origen.pk)
                self.assertFalse(CuentaGastos.objects.exists())

    def test_destino_cuenta_inactivo_revierte_movimiento(self):
        CuentaGastosColumna.objects.filter(codigo='DEVOLUCION_A_GARANTIAS').update(activa=False)
        for alternativa in (False, True):
            self.assertEqual(self.mover(alternativa).status_code, 400)
            self.garantia.refresh_from_db()
            self.assertEqual(self.garantia.columna_id, self.origen.pk)
            self.assertFalse(CuentaGastos.objects.exists())

    def test_otras_columnas_no_transfieren(self):
        self.assertEqual(self.mover(estado=Garantia.Estado.PAGO_NAVIERA_ZAHA).status_code, 200)
        self.assertFalse(CuentaGastos.objects.exists())

    def test_reubicacion_transfiere_y_error_revierte_toda_la_eliminacion(self):
        temporal = GarantiaColumna.objects.create(codigo='TEMPORAL_AUTO', nombre='Temporal')
        Garantia.objects.filter(pk=self.garantia.pk).update(columna=temporal, estado=temporal.codigo)
        otra = Garantia.objects.create(titulo='Segunda', creado_por=self.usuario, columna=temporal, estado=temporal.codigo)
        url = reverse('garantias:columna_eliminar', args=[temporal.pk])
        llamadas = []
        def fallar_segunda(*args, **kwargs):
            resultado = enviar_garantia_a_cuenta_gastos(*args, **kwargs)
            llamadas.append(1)
            if len(llamadas) == 2:
                raise ValueError('Error segunda tarjeta')
            return resultado
        with patch('garantias.views.enviar_garantia_a_cuenta_gastos', side_effect=fallar_segunda):
            response = self.client.post(url, {'columna_destino_id': self.destino.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 400)
        temporal.refresh_from_db()
        self.assertTrue(temporal.activa)
        self.assertEqual(Garantia.objects.filter(columna=temporal).count(), 2)
        self.assertFalse(CuentaGastos.objects.exists())
        response = self.client.post(url, {'columna_destino_id': self.destino.pk}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Garantia.objects.filter(columna=self.destino).count(), 2)
        self.assertEqual(CuentaGastos.objects.filter(garantia_origen__in=[self.garantia, otra]).count(), 2)

    def test_movimiento_requiere_post_autenticacion_y_csrf(self):
        from django.test import Client
        url = reverse('garantias:cambiar_estado_garantia', args=[self.garantia.pk])
        self.assertEqual(self.client.get(url).status_code, 405)
        self.client.logout()
        self.assertEqual(self.client.post(url, {'estado': self.destino.codigo}).status_code, 302)
        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.usuario)
        self.assertEqual(csrf_client.post(url, {'estado': self.destino.codigo}).status_code, 403)
        self.assertFalse(CuentaGastos.objects.exists())

    def test_tarjeta_ya_no_ofrece_boton_manual_y_backend_sigue_disponible(self):
        self.mover()
        from .views import _render_card_html
        from django.test import RequestFactory
        request = RequestFactory().get('/')
        request.user = self.usuario
        html = _render_card_html(request, self.garantia)
        self.assertNotIn('data-garantia-send-cuenta="1"', html)
        self.assertEqual(self.client.post(reverse('garantias:enviar_garantia_a_cuenta', args=[self.garantia.pk])).status_code, 200)
        self.assertEqual(CuentaGastos.objects.count(), 1)

    def test_reentrada_conserva_cuenta_existente_y_sus_asignados_editados(self):
        self.mover()
        cuenta = CuentaGastos.objects.get(garantia_origen=self.garantia)
        cuenta.titulo = 'Cuenta editada'
        cuenta.save(update_fields=['titulo'])
        cuenta.asignados.clear()
        antes = CuentaGastos.objects.values().get(pk=cuenta.pk)
        self.mover(estado=self.origen.codigo)
        self.mover(alternativa=True)
        self.assertEqual(CuentaGastos.objects.values().get(pk=cuenta.pk), antes)
        self.assertFalse(cuenta.asignados.exists())
        self.assertEqual(CuentaGastos.objects.count(), 1)

    def test_usuario_solo_lectura_no_puede_mover_ni_transferir(self):
        from solicitudes.permissions import grupo_solo_lectura
        lector = get_user_model().objects.create_user(username='lector-garantias')
        lector.groups.add(grupo_solo_lectura())
        self.client.force_login(lector)
        self.assertEqual(self.mover().status_code, 403)
        self.assertEqual(self.mover(alternativa=True).status_code, 403)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.columna_id, self.origen.pk)
        self.assertFalse(CuentaGastos.objects.exists())

    def test_reentrada_devuelve_cuenta_a_destino_sin_sobrescribir_otros_datos(self):
        for alternativa in (False, True):
            with self.subTest(alternativa=alternativa):
                self.mover()
                cuenta = CuentaGastos.objects.get(garantia_origen=self.garantia)
                otra_columna = CuentaGastosColumna.objects.exclude(codigo='DEVOLUCION_A_GARANTIAS').filter(activa=True).first()
                cuenta.titulo = 'Cuenta editada por usuario'
                cuenta.descripcion = 'Conservar esta descripción'
                cuenta.estado = otra_columna.codigo
                cuenta.columna = otra_columna
                cuenta.save()
                cuenta.asignados.clear()
                antes = CuentaGastos.objects.values().get(pk=cuenta.pk)
                self.mover(estado=self.origen.codigo)
                self.assertEqual(self.mover(alternativa).status_code, 200)
                despues = CuentaGastos.objects.values().get(pk=cuenta.pk)
                self.assertEqual(despues.pop('estado'), 'DEVOLUCION_A_GARANTIAS')
                self.assertEqual(despues.pop('columna_id'), CuentaGastosColumna.objects.get(codigo='DEVOLUCION_A_GARANTIAS').pk)
                antes.pop('estado')
                antes.pop('columna_id')
                self.assertEqual(despues, antes)
                self.assertFalse(cuenta.asignados.exists())
                self.assertEqual(CuentaGastos.objects.count(), 1)
                self.assertEqual(Garantia.objects.count(), 1)

    def test_error_posterior_revierte_reubicacion_de_cuenta_existente(self):
        self.mover()
        cuenta = CuentaGastos.objects.get(garantia_origen=self.garantia)
        otra_columna = CuentaGastosColumna.objects.exclude(codigo='DEVOLUCION_A_GARANTIAS').filter(activa=True).first()
        cuenta.estado = otra_columna.codigo
        cuenta.columna = otra_columna
        cuenta.save(update_fields=['estado', 'columna'])
        antes = CuentaGastos.objects.values().get(pk=cuenta.pk)
        self.mover(estado=self.origen.codigo)

        def fallar(*args, **kwargs):
            enviar_garantia_a_cuenta_gastos(*args, **kwargs)
            raise ValueError('Fallo posterior a reubicar')

        with patch('garantias.views.enviar_garantia_a_cuenta_gastos', side_effect=fallar):
            self.assertEqual(self.mover().status_code, 400)
        self.assertEqual(CuentaGastos.objects.values().get(pk=cuenta.pk), antes)
        self.garantia.refresh_from_db()
        self.assertEqual(self.garantia.columna_id, self.origen.pk)
