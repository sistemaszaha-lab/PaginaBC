import csv
from datetime import datetime
from pathlib import Path

from django.core.management.base import BaseCommand

from solicitudes.models import Solicitud


class Command(BaseCommand):
    help = "Importa solicitudes desde un CSV por año (ej: 2021)"

    def add_arguments(self, parser):
        parser.add_argument("anio", type=int, help="Año del archivo CSV (ej: 2021)")

    def handle(self, *args, **options):
        anio = options["anio"]
        archivo = Path(f"Solicitudes {anio}.csv")

        if not archivo.exists():
            self.stdout.write(self.style.ERROR(f"No se encontró el archivo {archivo}"))
            return

        contador = 0

        with archivo.open(encoding="latin-1") as file:
            reader = csv.reader(file, delimiter=";")

            for row in reader:
                if len(row) < 10:
                    continue

                sg = row[0].strip()
                if not sg or sg.upper() == "SG" or "Indicar" in sg:
                    continue

                cliente = row[1].strip()

                try:
                    fecha_recepcion = datetime.strptime(row[2].strip(), "%d-%m-%y").date()
                except ValueError:
                    continue

                tipo = row[4].strip()

                aerea = bool(row[7].strip())
                maritima = bool(row[8].strip())
                terrestre = bool(row[9].strip())

                Solicitud.objects.update_or_create(
                    sg=sg,
                    anio=anio,
                    defaults={
                        "cliente": cliente,
                        "fecha_recepcion": fecha_recepcion,
                        "tipo": tipo,
                        "aerea": aerea,
                        "maritima": maritima,
                        "terrestre": terrestre,
                        "estado_aereo": "Pendiente" if aerea else None,
                        "estado_maritimo": "Pendiente" if maritima else None,
                        "estado_terrestre": "Pendiente" if terrestre else None,
                    },
                )
                contador += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Importación completada: {contador} solicitudes para el año {anio}"
            )
        )
