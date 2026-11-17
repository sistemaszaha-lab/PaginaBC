"""Los archivos sobreviven a PROTECT y a cualquier rollback de la purga."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch
from datetime import timedelta
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.files.storage import FileSystemStorage
from django.core.files.uploadedfile import SimpleUploadedFile
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, connection, transaction
from django.db.models import ProtectedError
from django.test import TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from operaciones.models import Operacion, OperacionArchivo, OperacionColumna, OperacionEtiqueta
from cuenta_gastos.models import CuentaGastos, CuentaGastosArchivo, DocumentoRepositorio
from garantias.models import Garantia, GarantiaArchivo
from panel_cotizaciones.models import PanelCotizacion, PanelCotizacionArchivo
from clientes.models import Cliente
from solicitudes_app.trash import TRASH_MODELS, enviar_a_papelera, eliminar_definitivamente, TrashOperationError


class ArchivosTemporalesMixin:
    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(username='purga-segura')
        temporal = TemporaryDirectory()
        self.addCleanup(temporal.cleanup)
        self.storage = FileSystemStorage(location=temporal.name)
        for modelo in (OperacionArchivo, CuentaGastosArchivo, GarantiaArchivo, PanelCotizacionArchivo, DocumentoRepositorio):
            parche = patch.object(modelo._meta.get_field('archivo'), 'storage', self.storage)
            parche.start()
            self.addCleanup(parche.stop)

    def adjuntar(self, obj, modelo=OperacionArchivo, campo='operacion'):
        archivo = modelo.objects.create(**{campo: obj}, subido_por=self.user,
            archivo=SimpleUploadedFile('auditoria.txt', b'contenido a preservar'))
        return archivo, Path(archivo.archivo.path)


class PurgaSeguraTests(ArchivosTemporalesMixin, TestCase):
    def test_documento_repositorio_elimina_archivo_solo_despues_del_commit(self):
        documento = DocumentoRepositorio.objects.create(
            nombre_original='factura.pdf', subido_por=self.user,
            archivo=SimpleUploadedFile('factura.pdf', b'pdf de prueba'),
        )
        ruta = Path(documento.archivo.path)
        pk = documento.pk
        enviar_a_papelera(documento, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            eliminar_definitivamente(documento)
            self.assertTrue(ruta.exists())
        self.assertFalse(DocumentoRepositorio.objects.filter(pk=pk).exists())
        self.assertFalse(ruta.exists())

    def test_documento_repositorio_con_rollback_conserva_archivo(self):
        documento = DocumentoRepositorio.objects.create(
            nombre_original='factura.pdf', subido_por=self.user,
            archivo=SimpleUploadedFile('factura.pdf', b'pdf de prueba'),
        )
        ruta = Path(documento.archivo.path)
        pk = documento.pk
        enviar_a_papelera(documento, self.user)
        with self.captureOnCommitCallbacks(execute=True) as callbacks:
            with self.assertRaisesRegex(RuntimeError, 'rollback'):
                with transaction.atomic():
                    eliminar_definitivamente(documento)
                    raise RuntimeError('rollback')
        self.assertEqual(callbacks, [])
        self.assertTrue(DocumentoRepositorio.objects.filter(pk=pk).exists())
        self.assertTrue(ruta.exists())

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


class PreparacionPurgaTests(ArchivosTemporalesMixin, TestCase):
    def test_segunda_ejecucion_se_rechaza_si_el_bloqueo_esta_ocupado(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = (False,)
        conexion = MagicMock()
        conexion.vendor = 'postgresql'
        conexion.cursor.return_value.__enter__.return_value = cursor
        with patch('solicitudes.management.commands.purgar_papelera.connection', conexion):
            with self.assertRaisesRegex(CommandError, 'otra ejecución'):
                call_command('purgar_papelera', dry_run=True, stdout=StringIO())
        cursor.execute.assert_called_once_with(
            'SELECT pg_try_advisory_lock(%s, %s)', (24402, 1)
        )

    def vencer(self, objeto, dias):
        enviar_a_papelera(objeto, self.user)
        type(objeto).objects.filter(pk=objeto.pk).update(
            eliminado_en=timezone.now() - timedelta(days=dias)
        )
        objeto.refresh_from_db()

    def test_dry_run_identifica_vencidos_bloqueos_y_no_modifica_nada(self):
        protegida = Operacion.objects.create(titulo='Protegida', creado_por=self.user)
        copia_flete = CuentaGastos.objects.create(
            titulo='Copia activa', creado_por=self.user,
            operacion_flete_origen=protegida,
        )
        eliminable = Operacion.objects.create(titulo='Eliminable', creado_por=self.user)
        reciente = Operacion.objects.create(titulo='Reciente', creado_por=self.user)
        documento = DocumentoRepositorio.objects.create(
            nombre_original='retener.pdf', subido_por=self.user,
            archivo=SimpleUploadedFile('retener.pdf', b'archivo intacto'),
        )
        archivo = Path(documento.archivo.path)
        for objeto, dias in ((protegida, 40), (eliminable, 31), (reciente, 29), (documento, 35)):
            self.vencer(objeto, dias)
        marcas = {objeto.pk: objeto.eliminado_en for objeto in (protegida, eliminable, reciente)}
        salida = StringIO()
        errores = StringIO()

        with CaptureQueriesContext(connection) as consultas:
            call_command('purgar_papelera', dry_run=True, stdout=salida, stderr=errores)

        self.assertFalse(any(
            query['sql'].lstrip().upper().startswith(('INSERT ', 'UPDATE ', 'DELETE '))
            for query in consultas.captured_queries
        ))
        self.assertIn('operacion: vencidos=2, potencialmente_eliminables=1, protegidos=1, errores=0.', salida.getvalue())
        self.assertEqual(salida.getvalue().count(': vencidos='), len(TRASH_MODELS))
        self.assertIn('operacion_flete_origen', salida.getvalue())
        self.assertIn('documento_repositorio: vencidos=1, potencialmente_eliminables=1', salida.getvalue())
        self.assertNotIn(f'operacion #{reciente.pk}:', salida.getvalue())
        self.assertEqual(errores.getvalue(), '')
        self.assertTrue(archivo.exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=copia_flete.pk, eliminado_en__isnull=True).exists())
        self.assertTrue(DocumentoRepositorio.objects.filter(pk=documento.pk).exists())
        for objeto in (protegida, eliminable, reciente):
            objeto.refresh_from_db()
            self.assertEqual(objeto.eliminado_en, marcas[objeto.pk])

    def test_comando_conserva_protegidos_y_registra_errores_individuales(self):
        protegido = Operacion.objects.create(titulo='Con copia', creado_por=self.user)
        copia = CuentaGastos.objects.create(creado_por=self.user, operacion_flete_origen=protegido)
        anticipo_origen = Operacion.objects.create(titulo='Con anticipo', creado_por=self.user)
        anticipo = CuentaGastos.objects.create(creado_por=self.user, operacion_anticipo_origen=anticipo_origen)
        cuenta_origen = CuentaGastos.objects.create(titulo='Con solicitud GEO', creado_por=self.user)
        solicitud_geo = CuentaGastos.objects.create(creado_por=self.user, vobo_angie_origen=cuenta_origen)
        fallido = Operacion.objects.create(titulo='Fallo individual', creado_por=self.user)
        siguiente = Operacion.objects.create(titulo='Siguiente', creado_por=self.user)
        reciente = Operacion.objects.create(titulo='Menos de treinta días', creado_por=self.user)
        for objeto, dias in ((protegido, 45), (anticipo_origen, 44), (cuenta_origen, 42),
                             (fallido, 40), (siguiente, 35), (reciente, 29)):
            self.vencer(objeto, dias)
        from solicitudes_app.trash import eliminar_definitivamente as eliminar_real

        def eliminar_con_error(objeto, **kwargs):
            if objeto.pk == fallido.pk:
                raise TrashOperationError('fallo de prueba')
            return eliminar_real(objeto, **kwargs)

        salida, errores = StringIO(), StringIO()
        with patch('solicitudes.management.commands.purgar_papelera.eliminar_definitivamente', side_effect=eliminar_con_error):
            with self.assertRaises(CommandError):
                call_command('purgar_papelera', stdout=salida, stderr=errores)
        self.assertIn(f'operacion #{fallido.pk}: no se pudo purgar (fallo de prueba).', errores.getvalue())
        self.assertIn('operacion: vencidos=4, potencialmente_eliminables=2, protegidos=2, errores=1.', salida.getvalue())
        self.assertIn('cuenta_gastos: vencidos=1, potencialmente_eliminables=0, protegidos=1, errores=0.', salida.getvalue())
        self.assertTrue(Operacion.objects.filter(pk=protegido.pk).exists())
        self.assertTrue(Operacion.objects.filter(pk=anticipo_origen.pk).exists())
        self.assertTrue(Operacion.objects.filter(pk=fallido.pk).exists())
        self.assertFalse(Operacion.objects.filter(pk=siguiente.pk).exists())
        self.assertTrue(Operacion.objects.filter(pk=reciente.pk).exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=copia.pk, eliminado_en__isnull=True).exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=anticipo.pk, eliminado_en__isnull=True).exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=cuenta_origen.pk).exists())
        self.assertTrue(CuentaGastos.objects.filter(pk=solicitud_geo.pk, eliminado_en__isnull=True).exists())

    def test_no_permite_reducir_la_retencion_minima(self):
        with self.assertRaises(CommandError):
            call_command('purgar_papelera', days=29, dry_run=True, stdout=StringIO())

    def test_dry_run_recorre_mas_de_un_lote_sin_borrar(self):
        etiquetas = [OperacionEtiqueta(nombre=f'etiqueta-purga-{indice}') for indice in range(201)]
        OperacionEtiqueta.objects.bulk_create(etiquetas)
        OperacionEtiqueta.objects.filter(nombre__startswith='etiqueta-purga-').update(
            eliminado_en=timezone.now() - timedelta(days=31)
        )
        salida = StringIO()
        call_command('purgar_papelera', dry_run=True, stdout=salida)
        self.assertIn('operacion_etiqueta: vencidos=201, potencialmente_eliminables=201, protegidos=0, errores=0.', salida.getvalue())
        self.assertEqual(OperacionEtiqueta.objects.filter(nombre__startswith='etiqueta-purga-').count(), 201)

    def test_no_elimina_un_registro_restaurado_durante_la_ejecucion(self):
        operacion = Operacion.objects.create(titulo='Restaurada', creado_por=self.user)
        self.vencer(operacion, 35)

        def restaurar_antes_del_borrado(objeto):
            type(objeto).objects.filter(pk=objeto.pk).update(eliminado_en=None)
            return None

        salida = StringIO()
        with patch(
            'solicitudes.management.commands.purgar_papelera.Command._evaluar_relaciones',
            side_effect=restaurar_antes_del_borrado,
        ):
            call_command('purgar_papelera', stdout=salida)
        self.assertTrue(Operacion.objects.filter(pk=operacion.pk, eliminado_en__isnull=True).exists())
        self.assertIn('omitido; ya no está vencido', salida.getvalue())


class CommitRealPurgaTests(ArchivosTemporalesMixin, TransactionTestCase):
    def test_error_de_archivo_posterior_al_commit_falla_el_comando(self):
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        pk = op.pk
        enviar_a_papelera(op, self.user)
        Operacion.objects.filter(pk=pk).update(
            eliminado_en=timezone.now() - timedelta(days=31)
        )
        salida, errores = StringIO(), StringIO()

        with patch.object(self.storage, 'delete', side_effect=OSError('storage no disponible')):
            with self.assertRaises(CommandError):
                call_command('purgar_papelera', stdout=salida, stderr=errores)

        self.assertFalse(Operacion.objects.filter(pk=pk).exists())
        self.assertTrue(ruta.exists())
        self.assertIn('registro eliminado, pero falló el borrado del archivo', errores.getvalue())
        self.assertIn('errores=1', salida.getvalue())

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
