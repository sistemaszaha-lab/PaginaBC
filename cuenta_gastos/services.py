"""Conversión idempotente de Operaciones hacia Cuenta de gastos."""

from django.db import IntegrityError, transaction

from operaciones.models import Operacion
from .models import CuentaGastos, CuentaGastosColumna


def crear_cuenta_gastos_desde_operacion_si_corresponde(operacion, *, creado_por):
    if operacion.estado != Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
        return None, False
    columna = CuentaGastosColumna.objects.filter(
        codigo=CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS
    ).only("id", "codigo").first()
    defaults = {
        "titulo": operacion.titulo, "descripcion": operacion.descripcion,
        "cliente": operacion.cliente, "prioridad": operacion.prioridad,
        "fecha_vencimiento": operacion.fecha_vencimiento,
        "creado_por": creado_por,
        "estado": (
            columna.codigo
            if columna is not None
            else CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS
        ),
        "columna": columna,
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


@transaction.atomic
def copiar_cuenta_gastos_a_columna(
    cuenta_original: CuentaGastos,
    columna_destino: CuentaGastosColumna,
    usuario,
) -> CuentaGastos:
    nueva_cuenta = CuentaGastos.objects.create(
        titulo=cuenta_original.titulo,
        descripcion=cuenta_original.descripcion,
        cliente=cuenta_original.cliente,
        prioridad=cuenta_original.prioridad,
        estado=columna_destino.codigo,
        columna=columna_destino,
        creado_por=usuario,
        fecha_vencimiento=cuenta_original.fecha_vencimiento,
    )
    nueva_cuenta.asignados.set(cuenta_original.asignados.all())
    nueva_cuenta.etiquetas.set(cuenta_original.etiquetas.all())
    nueva_cuenta.opciones.set(cuenta_original.opciones.all())
    return nueva_cuenta
