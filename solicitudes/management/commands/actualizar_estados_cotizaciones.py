from django.core.management.base import BaseCommand

from solicitudes.services import actualizar_estados_cotizaciones


class Command(BaseCommand):
    help = (
        "Marca como 'Fuera de plazo' las cotizaciones pendientes cuya fecha "
        "de envio sea anterior a la fecha local actual."
    )

    def handle(self, *args, **options):
        resultado = actualizar_estados_cotizaciones()
        self.stdout.write(
            f"Cotizaciones pendientes examinadas: {resultado.examinados}"
        )
        self.stdout.write(
            "Cotizaciones que necesitaban actualizacion: "
            f"{resultado.necesitaban_actualizacion}"
        )
        self.stdout.write(
            f"Cotizaciones actualizadas: {resultado.actualizados}"
        )
        if resultado.actualizados:
            self.stdout.write(
                self.style.SUCCESS("Actualizacion de estados completada.")
            )
        else:
            self.stdout.write(
                self.style.SUCCESS("No habia estados pendientes de actualizacion.")
            )
