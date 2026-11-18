from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from io import StringIO
from threading import Event
from unittest import skipUnless

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection, connections, transaction
from django.test import TransactionTestCase
from django.utils import timezone

from operaciones.models import Operacion
from solicitudes_app.trash import restaurar_desde_papelera


@skipUnless(connection.vendor == 'postgresql', 'Requiere bloqueos reales PostgreSQL')
class ConcurrenciaPostgresTests(TransactionTestCase):
    def test_segunda_purga_no_adquiere_bloqueo_de_sesion(self):
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_lock(24402, 1)')
        def segunda():
            try:
                with self.assertRaisesMessage(CommandError, 'otra ejecución'):
                    call_command('purgar_papelera', dry_run=True, stdout=StringIO())
            finally:
                connections.close_all()
        try:
            with ThreadPoolExecutor(1) as pool:
                pool.submit(segunda).result(timeout=10)
        finally:
            with connection.cursor() as cursor:
                cursor.execute('SELECT pg_advisory_unlock(24402, 1)')

    def test_restauracion_confirmada_mientras_purga_espera_bloqueo(self):
        usuario = get_user_model().objects.create_user(username='concurrente')
        op = Operacion.objects.create(creado_por=usuario, eliminado_en=timezone.now()-timedelta(days=31))
        inicio = Event()
        def purgar():
            try:
                inicio.set()
                call_command('purgar_papelera', stdout=StringIO())
            finally:
                connections.close_all()
        with ThreadPoolExecutor(1) as pool:
            with transaction.atomic():
                bloqueado = Operacion.objects.select_for_update().get(pk=op.pk)
                futuro = pool.submit(purgar)
                self.assertTrue(inicio.wait(5))
                restaurar_desde_papelera(bloqueado)
            futuro.result(timeout=15)
        self.assertTrue(Operacion.objects.filter(pk=op.pk, eliminado_en__isnull=True).exists())
