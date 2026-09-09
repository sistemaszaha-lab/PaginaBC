from __future__ import annotations

from django.db import IntegrityError, transaction

from solicitudes.forms import ReferenciaForm
from solicitudes.models import Referencia
from solicitudes.services import obtener_initial_referencia_desde_panel_cotizacion

from .models import PanelCotizacion, PanelCotizacionColumna


@transaction.atomic
def copiar_cotizacion_a_columna(
    cotizacion_original: PanelCotizacion,
    columna_destino: PanelCotizacionColumna,
    usuario,
) -> PanelCotizacion:
    nueva_cotizacion = PanelCotizacion.objects.create(
        titulo=cotizacion_original.titulo,
        descripcion=cotizacion_original.descripcion,
        cliente=cotizacion_original.cliente,
        prioridad=cotizacion_original.prioridad,
        estado=columna_destino.codigo,
        columna=columna_destino,
        fecha_vencimiento=cotizacion_original.fecha_vencimiento,
        creado_por=usuario,
    )
    nueva_cotizacion.asignados.set(cotizacion_original.asignados.all())
    nueva_cotizacion.etiquetas.set(cotizacion_original.etiquetas.all())
    return nueva_cotizacion


def crear_referencia_desde_panel_cotizacion(cotizacion: PanelCotizacion):
    existente = getattr(cotizacion, "referencia_generada", None)
    if existente:
        return existente, False

    initial = obtener_initial_referencia_desde_panel_cotizacion(cotizacion)
    fecha = initial.get("fecha") or ""
    form = ReferenciaForm(
        data={
            "ejecutivo": initial.get("ejecutivo") or "",
            "cliente": initial.get("cliente") or "",
            "servicio": initial.get("servicio") or "importacion",
            "medio_operacion": initial.get("medio_operacion") or "",
            "agencia_aduanal": initial.get("agencia_aduanal") or "",
            "fecha": fecha.isoformat() if hasattr(fecha, "isoformat") else fecha,
        }
    )
    if not form.is_valid():
        raise ValueError(form.errors.as_json())

    referencia: Referencia = form.save(commit=False)
    referencia.panel_cotizacion_origen = cotizacion
    if cotizacion.solicitud_origen_id:
        referencia.solicitud_origen = cotizacion.solicitud_origen
    try:
        with transaction.atomic():
            form.save()
    except IntegrityError:
        existente = Referencia.objects.filter(panel_cotizacion_origen=cotizacion).first()
        if existente:
            return existente, False
        raise
    return referencia, True
