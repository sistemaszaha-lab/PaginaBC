from __future__ import annotations

from datetime import timedelta

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db import DatabaseError, transaction
from django.db.models import ProtectedError, RestrictedError
from django.db.models.deletion import Collector
from django.utils import timezone

from solicitudes_app.trash import (
    TRASH_MODELS,
    TRASH_RETENTION_DAYS,
    TrashOperationError,
    eliminar_definitivamente,
    get_deleted_queryset,
)


class Command(BaseCommand):
    help = "Elimina definitivamente los elementos de la papelera que superaron la retención."

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

        for tipo, config in TRASH_MODELS.items():
            queryset = get_deleted_queryset(config.model).filter(
                eliminado_en__lte=limite
            )
            motivos = Counter()
            vencidos = 0
            protegidos = 0
            potenciales = 0
            errores_modelo = 0
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
                        self.stderr.write(f"{tipo} #{objeto.pk}: error al revisar relaciones ({exc}).")
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
                            eliminar_definitivamente(actual)
                    except (TrashOperationError, DatabaseError) as exc:
                        errores_modelo += 1
                        errores += 1
                        self.stderr.write(f"{tipo} #{objeto.pk}: no se pudo purgar ({exc}).")
                        continue
                    eliminados += 1

            self.stdout.write(
                f"{tipo}: vencidos={vencidos}, "
                f"potencialmente_eliminables={potenciales}, "
                f"protegidos={protegidos}, errores={errores_modelo}."
            )
            for motivo, cantidad in sorted(motivos.items()):
                self.stdout.write(f"  {cantidad} bloqueado(s) por {motivo}")

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
