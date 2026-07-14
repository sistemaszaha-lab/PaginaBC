from collections import defaultdict

from django.core.management.base import BaseCommand
from django.db import transaction

from clientes.models import Cliente, normalizar_texto_cliente


class Command(BaseCommand):
    help = "Normaliza los campos nombre y empresa de todos los clientes existentes."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Muestra los cambios que se realizarian sin guardar nada.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        resumen = self._preparar_resumen()

        self._mostrar_candidatos_duplicado(resumen["duplicados"])

        if dry_run:
            self._mostrar_cambios(resumen["cambios"])
            self._mostrar_resumen(resumen, dry_run=True)
            return

        errores = resumen["errores"]
        modificados = 0

        try:
            with transaction.atomic():
                for cambio in resumen["cambios"]:
                    cliente = Cliente.objects.get(pk=cambio["id"])
                    update_fields = []

                    if cliente.nombre != cambio["nombre_nuevo"]:
                        cliente.nombre = cambio["nombre_nuevo"]
                        update_fields.append("nombre")
                    if cliente.empresa != cambio["empresa_nueva"]:
                        cliente.empresa = cambio["empresa_nueva"]
                        update_fields.append("empresa")

                    if update_fields:
                        cliente.save(update_fields=update_fields)
                        modificados += 1
        except Exception as exc:
            errores += 1
            self.stdout.write(self.style.ERROR(f"ERROR: {exc}"))

        resumen["modificados"] = modificados
        resumen["errores"] = errores
        self._mostrar_resumen(resumen, dry_run=False)

    def _preparar_resumen(self):
        total = 0
        sin_cambios = 0
        errores = 0
        cambios = []
        pares_normalizados = defaultdict(list)

        for cliente in Cliente.objects.order_by("id").iterator():
            total += 1
            try:
                nombre_actual = cliente.nombre
                empresa_actual = cliente.empresa
                nombre_nuevo = normalizar_texto_cliente(nombre_actual)
                empresa_nueva = normalizar_texto_cliente(empresa_actual)

                pares_normalizados[(nombre_nuevo, empresa_nueva)].append(cliente.id)

                if nombre_actual == nombre_nuevo and empresa_actual == empresa_nueva:
                    sin_cambios += 1
                    continue

                cambios.append(
                    {
                        "id": cliente.id,
                        "nombre_anterior": nombre_actual,
                        "nombre_nuevo": nombre_nuevo,
                        "empresa_anterior": empresa_actual,
                        "empresa_nueva": empresa_nueva,
                    }
                )
            except Exception as exc:
                errores += 1
                self.stdout.write(
                    self.style.ERROR(f"ERROR preparando cliente ID {cliente.id}: {exc}")
                )

        duplicados = [
            {"nombre": nombre, "empresa": empresa, "ids": ids}
            for (nombre, empresa), ids in pares_normalizados.items()
            if len(ids) > 1
        ]

        return {
            "total": total,
            "modificados": len(cambios),
            "sin_cambios": sin_cambios,
            "errores": errores,
            "cambios": cambios,
            "duplicados": duplicados,
        }

    def _mostrar_cambios(self, cambios):
        if not cambios:
            self.stdout.write("No hay clientes que requieran normalizacion.")
            return

        self.stdout.write("Clientes que cambiarian:")
        for cambio in cambios:
            self.stdout.write(f"ID {cambio['id']}")
            self.stdout.write(f"  nombre:  '{cambio['nombre_anterior']}' -> '{cambio['nombre_nuevo']}'")
            self.stdout.write(f"  empresa: '{cambio['empresa_anterior']}' -> '{cambio['empresa_nueva']}'")

    def _mostrar_candidatos_duplicado(self, duplicados):
        if not duplicados:
            self.stdout.write("Candidatos a duplicado encontrados: ninguno.")
            return

        self.stdout.write(
            self.style.WARNING(
                "ADVERTENCIA: la normalizacion deja clientes con el mismo par "
                "(nombre normalizado, empresa normalizada)."
            )
        )
        self.stdout.write(
            self.style.WARNING(
                "No se unificara ni eliminara ningun registro; quedan como candidatos para una etapa posterior."
            )
        )
        for duplicado in duplicados:
            self.stdout.write(
                f"  nombre='{duplicado['nombre']}' empresa='{duplicado['empresa']}' ids={duplicado['ids']}"
            )

    def _mostrar_resumen(self, resumen, dry_run):
        modo = "SIMULACION (--dry-run)" if dry_run else "EJECUCION REAL"
        self.stdout.write("")
        self.stdout.write(f"Modo: {modo}")
        self.stdout.write(f"Total de clientes revisados: {resumen['total']}")
        self.stdout.write(f"Total de clientes modificados: {resumen['modificados']}")
        self.stdout.write(f"Total de clientes sin cambios: {resumen['sin_cambios']}")
        self.stdout.write(f"Total de errores: {resumen['errores']}")
