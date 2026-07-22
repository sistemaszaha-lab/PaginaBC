"""Conversiones explícitas desde Solicitudes hacia Referencias."""

from .forms import ReferenciaForm


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
