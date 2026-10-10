"""Centralized application role helpers."""
from django.contrib.auth.models import Group

SOLO_LECTURA_GROUP = "SOLO_LECTURA"
ROL_ADMIN = "admin"
# Keep the existing form value for backwards compatibility.
ROL_EJECUTIVO = "usuario"
ROL_SOLO_LECTURA = "solo_lectura"

def es_admin(user):
    return bool(user and getattr(user, "is_authenticated", False) and user.is_superuser)

def es_solo_lectura(user):
    return bool(user and getattr(user, "is_authenticated", False) and not user.is_superuser and user.groups.filter(name=SOLO_LECTURA_GROUP).exists())

def es_ejecutivo(user):
    return bool(user and getattr(user, "is_authenticated", False) and not user.is_superuser and not es_solo_lectura(user))

def puede_escribir(user):
    return es_admin(user) or es_ejecutivo(user)

def puede_ver_todo(user):
    """Whether querysets should use administrator-level visibility."""
    return es_admin(user) or es_solo_lectura(user)

def rol_de_usuario(user):
    if es_admin(user): return ROL_ADMIN
    if es_solo_lectura(user): return ROL_SOLO_LECTURA
    if es_ejecutivo(user): return ROL_EJECUTIVO
    return ""

def grupo_solo_lectura():
    return Group.objects.get_or_create(name=SOLO_LECTURA_GROUP)[0]

def aplicar_rol(user, rol):
    if rol == ROL_ADMIN:
        user.is_superuser, user.is_staff = True, True
        user.save(update_fields=["is_superuser", "is_staff"])
        user.groups.remove(grupo_solo_lectura())
    elif rol == ROL_SOLO_LECTURA:
        user.is_superuser, user.is_staff = False, False
        user.save(update_fields=["is_superuser", "is_staff"])
        user.groups.clear()
        user.user_permissions.clear()
        user.groups.add(grupo_solo_lectura())
    elif rol == ROL_EJECUTIVO:
        user.is_superuser, user.is_staff = False, False
        user.save(update_fields=["is_superuser", "is_staff"])
        user.groups.remove(grupo_solo_lectura())
    else:
        raise ValueError(f"Rol no soportado: {rol}")
