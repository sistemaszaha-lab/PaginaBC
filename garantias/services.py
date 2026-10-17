from __future__ import annotations

import logging

from django.db import IntegrityError, transaction

from clientes.models import Cliente, normalizar_texto_cliente

from .models import (
    Garantia,
    GarantiaArchivo,
    GarantiaColumna,
    GarantiaComentario,
    GarantiaEnlace,
    GarantiaEtiqueta,
)
from cuenta_gastos.models import CuentaGastos, CuentaGastosColumna

logger = logging.getLogger(__name__)


@transaction.atomic
def enviar_operacion_a_garantias(operacion, *, creado_por):
    """Create the single Guarantee mirror for an operation, idempotently."""
    from operaciones.models import Operacion

    operacion = (
        Operacion.objects.select_for_update()
        .select_related("cliente")
        .prefetch_related("asignados", "etiquetas", "comentarios", "enlaces", "archivos")
        .get(pk=operacion.pk)
    )
    if operacion.estado != Operacion.Estado.EXPEDIENTE_CG:
        raise ValueError("La operacion debe estar en Expediente CG.")

    existente = Garantia.objects.select_for_update().filter(
        operacion_origen=operacion,
    ).first()
    if existente is not None:
        return existente, False

    columna = GarantiaColumna.objects.filter(
        codigo=Garantia.Estado.SOLICITUD_NAVIERA,
        activa=True,
    ).first()
    if columna is None:
        raise ValueError("No existe una columna activa con codigo SOLICITUD_NAVIERA.")

    try:
        with transaction.atomic():
            garantia = Garantia.objects.create(
                titulo=operacion.titulo,
                descripcion=operacion.descripcion,
                cliente=operacion.cliente,
                estado=columna.codigo,
                columna=columna,
                prioridad=operacion.prioridad,
                creado_por=creado_por,
                operacion_origen=operacion,
            )
    except IntegrityError:
        garantia = Garantia.objects.get(operacion_origen=operacion)
        return garantia, False

    garantia.asignados.set(operacion.asignados.all())
    garantia.etiquetas.set([
        GarantiaEtiqueta.objects.get_or_create(
            nombre=etiqueta.nombre,
            defaults={"color": etiqueta.color},
        )[0]
        for etiqueta in operacion.etiquetas.all()
    ])
    for comentario in operacion.comentarios.all():
        GarantiaComentario.objects.create(
            garantia=garantia,
            usuario=comentario.usuario,
            comentario=comentario.comentario,
            fecha=comentario.fecha,
        )
    for enlace in operacion.enlaces.all():
        GarantiaEnlace.objects.create(
            garantia=garantia,
            titulo=enlace.titulo,
            url=enlace.url,
            creado_por=enlace.creado_por,
            fecha=enlace.fecha,
        )
    for archivo in operacion.archivos.all():
        GarantiaArchivo.objects.create(
            garantia=garantia,
            archivo=archivo.archivo.name,
            subido_por=archivo.subido_por,
            fecha=archivo.fecha,
        )
    return garantia, True

@transaction.atomic
def enviar_garantia_a_cuenta_gastos(garantia, *, creado_por):
    garantia = Garantia.objects.select_for_update().get(pk=garantia.pk)
    if garantia.estado != Garantia.Estado.DEVOLUCION_CLIENTE:
        raise ValueError("La garantía debe estar en Devolución a cliente.")
    columna = CuentaGastosColumna.objects.get(codigo="DEVOLUCION_A_GARANTIAS", activa=True)
    cuenta, creada = CuentaGastos.objects.get_or_create(garantia_origen=garantia, defaults={
        "titulo": garantia.titulo, "descripcion": garantia.descripcion, "cliente": garantia.cliente,
        "prioridad": garantia.prioridad if garantia.prioridad in dict(CuentaGastos.Prioridad.choices) else CuentaGastos.Prioridad.MEDIA,
        "fecha_vencimiento": garantia.fecha_vencimiento, "estado": columna.codigo, "columna": columna,
        "creado_por": creado_por,
    })
    if creada:
        cuenta.asignados.set(garantia.asignados.all())
    return cuenta, creada


def obtener_datos_garantia_desde_referencia(referencia):
    cliente = None
    if referencia.cliente:
        cliente = Cliente.objects.filter(
            nombre__iexact=normalizar_texto_cliente(referencia.cliente)
        ).order_by("id").first()
    descripcion = "\n".join(
        parte for parte in (
            f"Referencia: {referencia.referencia}",
            f"Servicio: {referencia.servicio_legible}" if referencia.servicio else "",
            f"Medio: {referencia.get_medio_operacion_display()}" if referencia.medio_operacion else "",
            f"Agencia aduanal: {referencia.agencia_aduanal}" if referencia.agencia_aduanal else "",
        ) if parte
    )
    datos = {
        "titulo": f"Referencia {referencia.referencia}",
        "descripcion": descripcion,
    }
    if cliente:
        datos["cliente"] = cliente
    return datos


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
