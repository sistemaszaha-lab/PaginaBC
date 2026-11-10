"""Los archivos sobreviven a PROTECT y a cualquier rollback de la purga."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase

from operaciones.models import Operacion, OperacionArchivo, OperacionColumna
from cuenta_gastos.models import CuentaGastos, CuentaGastosArchivo
from garantias.models import Garantia, GarantiaArchivo
from panel_cotizaciones.models import PanelCotizacion, PanelCotizacionArchivo
from clientes.models import Cliente
from solicitudes_app.trash import enviar_a_papelera, eliminar_definitivamente, TrashOperationError


class ArchivosTemporalesMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username='purga-segura')
        temporal = TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.storage = FileSystemStorage(location=temporal.name)
        for modelo in (OperacionArchivo, CuentaGastosArchivo, GarantiaArchivo, PanelCotizacionArchivo):
            parche = patch.object(modelo._meta.get_field('archivo'), 'storage', self.storage)
            parche.start()
            self.addCleanup(parche.stop)

    def adjuntar(self, obj, modelo=OperacionArchivo, campo='operacion'):
        archivo = modelo.objects.create(**{campo: obj}, subido_por=self.user,
            archivo=SimpleUploadedFile('auditoria.txt', b'contenido a preservar'))
        return archivo, Path(archivo.archivo.path)


class PurgaSeguraTests(ArchivosTemporalesMixin, TestCase):
    def test_protect_nuevos_conservan_tarjetas_registros_y_archivos(self):
        for modelo, archivo_model, campo, vinculo in (
            (Operacion, OperacionArchivo, 'operacion', 'operacion_flete_origen'),
            (CuentaGastos, CuentaGastosArchivo, 'cuenta_gasto', 'vobo_angie_origen'),
        ):
            with self.subTest(modelo=modelo):
                origen = modelo.objects.create(creado_por=self.user)
                CuentaGastos.objects.create(creado_por=self.user, **{vinculo: origen})
                archivo, ruta = self.adjuntar(origen, archivo_model, campo)
                enviar_a_papelera(origen, self.user)
                with self.captureOnCommitCallbacks(execute=True) as callbacks:
                    with self.assertRaises(TrashOperationError):
                        eliminar_definitivamente(origen)
                self.assertEqual(callbacks, [])
                self.assertTrue(modelo.objects.filter(pk=origen.pk).exists())
                self.assertTrue(archivo_model.objects.filter(pk=archivo.pk).exists())
                self.assertEqual(ruta.read_bytes(), b'contenido a preservar')

    def test_politicas_protect_historicas_de_cliente_columna_y_usuario_no_cambian(self):
        cliente = Cliente.objects.create(nombre='Cliente protegido')
        columna = OperacionColumna.objects.create(nombre='Columna protegida', codigo='PROTEGIDA')
        op = Operacion.objects.create(creado_por=self.user, cliente=cliente, columna=columna, estado=columna.codigo)
        _, ruta = self.adjuntar(op)
        for protegido in (cliente, columna, self.user):
            with self.subTest(modelo=type(protegido)), self.assertRaises(ProtectedError):
                protegido.delete()
        self.assertTrue(ruta.exists())
        self.assertTrue(Operacion.objects.filter(pk=op.pk).exists())

    def test_set_null_historico_permite_purgar_y_conserva_espejo(self):
        op = Operacion.objects.create(creado_por=self.user)
        espejo = CuentaGastos.objects.create(creado_por=self.user, operacion_origen=op)
        _, ruta = self.adjuntar(op)
        enviar_a_papelera(op, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            eliminar_definitivamente(op)
            self.assertTrue(ruta.exists())
        self.assertFalse(ruta.exists())
        espejo.refresh_from_db()
        self.assertIsNone(espejo.operacion_origen_id)

    def test_purgas_de_tableros_difieren_archivos_hasta_commit(self):
        for modelo, archivo_model, campo in (
            (Operacion, OperacionArchivo, 'operacion'),
            (CuentaGastos, CuentaGastosArchivo, 'cuenta_gasto'),
            (Garantia, GarantiaArchivo, 'garantia'),
            (PanelCotizacion, PanelCotizacionArchivo, 'cotizacion'),
        ):
            with self.subTest(modelo=modelo):
                obj = modelo.objects.create(creado_por=self.user)
                _, ruta = self.adjuntar(obj, archivo_model, campo)
                pk = obj.pk
                enviar_a_papelera(obj, self.user)
                with self.captureOnCommitCallbacks(execute=True):
                    eliminar_definitivamente(obj)
                    self.assertFalse(modelo.objects.filter(pk=pk).exists())
                    self.assertTrue(ruta.exists())
                self.assertFalse(ruta.exists())

    def test_rollback_exterior_conserva_archivo_y_descarta_callback(self):
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        pk = op.pk
        enviar_a_papelera(op, self.user)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaisesRegex(RuntimeError, 'posterior'):
                with transaction.atomic():
                    eliminar_definitivamente(op)
                    raise RuntimeError('fallo posterior')
        self.assertEqual(callbacks, [])
        self.assertTrue(Operacion.objects.filter(pk=pk).exists())
        self.assertTrue(ruta.exists())

    def test_error_storage_se_registra_sin_interrumpir_otros_borrados(self):
        op = Operacion.objects.create(creado_por=self.user)
        self.adjuntar(op)
        self.adjuntar(op)
        pk = op.pk
        enviar_a_papelera(op, self.user)
        with patch.object(self.storage, 'delete', side_effect=[OSError('storage no disponible'), None]) as borrar:
            with self.assertLogs('django.test', level='ERROR'):
                with self.captureOnCommitCallbacks(execute=True):
                    eliminar_definitivamente(op)
        self.assertEqual(borrar.call_count, 2)
        self.assertFalse(Operacion.objects.filter(pk=pk).exists())


class CommitRealPurgaTests(ArchivosTemporalesMixin, TransactionTestCase):
    def test_archivo_se_elimina_despues_de_commit_real(self):
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        pk = op.pk
        enviar_a_papelera(op, self.user)
        with transaction.atomic():
            eliminar_definitivamente(op)
            self.assertTrue(ruta.exists())
        self.assertFalse(ruta.exists())
        self.assertFalse(Operacion.objects.filter(pk=pk).exists())

    def test_fallo_fk_diferida_al_commit_conserva_todo(self):
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        pk = op.pk
        enviar_a_papelera(op, self.user)
        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                CuentaGastos.objects.create(creado_por_id=self.user.pk + 100000)
                eliminar_definitivamente(op)
        self.assertTrue(ruta.exists())
        self.assertTrue(Operacion.objects.filter(pk=pk).exists())
