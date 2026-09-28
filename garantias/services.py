from __future__ import annotations

from django.db import transaction

from clientes.models import Cliente, normalizar_texto_cliente

from .models import Garantia, GarantiaColumna
from cuenta_gastos.models import CuentaGastos, CuentaGastosColumna

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
