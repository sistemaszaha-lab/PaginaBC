from __future__ import annotations

from datetime import timedelta

from django.core.management.base import BaseCommand
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
            help="Muestra cuántos elementos se purgarían sin eliminarlos.",
        )

    def handle(self, *args, **options):
        days = max(0, int(options["days"]))
        dry_run = bool(options["dry_run"])
        limite = timezone.now() - timedelta(days=days)

        eliminados = 0
        errores = 0

        for tipo, config in TRASH_MODELS.items():
            queryset = get_deleted_queryset(config.model).filter(
                eliminado_en__lte=limite
            ).order_by("eliminado_en", "pk")
            candidatos = list(queryset)

            if dry_run:
                self.stdout.write(
                    f"{tipo}: {len(candidatos)} elemento(s) elegible(s) para purga."
                )
                continue

            for objeto in candidatos:
                try:
                    eliminar_definitivamente(objeto)
                except TrashOperationError as exc:
                    errores += 1
                    self.stderr.write(
                        f"{tipo} #{objeto.pk}: no se pudo purgar ({exc})."
                    )
                    continue
                eliminados += 1

        if dry_run:
            self.stdout.write(self.style.WARNING("Ejecución de simulación completada."))
            return

        resumen = f"Purga completada: {eliminados} elemento(s) eliminado(s)"
        if errores:
            resumen += f", {errores} error(es)."
            self.stdout.write(self.style.WARNING(resumen))
            return
        self.stdout.write(self.style.SUCCESS(f"{resumen}."))
