"""Transferencias transaccionales entre Operaciones y Cuenta de Gastos.

Las rutas controladas llaman explícitamente al servicio después de
``save_m2m()``. Un ``Operacion.save()`` directo no inicia esta automatización;
ese código debe invocar este servicio dentro de la misma transacción.
"""

import logging
import time

from django.db import IntegrityError, OperationalError, connection, transaction

from operaciones.models import Operacion
from .models import (
    CuentaGastos,
    CuentaGastosColumna,
    CuentaGastosEtiqueta,
    CuentaGastosOpcion,
)

logger = logging.getLogger(__name__)


class CuentaGastosTransferError(ValueError):
    """Error controlado que impide dejar una Operación sin tarjeta espejo."""


class CuentaGastosFleteTransferError(ValueError):
    """Error de configuración que impide crear una copia Flete ambigua."""


class CuentaGastosAutomationError(ValueError):
    """Error de configuración para automatizaciones Cuenta de Gastos."""


FACTURA_FLETES_1 = "FACTURA_FLETES_1"
VOBO_ANGIE = "VOBO_ANGIE"
SOLICITUDES_GEO_1 = "SOLICITUDES_GEO_1"


def _columna_activa_por_codigo(modelo, codigo, modulo, error_class):
    columna = modelo.objects.select_for_update().filter(codigo=codigo, activa=True).first()
    if columna is None:
        mensaje = (
            f"Automatización detenida: no existe una columna activa con código "
            f"'{codigo}' en {modulo}."
        )
        logger.error(mensaje)
        raise error_class(mensaje)
    return columna


def _clonar_cuenta_gastos(
    origen, columna_destino, usuario, *, operacion_flete=None, vobo_angie=None
):
    """Núcleo compartido de creación y relaciones para tarjetas copiadas."""
    cuenta = CuentaGastos.objects.create(
        operacion_flete_origen=operacion_flete,
        vobo_angie_origen=vobo_angie,
        titulo=origen.titulo,
        descripcion=origen.descripcion,
        cliente=origen.cliente,
        prioridad=origen.prioridad,
        fecha_vencimiento=origen.fecha_vencimiento,
        agencia_aduanal=getattr(origen, "agencia_aduanal", ""),
        creado_por=usuario,
        estado=columna_destino.codigo,
        columna=columna_destino,
    )
    cuenta.asignados.set(origen.asignados.all())
    for etiqueta in origen.etiquetas.all():
        etiqueta_cuenta, _ = CuentaGastosEtiqueta.objects.get_or_create(
            nombre=etiqueta.nombre,
            defaults={"color": etiqueta.color},
        )
        cuenta.etiquetas.add(etiqueta_cuenta)
    for opcion in origen.opciones.all():
        opcion_cuenta, _ = CuentaGastosOpcion.objects.get_or_create(
            nombre=opcion.nombre,
        )
        cuenta.opciones.add(opcion_cuenta)
    crear_copia_vobo_angie_si_corresponde(cuenta, creado_por=usuario)
    return cuenta


def _crear_copia_flete_desde_operacion(operacion, *, creado_por):
    from operaciones.models import OperacionColumna

    with transaction.atomic():
        origen = (
            Operacion.objects.select_for_update(of=("self",))
            .select_related("cliente", "columna")
            .get(pk=operacion.pk)
        )
        if origen.columna is None or origen.columna.codigo != FACTURA_FLETES_1:
            return None, False
        columna_origen = _columna_activa_por_codigo(
            OperacionColumna,
            FACTURA_FLETES_1,
            "Operaciones",
            CuentaGastosFleteTransferError,
        )
        if origen.columna_id != columna_origen.pk:
            return None, False

        columna_destino = _columna_activa_por_codigo(
            CuentaGastosColumna,
            FACTURA_FLETES_1,
            "Cuenta de Gastos",
            CuentaGastosFleteTransferError,
        )
        existente = CuentaGastos.objects.filter(
            operacion_flete_origen_id=origen.pk
        ).first()
        if existente is not None:
            return existente, False

        try:
            with transaction.atomic():
                cuenta = _clonar_cuenta_gastos(
                    origen,
                    columna_destino,
                    creado_por,
                    operacion_flete=origen,
                )
        except IntegrityError:
            cuenta = CuentaGastos.objects.filter(
                operacion_flete_origen_id=origen.pk
            ).first()
            if cuenta is None:
                raise
            return cuenta, False

        return cuenta, True


def crear_copia_flete_desde_operacion(operacion, *, creado_por):
    """Crea/reutiliza la tarjeta independiente de Cuenta de Gastos para Flete."""
    for intento in range(5):
        try:
            return _crear_copia_flete_desde_operacion(
                operacion, creado_por=creado_por
            )
        except OperationalError as exc:
            # SQLite no implementa SELECT FOR UPDATE. Reintentar sus bloqueos
            # transitorios deja que la restricción OneToOne resuelva la carrera.
            if (
                connection.vendor != "sqlite"
                or "locked" not in str(exc).casefold()
                or intento == 4
            ):
                raise
            time.sleep(0.025 * (intento + 1))


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
    return _clonar_cuenta_gastos(cuenta_original, columna_destino, usuario)


def _crear_copia_vobo_angie(cuenta_gastos, *, creado_por):
    with transaction.atomic():
        origen = (
            CuentaGastos.objects.select_for_update(of=("self",))
            .select_related("columna")
            .get(pk=cuenta_gastos.pk)
        )
        if (
            origen.columna is None
            or origen.columna.codigo != VOBO_ANGIE
        ):
            return None, False
        columna_origen = _columna_activa_por_codigo(
            CuentaGastosColumna,
            VOBO_ANGIE,
            "Cuenta de Gastos",
            CuentaGastosAutomationError,
        )
        if origen.columna_id != columna_origen.pk:
            return None, False

        columna_destino = _columna_activa_por_codigo(
            CuentaGastosColumna,
            SOLICITUDES_GEO_1,
            "Cuenta de Gastos",
            CuentaGastosAutomationError,
        )
        existente = CuentaGastos.objects.filter(vobo_angie_origen_id=origen.pk).first()
        if existente is not None:
            return existente, False

        try:
            with transaction.atomic():
                copia = _clonar_cuenta_gastos(
                    origen,
                    columna_destino,
                    creado_por,
                    vobo_angie=origen,
                )
        except IntegrityError:
            copia = CuentaGastos.objects.filter(
                vobo_angie_origen_id=origen.pk
            ).first()
            if copia is None:
                raise
            return copia, False
        return copia, True


def crear_copia_vobo_angie_si_corresponde(cuenta_gastos, *, creado_por):
    """Duplica una tarjeta en VoBo Angie una sola vez hacia SOLICITUDES_GEO_1."""
    for intento in range(5):
        try:
            return _crear_copia_vobo_angie(cuenta_gastos, creado_por=creado_por)
        except OperationalError as exc:
            if (
                connection.vendor != "sqlite"
                or "locked" not in str(exc).casefold()
                or intento == 4
            ):
                raise
            time.sleep(0.025 * (intento + 1))
