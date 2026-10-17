from django.apps import AppConfig


class OperacionesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "operaciones"
    verbose_name = "Operaciones"

    def ready(self):
        # La transferencia se invoca explícitamente después de save_m2m().
        return None
