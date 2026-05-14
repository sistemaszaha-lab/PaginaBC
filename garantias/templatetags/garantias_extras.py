from django import template


register = template.Library()


@register.filter
def iniciales_nombre(value):
    nombre = (value or "").strip()
    if not nombre:
        return ""
    partes = [parte for parte in nombre.split() if parte]
    if len(partes) >= 2:
        return f"{partes[0][0]}{partes[1][0]}".upper()
    return nombre[:2].upper()
