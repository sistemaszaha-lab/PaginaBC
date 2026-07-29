from django import template

register = template.Library()

@register.filter
def get_estado_choices(obj):
    """
    Devuelve las opciones (choices) del campo 'estado' de un modelo.
    Útil para iterar sobre los estados de Garantía o PanelCotizacion en la vista.
    """
    try:
        return obj._meta.get_field('estado').choices
    except Exception:
        return []
