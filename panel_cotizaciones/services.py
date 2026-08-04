from __future__ import annotations

from django.db import transaction

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
