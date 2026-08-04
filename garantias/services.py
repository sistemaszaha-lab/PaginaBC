from __future__ import annotations

from django.db import transaction

from .models import Garantia, GarantiaColumna


@transaction.atomic
def copiar_garantia_a_columna(
    garantia_original: Garantia,
    columna_destino: GarantiaColumna,
    usuario,
) -> Garantia:
    nueva_garantia = Garantia.objects.create(
        titulo=garantia_original.titulo,
        descripcion=garantia_original.descripcion,
        cliente=garantia_original.cliente,
        prioridad=garantia_original.prioridad,
        estado=columna_destino.codigo,
        columna=columna_destino,
        fecha_vencimiento=garantia_original.fecha_vencimiento,
        creado_por=usuario,
    )
    nueva_garantia.asignados.set(garantia_original.asignados.all())
    nueva_garantia.etiquetas.set(garantia_original.etiquetas.all())
    return nueva_garantia
