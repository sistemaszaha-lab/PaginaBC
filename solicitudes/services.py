"""Servicios de dominio de Solicitudes, Referencias y Cotizaciones."""

from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from .forms import ReferenciaForm
from .models import Cotizacion


@dataclass(frozen=True)
class ResultadoActualizacionCotizaciones:
    examinados: int
    necesitaban_actualizacion: int
    actualizados: int
    fecha_referencia: object


def estado_vigente_cotizacion(cotizacion, fecha_referencia=None):
    """Calcula el estado visible con la misma regla de persistencia programada."""
    fecha_referencia = fecha_referencia or timezone.localdate()
    if (
        cotizacion.estado == "Pendiente"
        and cotizacion.fecha_envio is not None
        and cotizacion.fecha_envio < fecha_referencia
    ):
        return "Fuera de plazo"
    return cotizacion.estado


def aplicar_estados_vigentes_cotizaciones(cotizaciones, fecha_referencia=None):
    """Actualiza solo las instancias en memoria para renderizar estados vigentes."""
    fecha_referencia = fecha_referencia or timezone.localdate()
    for cotizacion in cotizaciones:
        cotizacion.estado = estado_vigente_cotizacion(
            cotizacion,
            fecha_referencia=fecha_referencia,
        )
    return cotizaciones


def actualizar_estados_cotizaciones(fecha_referencia=None):
    """Persiste en bloque las cotizaciones pendientes que ya vencieron."""
    fecha_referencia = fecha_referencia or timezone.localdate()
    pendientes = Cotizacion.objects.filter(estado="Pendiente")
    por_actualizar = pendientes.filter(fecha_envio__lt=fecha_referencia)

    with transaction.atomic():
        examinados = pendientes.count()
        necesitaban_actualizacion = por_actualizar.count()
        actualizados = por_actualizar.update(estado="Fuera de plazo")

    return ResultadoActualizacionCotizaciones(
        examinados=examinados,
        necesitaban_actualizacion=necesitaban_actualizacion,
        actualizados=actualizados,
        fecha_referencia=fecha_referencia,
    )


def obtener_initial_referencia_desde_solicitud(solicitud):
    """Devuelve únicamente los campos que ambos módulos pueden compartir."""
    medio = next(
        (
            nombre
            for nombre in ("aerea", "maritima", "terrestre")
            if getattr(solicitud, nombre, False)
        ),
        "",
    )
    servicio = _servicio_desde_tipo(solicitud.tipo)
    initial = {
        "cliente": solicitud.cliente,
        "ejecutivo": solicitud.ejecutivo_id,
        "fecha": solicitud.fecha_recepcion,
        "medio_operacion": medio,
    }
    if servicio:
        initial["servicio"] = servicio
    return initial


def obtener_datos_panel_desde_solicitud(solicitud):
    medios = [
        etiqueta
        for campo, etiqueta in (
            ("aerea", "Aerea"),
            ("maritima", "Maritima"),
            ("terrestre", "Terrestre"),
        )
        if getattr(solicitud, campo, False)
    ]
    descripcion = "\n".join(
        parte
        for parte in (
            f"Solicitud: {solicitud.sg}",
            f"Tipo: {solicitud.tipo}" if solicitud.tipo else "",
            f"Medio: {', '.join(medios)}" if medios else "",
            f"Fecha de inicio: {solicitud.fecha_recepcion}" if solicitud.fecha_recepcion else "",
            f"Fecha de entrega: {solicitud.fecha_entrega}" if solicitud.fecha_entrega else "",
        )
        if parte
    )
    return {
        "titulo": solicitud.sg,
        "descripcion": descripcion,
        "cliente": solicitud.cliente,
        "fecha_vencimiento": solicitud.fecha_entrega,
        "asignados": [solicitud.ejecutivo_id] if solicitud.ejecutivo_id else [],
    }


def obtener_initial_referencia_desde_panel_cotizacion(cotizacion):
    solicitud = getattr(cotizacion, "solicitud_origen", None)
    if solicitud is not None:
        initial = obtener_initial_referencia_desde_solicitud(solicitud)
        if cotizacion.cliente:
            initial["cliente"] = cotizacion.cliente
        return initial

    asignado = cotizacion.asignados.order_by("id").first()
    initial = {
        "cliente": cotizacion.cliente,
        "ejecutivo": asignado.pk if asignado else cotizacion.creado_por_id,
        "fecha": timezone.localdate(),
    }
    servicio = _servicio_desde_tipo(f"{cotizacion.titulo} {cotizacion.descripcion}")
    if servicio:
        initial["servicio"] = servicio
    return initial


def _servicio_desde_tipo(tipo):
    texto = (tipo or "").lower()
    if "export" in texto:
        return "exportacion"
    if "consult" in texto:
        return "servicios_consultoria"
    if "transporte" in texto:
        return "servicios_transporte"
    if "import" in texto:
        return "importacion"
    return ""
