from functools import wraps

from django.core.exceptions import PermissionDenied


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            # Dejar que login_required maneje no autenticados.
            raise PermissionDenied

        # Garantías: acceso completo para Administrador y Ejecutivo.
        # En este sistema, "Ejecutivo" corresponde a usuarios autenticados que no son superuser.
        rol = "admin" if request.user.is_superuser else "ejecutivo"
        if rol not in {"admin", "ejecutivo"}:
            raise PermissionDenied("No tienes permisos para acceder a este mÃ³dulo.")

        return view_func(request, *args, **kwargs)

    return _wrapped