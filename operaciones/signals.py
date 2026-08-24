import logging
from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Operacion
from cuenta_gastos.models import CuentaGastos

logger = logging.getLogger(__name__)

@receiver(post_save, sender=Operacion)
def clonar_operacion_a_cuenta_gastos(sender, instance, created, **kwargs):
    """
    Señal defensiva que clona la tarjeta a la app Cuenta de Gastos cuando se 
    mueve a la columna correspondiente. Nunca interrumpe el flujo principal.
    """
    try:
        if instance.estado == Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
            
            existe_clon = CuentaGastos.objects.filter(operacion_origen=instance).exists()
            
            if not existe_clon:
                CuentaGastos.objects.create(
                    operacion_origen=instance,
                    titulo=instance.titulo,
                    descripcion=instance.descripcion,
                    cliente=instance.cliente,
                    estado=CuentaGastos.Estado.SOLICITUD_PAGO,
                    prioridad=instance.prioridad,
                    creado_por=instance.creado_por,
                    fecha_vencimiento=instance.fecha_vencimiento
                )
    
    except Exception as e:
        logger.error(
            f"[CRÍTICO] Fallo silencioso al clonar Operacion ID {instance.id} a Cuenta de Gastos. "
            f"El guardado de operaciones continuó intacto. Error: {str(e)}",
            exc_info=True
        )
