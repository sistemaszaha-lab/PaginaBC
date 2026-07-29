"""Conversión idempotente de Operaciones hacia Cuenta de gastos."""

from django.db import IntegrityError, transaction

from operaciones.models import Operacion
from .models import CuentaGastos


def crear_cuenta_gastos_desde_operacion_si_corresponde(operacion, *, creado_por):
    if operacion.estado != Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
        return None, False
    defaults = {
        "titulo": operacion.titulo, "descripcion": operacion.descripcion,
        "cliente": operacion.cliente, "prioridad": operacion.prioridad,
        "fecha_vencimiento": operacion.fecha_vencimiento, "creado_por": creado_por,
        "estado": CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS,
    }
    try:
        with transaction.atomic():
            cuenta, creada = CuentaGastos.objects.get_or_create(
                operacion_origen=operacion, defaults=defaults
            )
            if creada:
                cuenta.asignados.set(operacion.asignados.all())
            return cuenta, creada
    except IntegrityError:
        return CuentaGastos.objects.get(operacion_origen=operacion), False
