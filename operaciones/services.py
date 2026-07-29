"""Conversiones explícitas desde Referencias hacia Operaciones."""

from clientes.models import Cliente, normalizar_texto_cliente

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
