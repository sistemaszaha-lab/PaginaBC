"""Conversiones explícitas desde Referencias hacia Operaciones."""

from django.db import transaction

from clientes.models import Cliente, normalizar_texto_cliente
from cuenta_gastos.services import crear_cuenta_gastos_desde_operacion_si_corresponde

from .models import Operacion


def obtener_initial_operacion_desde_referencia(referencia):
    """Prellena solo datos compatibles con el formulario normal de Operaciones."""
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
    initial = {
        "titulo": f"Referencia {referencia.referencia}",
        "descripcion": descripcion,
        "estado": Operacion.Estado.COORDINAR_PICKUP,
    }
    if cliente:
        initial["cliente"] = cliente.pk
    if referencia.ejecutivo_id:
        initial["asignados"] = [referencia.ejecutivo_id]
    return initial


def copiar_operacion_a_columna(operacion_original, columna_destino, usuario):
    with transaction.atomic():
        nueva_operacion = Operacion.objects.create(
            titulo=operacion_original.titulo,
            descripcion=operacion_original.descripcion,
            cliente=operacion_original.cliente,
            estado=columna_destino.codigo,
            columna=columna_destino,
            prioridad=operacion_original.prioridad,
            creado_por=usuario,
            etd=operacion_original.etd,
        )
        nueva_operacion.asignados.set(operacion_original.asignados.all())
        nueva_operacion.etiquetas.set(operacion_original.etiquetas.all())
        nueva_operacion.opciones.set(operacion_original.opciones.all())
        crear_cuenta_gastos_desde_operacion_si_corresponde(
            nueva_operacion,
            creado_por=usuario,
        )
        return nueva_operacion
