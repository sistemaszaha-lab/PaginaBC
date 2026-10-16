from django import template
from decimal import Decimal
from django.core.exceptions import ObjectDoesNotExist
from solicitudes.permissions import rol_de_usuario, ROL_ADMIN, ROL_SOLO_LECTURA

register = template.Library()

@register.filter
def dinero(valor):
    try:
        return f"{Decimal(str(valor or 0)):,.2f}"
    except Exception:
        return "0.00"

@register.filter
def etiqueta_rol(user):
    return {ROL_ADMIN: "Administrador", ROL_SOLO_LECTURA: "Solo lectura"}.get(rol_de_usuario(user), "Ejecutivo")


@register.filter
def primer_nombre(user):
    if not user:
        return ""
    first_name = (getattr(user, "first_name", "") or "").strip()
    if first_name:
        return first_name.split()[0]
    return (getattr(user, "username", "") or "").strip()


@register.filter
def segundo_nombre(user):
    if not user:
        return ""
    try:
        perfil = user.perfil
    except ObjectDoesNotExist:
        perfil = None
    except Exception:
        perfil = None
    return (getattr(perfil, "segundo_nombre", "") or "").strip() if perfil else ""


@register.filter
def nombre_completo(user):
    if not user:
        return ""
    partes = []
    primer = (getattr(user, "first_name", "") or "").strip()
    if primer:
        partes.append(primer)

    try:
        perfil = user.perfil
    except ObjectDoesNotExist:
        perfil = None
    except Exception:
        perfil = None
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
