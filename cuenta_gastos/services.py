"""Transferencias transaccionales entre Operaciones y Cuenta de Gastos.

Las rutas controladas llaman explícitamente al servicio después de
``save_m2m()``. Un ``Operacion.save()`` directo no inicia esta automatización;
ese código debe invocar este servicio dentro de la misma transacción.
"""

from django.db import IntegrityError, transaction

from operaciones.models import Operacion
from .models import CuentaGastos, CuentaGastosColumna


class CuentaGastosTransferError(ValueError):
    """Error controlado que impide dejar una Operación sin tarjeta espejo."""


def crear_cuenta_gastos_desde_operacion_si_corresponde(operacion, *, creado_por):
    """Crea una tarjeta espejo una sola vez y copia los asignados definitivos."""
    if operacion.estado != Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
        return None, False

    with transaction.atomic():
        operacion_bloqueada = (
            Operacion.objects.select_for_update(of=("self",))
            .select_related("cliente")
            .get(pk=operacion.pk)
        )
        if operacion_bloqueada.estado != Operacion.Estado.SOLICITUD_CUENTA_GASTOS:
            return None, False

        columna = (
            CuentaGastosColumna.objects.select_for_update()
            .filter(
                codigo=CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS,
                activa=True,
            )
            .only("id", "codigo")
            .first()
        )
        if columna is None:
            raise CuentaGastosTransferError(
                "No existe una columna activa de Cuenta de Gastos con código "
                "SOLICITUD_CUENTA_GASTOS."
            )

        cuenta_existente = (
            CuentaGastos.objects.select_for_update()
            .filter(operacion_origen_id=operacion_bloqueada.pk)
            .first()
        )
        if cuenta_existente is not None:
            return cuenta_existente, False

        try:
            # Savepoint para poder consultar el conflicto sin dejar rota la
            # transacción exterior.
            with transaction.atomic():
                cuenta = CuentaGastos.objects.create(
                    operacion_origen=operacion_bloqueada,
                    titulo=operacion_bloqueada.titulo,
                    descripcion=operacion_bloqueada.descripcion,
                    cliente=operacion_bloqueada.cliente,
                    prioridad=operacion_bloqueada.prioridad,
                    fecha_vencimiento=operacion_bloqueada.fecha_vencimiento,
                    creado_por=creado_por,
                    estado=columna.codigo,
                    columna=columna,
                )
        except IntegrityError:
            cuenta = CuentaGastos.objects.filter(
                operacion_origen_id=operacion_bloqueada.pk
            ).first()
            if cuenta is None:
                raise
            return cuenta, False

        cuenta.asignados.set(operacion_bloqueada.asignados.all())
        return cuenta, True


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
        agencia_aduanal=cuenta_original.agencia_aduanal,
    )
    nueva_cuenta.asignados.set(cuenta_original.asignados.all())
    nueva_cuenta.etiquetas.set(cuenta_original.etiquetas.all())
    nueva_cuenta.opciones.set(cuenta_original.opciones.all())
    return nueva_cuenta
