from django import template

register = template.Library()


@register.filter
def primer_nombre(user):
    if not user:
        return ""
    first_name = (getattr(user, "first_name", "") or "").strip()
    if first_name:
        return first_name.split()[0]
    return (getattr(user, "username", "") or "").strip()


@register.filter
def nombre_completo(user):
    if not user:
        return ""
    partes = []
    primer = (getattr(user, "first_name", "") or "").strip()
    if primer:
        partes.append(primer)

    perfil = getattr(user, "perfil", None)
    if perfil:
        segundo = (getattr(perfil, "segundo_nombre", "") or "").strip()
        if segundo:
            partes.append(segundo)

    apellidos = (getattr(user, "last_name", "") or "").strip()
    if apellidos:
        partes.append(apellidos)

    if partes:
        return " ".join(partes)
    return (getattr(user, "username", "") or "").strip()

