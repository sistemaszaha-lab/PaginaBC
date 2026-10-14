import json
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from cuenta_gastos.models import AgenciaAduanal


AGENCIAS_AUTORIZADAS = (
    "DEL BRAVO",
    "GADI",
    "ZARAGOZA",
    "HANO",
    "ESCALANTE",
    "RIOJA",
    "ESTRATEGIA",
)


def normalizar(nombre):
    return " ".join((nombre or "").split()).casefold()


class Command(BaseCommand):
    help = "Limpia explícitamente el catálogo local de agencias aduanales."

    def add_arguments(self, parser):
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Confirma la creación/eliminación; sin esta opción sólo muestra el plan.",
        )
        parser.add_argument(
            "--backup",
            type=Path,
            help="Ruta del respaldo JSON del catálogo antes de modificarlo.",
        )

    def handle(self, *args, **options):
        relaciones = list(AgenciaAduanal._meta.related_objects)
        if relaciones:
            nombres = ", ".join(rel.get_accessor_name() for rel in relaciones)
            raise CommandError(
                "AgenciaAduanal tiene relaciones; limpieza detenida por seguridad: "
                + nombres
            )
        agencias = list(AgenciaAduanal.objects.order_by("id"))
        autorizadas = {normalizar(nombre): nombre for nombre in AGENCIAS_AUTORIZADAS}
        conservar = []
        eliminar = []
        vistos = set()

        for agencia in agencias:
            clave = normalizar(agencia.nombre)
            if clave in autorizadas and clave not in vistos:
                conservar.append(agencia)
                vistos.add(clave)
            else:
                eliminar.append(agencia)

        faltantes = [
            nombre for clave, nombre in autorizadas.items() if clave not in vistos
        ]
        self.stdout.write("Catálogo actual:")
        for agencia in agencias:
            self.stdout.write(f"  [{agencia.pk}] {agencia.nombre!r}")
        self.stdout.write("Entradas a eliminar:")
        for agencia in eliminar:
            self.stdout.write(f"  [{agencia.pk}] {agencia.nombre!r}")
        self.stdout.write(f"Agencias faltantes a crear: {', '.join(faltantes) or 'ninguna'}")

        if not options["apply"]:
            self.stdout.write(self.style.WARNING("Vista previa: no se modificó la base de datos. Use --apply para confirmar."))
            return

        backup_path = options["backup"]
        if backup_path is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_path = Path.cwd() / f"agencias_aduanales_backup_{timestamp}.json"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        backup_path.write_text(
            json.dumps(
                [{"id": a.pk, "nombre": a.nombre, "clave_normalizada": a.clave_normalizada} for a in agencias],
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        with transaction.atomic():
            for agencia in eliminar:
                agencia.delete()
            for nombre in faltantes:
                AgenciaAduanal.objects.create(nombre=nombre)

        final = list(AgenciaAduanal.objects.order_by("nombre", "id").values_list("nombre", flat=True))
        esperado = sorted(AGENCIAS_AUTORIZADAS)
        if final != esperado:
            raise CommandError(f"El catálogo final no coincide con lo esperado: {final!r}")
        self.stdout.write(f"Respaldo creado: {backup_path}")
        self.stdout.write(self.style.SUCCESS("Catálogo limpiado correctamente."))
        self.stdout.write("Catálogo final: " + ", ".join(final))
