from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import AgenciaAduanal, CuentaGastos

@receiver(post_save, sender=CuentaGastos)
def registrar_agencia_aduanal(sender, instance, **kwargs):
    nombre = " ".join((instance.agencia_aduanal or "").split())
    if nombre:
        AgenciaAduanal.objects.get_or_create(clave_normalizada=nombre.casefold(), defaults={"nombre": nombre})
