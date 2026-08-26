"""
Signal que duplica automáticamente una Operacion hacia CuentaGastos
cuando su estado cambia a SOLICITUD_CUENTA_GASTOS.

La lógica de creación y anti-duplicación vive en:
    cuenta_gastos.services.crear_cuenta_gastos_desde_operacion_si_corresponde

Este signal actúa como hook de respaldo para cualquier save() directo
sobre Operacion (p. ej. edición de campos sin pasar por la vista mover).
La vista `mover_operacion` también llama al servicio directamente dentro
de su transacción atómica, por lo que ambos mecanismos son idempotentes
y seguros de convivir.
"""
import logging

from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import Operacion

logger = logging.getLogger(__name__)


@receiver(post_save, sender=Operacion)
def duplicar_a_cuenta_gastos_si_corresponde(sender, instance, **kwargs):
    """
    Dispara la creación idempotente de una CuentaGastos cuando la
    Operacion está en columna SOLICITUD_CUENTA_GASTOS.

    Mapeo de campos (Operacion → CuentaGastos):
        titulo           → titulo
        descripcion      → descripcion
        cliente          → cliente
        prioridad        → prioridad
        fecha_vencimiento→ fecha_vencimiento
        creado_por       → creado_por
        asignados (M2M)  → asignados (M2M)
        pk               → operacion_origen (FK de trazabilidad)

    Campos de CuentaGastos SIN equivalente en Operacion (quedan
    en su valor por defecto / vacíos – el equipo los completará a mano):
        etiquetas, opciones, archivos, enlaces, comentarios
    Columna destino fija: CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS
    (código "SOLICITUD_CUENTA_GASTOS", visible en CuentaGastos como
    "Solicitud de cuenta de agencia aduanal").
    """
    # Importación diferida para evitar importaciones circulares al arrancar.
    from cuenta_gastos.services import crear_cuenta_gastos_desde_operacion_si_corresponde

    if instance.estado != Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
        return

    try:
        crear_cuenta_gastos_desde_operacion_si_corresponde(
            instance,
            creado_por=instance.creado_por,
        )
    except Exception:
        # Registrar el error pero nunca interrumpir el flujo principal.
        logger.exception(
            "Error al duplicar Operacion id=%s a CuentaGastos.", instance.pk
        )