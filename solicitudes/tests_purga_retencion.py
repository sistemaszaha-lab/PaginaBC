from datetime import datetime, timedelta, timezone as tz
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase

from operaciones.models import Operacion, OperacionArchivo
from garantias.models import Garantia, GarantiaArchivo
from solicitudes.tests_purga_segura import ArchivosTemporalesMixin
from solicitudes_app.trash import (
    TrashOperationError, enviar_a_papelera, restaurar_desde_papelera,
    eliminar_definitivamente,
)


class RetencionTests(ArchivosTemporalesMixin, TestCase):
    def test_interrupcion_despues_del_commit_deja_trabajo_recuperable(self):
        from solicitudes.models import ArchivoPurgaPendiente
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        enviar_a_papelera(op, self.user)
        # Simula muerte del proceso: commit lógico sin ejecutar callbacks.
        with self.captureOnCommitCallbacks(execute=False):
            eliminar_definitivamente(op)
        self.assertTrue(ruta.exists())
        self.assertEqual(ArchivoPurgaPendiente.objects.count(), 1)
        call_command('purgar_papelera', dry_run=True, stdout=StringIO())
        self.assertTrue(ruta.exists())
        self.assertEqual(ArchivoPurgaPendiente.objects.count(), 1)
        call_command('purgar_papelera', stdout=StringIO())
        self.assertFalse(ruta.exists())
        self.assertFalse(ArchivoPurgaPendiente.objects.exists())

    def test_limites_completos_cambio_de_mes_anio_y_zona(self):
        for ahora in (datetime(2027, 1, 15, tzinfo=tz.utc),
                      datetime(2026, 3, 1, 3, tzinfo=tz(timedelta(hours=-6)))):
            with self.subTest(ahora=ahora):
                edades = [timedelta(days=29), timedelta(days=30, microseconds=-1),
                          timedelta(days=30), timedelta(days=31)]
                objetos = [Operacion.objects.create(creado_por=self.user, eliminado_en=ahora-e) for e in edades]
                activo = Operacion.objects.create(creado_por=self.user)
                with patch('django.utils.timezone.now', return_value=ahora):
                    call_command('purgar_papelera', stdout=StringIO())
                    call_command('purgar_papelera', stdout=StringIO())
                self.assertEqual([Operacion.objects.filter(pk=o.pk).exists() for o in objetos], [True, True, False, False])
                self.assertTrue(Operacion.objects.filter(pk=activo.pk).exists())
                Operacion.objects.all().delete()

    def test_instancia_obsoleta_no_reinicia_fecha_y_nueva_eliminacion_si(self):
        op = Operacion.objects.create(creado_por=self.user)
        obsoleta = Operacion.objects.get(pk=op.pk)
        antes = datetime(2026, 10, 1, tzinfo=tz.utc)
        despues = antes + timedelta(days=20)
        with patch('django.utils.timezone.now', return_value=antes):
            enviar_a_papelera(op, self.user)
        with patch('django.utils.timezone.now', return_value=despues):
            with self.assertRaises(TrashOperationError):
                enviar_a_papelera(obsoleta, self.user)
            op.refresh_from_db()
            self.assertEqual(op.eliminado_en, antes)
            restaurar_desde_papelera(op)
            self.assertIsNone(op.eliminado_en)
            enviar_a_papelera(op, self.user)
            self.assertEqual(op.eliminado_en, despues)

    def test_instancia_obsoleta_no_borra_restaurado(self):
        op = Operacion.objects.create(creado_por=self.user)
        enviar_a_papelera(op, self.user)
        obsoleta = Operacion.objects.get(pk=op.pk)
        restaurar_desde_papelera(op)
        with self.assertRaises(TrashOperationError):
            eliminar_definitivamente(obsoleta)
        self.assertTrue(Operacion.objects.filter(pk=op.pk, eliminado_en__isnull=True).exists())

    def test_archivo_compartido_entre_modulos_sobrevive(self):
        op = Operacion.objects.create(creado_por=self.user)
        archivo, ruta = self.adjuntar(op)
        garantia = Garantia.objects.create(creado_por=self.user)
        GarantiaArchivo.objects.create(garantia=garantia, subido_por=self.user, archivo=archivo.archivo.name)
        enviar_a_papelera(op, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            eliminar_definitivamente(op)
        self.assertTrue(ruta.exists())
        enviar_a_papelera(garantia, self.user)
        with self.captureOnCommitCallbacks(execute=True):
            eliminar_definitivamente(garantia)
        self.assertFalse(ruta.exists())

    def test_archivo_ausente_no_impide_purga(self):
        op = Operacion.objects.create(creado_por=self.user)
        _, ruta = self.adjuntar(op)
        ruta.unlink()
        enviar_a_papelera(op, self.user)
        resultados = []
        with self.captureOnCommitCallbacks(execute=True):
            eliminar_definitivamente(op, on_storage_result=resultados.append)
        self.assertEqual(resultados, ['ausente'])

    def test_purga_automatica_conserva_vinculo_activo_set_null(self):
        op = Operacion.objects.create(creado_por=self.user, eliminado_en=datetime(2020, 1, 1, tzinfo=tz.utc))
        garantia = Garantia.objects.create(creado_por=self.user, operacion_origen=op)
        salida = StringIO()
        call_command('purgar_papelera', stdout=salida)
        garantia.refresh_from_db()
        self.assertEqual(garantia.operacion_origen_id, op.pk)
        self.assertIn('dependencia activa', salida.getvalue())

    def test_interrupcion_conserva_pendientes_y_reintento_termina(self):
        objetos = [Operacion.objects.create(creado_por=self.user, eliminado_en=datetime(2020, 1, 1, tzinfo=tz.utc)) for _ in range(3)]
        from solicitudes_app.trash import eliminar_definitivamente as real
        llamadas = 0
        def interrumpir(objeto, **kwargs):
            nonlocal llamadas
            llamadas += 1
            if llamadas == 2:
                raise KeyboardInterrupt()
            return real(objeto, **kwargs)
        with patch('solicitudes.management.commands.purgar_papelera.eliminar_definitivamente', side_effect=interrumpir):
            with self.assertRaises(KeyboardInterrupt):
                call_command('purgar_papelera', stdout=StringIO())
        self.assertEqual(Operacion.objects.filter(pk__in=[o.pk for o in objetos]).count(), 2)
        call_command('purgar_papelera', stdout=StringIO())
        self.assertFalse(Operacion.objects.exists())
