from django import template

register = template.Library()


@register.filter
def get_item(dictionary, key):
    """Obtiene un valor de un diccionario en templates."""
    if isinstance(dictionary, dict):
        return dictionary.get(key, [])
    return []
