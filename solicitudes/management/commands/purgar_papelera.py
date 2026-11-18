from __future__ import annotations

from datetime import timedelta
import os

from collections import Counter
from time import monotonic

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, connection, transaction
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from django.utils import timezone

from solicitudes_app.trash import (
    TRASH_MODELS,
    TRASH_RETENTION_DAYS,
    TrashOperationError,
    eliminar_definitivamente,
    get_deleted_queryset,
    procesar_archivo_pendiente,
)


class Command(BaseCommand):
    help = "Elimina definitivamente los elementos de la papelera que superaron la retención."

    # Bloqueo de sesión compartido por todas las invocaciones del comando en PostgreSQL.
    # Se libera también si el proceso termina o pierde la conexión.
    LOCK_KEY = (24402, 1)

    def execute(self, *args, **options):
        inicio = monotonic()
        dry_run = bool(options.get("dry_run"))
        estado = "error"
        bloqueo = False
        self.stdout.write(f"Inicio purga_papelera: fecha={timezone.now().isoformat()}, entorno={os.getenv('RAILWAY_ENVIRONMENT_NAME', 'local')}, modo={'dry-run' if dry_run else 'real'}.")
        try:
            if connection.vendor == "postgresql":
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_try_advisory_lock(%s, %s)", self.LOCK_KEY)
                    bloqueo = cursor.fetchone()[0]
                if not bloqueo:
                    raise CommandError("Ya hay otra ejecución de purgar_papelera en curso.")
            resultado = super().execute(*args, **options)
            estado = "correcto"
            return resultado
        finally:
            if bloqueo:
                try:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT pg_advisory_unlock(%s, %s)", self.LOCK_KEY)
                except DatabaseError as exc:
                    self.stderr.write(f"No se pudo liberar el bloqueo de purga: {type(exc).__name__}.")
            self.stdout.write(
                f"Fin purga_papelera: modo={'dry-run' if dry_run else 'real'}, "
                f"estado={estado}, fecha={timezone.now().isoformat()}, duracion_segundos={monotonic() - inicio:.2f}."
            )

    def add_arguments(self, parser):
        parser.add_argument(
            "--days",
            type=int,
            default=TRASH_RETENTION_DAYS,
            help="Días de retención antes de purgar. Por defecto: 30.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Identifica vencidos y bloqueos sin modificar registros ni archivos.",
        )

    @staticmethod
    def _evaluar_relaciones(objeto):
        """Django Collector aplica las mismas reglas CASCADE/SET_NULL/PROTECT/RESTRICT.

        collect() consulta las relaciones, pero no ejecuta DELETE ni UPDATE.
        La eliminación real vuelve a comprobarlas dentro de su transacción.
        """
        try:
            Collector(using=objeto._state.db).collect([objeto])
        except (ProtectedError, RestrictedError) as exc:
            politica = "PROTECT" if isinstance(exc, ProtectedError) else "RESTRICT"
            return f"{politica}: {exc.args[0]}"
        # SET_NULL conserva el hijo, pero la purga automática no debe romper
        # vínculos con tarjetas activas. No cambia la eliminación manual.
        for relacion in objeto._meta.related_objects:
            modelo = relacion.related_model
            if any(c.name == "eliminado_en" for c in modelo._meta.fields):
                if modelo.objects.filter(**{
                    relacion.field.name: objeto,
                    "eliminado_en__isnull": True,
                }).exists():
                    return f"dependencia activa: {modelo._meta.label}.{relacion.field.name}"
        return None

    def handle(self, *args, **options):
        days = int(options["days"])
        if days < TRASH_RETENTION_DAYS:
            raise CommandError(
                f"La retención mínima es de {TRASH_RETENTION_DAYS} días completos."
            )
        dry_run = bool(options["dry_run"])
        limite = timezone.now() - timedelta(days=days)

        eliminados = 0
        errores = 0
        archivos = Counter()
        from solicitudes.models import ArchivoPurgaPendiente
        self.stdout.write(f"Archivos pendientes de reintento: {ArchivoPurgaPendiente.objects.count()}.")
        if not dry_run:
            def error_pendiente(nombre, exc):
                nonlocal errores
                errores += 1
                self.stderr.write(f"Error al reintentar archivo pendiente ({type(exc).__name__}).")
            for pendiente in ArchivoPurgaPendiente.objects.order_by('pk').iterator(chunk_size=200):
                procesar_archivo_pendiente(pendiente, on_storage_error=error_pendiente,
                                          on_storage_result=lambda estado: archivos.update([estado]))

        for tipo, config in TRASH_MODELS.items():
            queryset = get_deleted_queryset(config.model).filter(
                eliminado_en__lte=limite
            )
            motivos = Counter()
            vencidos = 0
            protegidos = 0
            potenciales = 0
            errores_modelo = 0
            eliminados_modelo = 0
            mas_antiguo = queryset.order_by("eliminado_en").values_list("eliminado_en", flat=True).first()
            self.stdout.write(f"{tipo}: fecha_mas_antigua={mas_antiguo.isoformat() if mas_antiguo else '-'}.")
            ultimo_pk = 0
            while True:
                # Páginas por PK evitan cargar toda la papelera en memoria.
                candidatos = list(
                    queryset.filter(pk__gt=ultimo_pk).order_by("pk")[:200]
                )
                if not candidatos:
                    break
                ultimo_pk = candidatos[-1].pk
                for objeto in candidatos:
                    vencidos += 1
                    try:
                        motivo = self._evaluar_relaciones(objeto)
                    except DatabaseError as exc:
                        errores_modelo += 1
                        errores += 1
                        self.stderr.write(f"{tipo} #{objeto.pk}: error al revisar relaciones ({type(exc).__name__}).")
                        continue
                    if motivo:
                        protegidos += 1
                        motivos[motivo] += 1
                        self.stdout.write(f"{tipo} #{objeto.pk}: protegido ({motivo}).")
                        continue

                    potenciales += 1
                    if dry_run:
                        self.stdout.write(f"{tipo} #{objeto.pk}: potencialmente eliminable.")
                        continue
                    def registrar_error_archivo(nombre, exc):
                        nonlocal errores, errores_modelo
                        errores += 1
                        errores_modelo += 1
                        self.stderr.write(
                            f"{tipo} #{objeto.pk}: registro eliminado, pero falló "
                            f"el borrado del archivo ({type(exc).__name__})."
                        )

                    try:
                        with transaction.atomic():
                            actual = (
                                config.model.objects.select_for_update()
                                .filter(pk=objeto.pk, eliminado_en__lte=limite)
                                .first()
                            )
                            if actual is None:
                                self.stdout.write(
                                    f"{tipo} #{objeto.pk}: omitido; ya no está vencido."
                                )
                                continue
                            # Serializa restauraciones de tarjetas dependientes
                            # antes de revalidar SET_NULL y relaciones compartidas.
                            for relacion in actual._meta.related_objects:
                                modelo = relacion.related_model
                                if any(c.name == "eliminado_en" for c in modelo._meta.fields):
                                    list(modelo.objects.select_for_update().filter(
                                        **{relacion.field.name: actual}
                                    ).values_list('pk', flat=True))
                            motivo = self._evaluar_relaciones(actual)
                            if motivo:
                                protegidos += 1
                                self.stdout.write(f"{tipo} #{objeto.pk}: protegido al revalidar ({motivo}).")
                                continue
                            eliminar_definitivamente(
                                actual, on_storage_error=registrar_error_archivo,
                                on_storage_result=lambda estado: archivos.update([estado]),
                            )
                    except (TrashOperationError, DatabaseError) as exc:
                        errores_modelo += 1
                        errores += 1
                        detalle = type(exc).__name__ if isinstance(exc, DatabaseError) else str(exc)
                        self.stderr.write(f"{tipo} #{objeto.pk}: no se pudo purgar ({detalle}).")
                        continue
                    eliminados += 1
                    eliminados_modelo += 1

            self.stdout.write(
                f"{tipo}: vencidos={vencidos}, "
                f"potencialmente_eliminables={potenciales}, "
                f"protegidos={protegidos}, errores={errores_modelo}."
            )
            self.stdout.write(f"{tipo}: eliminados={eliminados_modelo}.")
            for motivo, cantidad in sorted(motivos.items()):
                self.stdout.write(f"  {cantidad} bloqueado(s) por {motivo}")

        self.stdout.write(f"Archivos: eliminados={archivos['eliminado']}, compartidos={archivos['compartido']}, ausentes={archivos['ausente']}.")
        if dry_run:
            self.stdout.write(self.style.WARNING("Simulación de solo lectura completada; no se eliminó ningún elemento."))
            if errores:
                raise CommandError(f"La simulación terminó con {errores} error(es).")
            return

        resumen = f"Purga completada: {eliminados} elemento(s) eliminado(s)"
        if errores:
            resumen += f", {errores} error(es)."
            self.stdout.write(self.style.WARNING(resumen))
            raise CommandError("La purga terminó con errores individuales; revisa el registro anterior.")
        self.stdout.write(self.style.SUCCESS(f"{resumen}."))
