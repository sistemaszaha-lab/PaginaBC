from django.apps import AppConfig


class CuentaGastosConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cuenta_gastos"
    def ready(self):
        from . import signals  # noqa: F401
