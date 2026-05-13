from functools import wraps

from django.core.exceptions import PermissionDenied


def admin_required(view_func):
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not getattr(request, "user", None) or not request.user.is_authenticated:
            # Dejar que login_required maneje no autenticados.
            raise PermissionDenied
        if not request.user.is_superuser:
            raise PermissionDenied("No tienes permisos para acceder a este módulo.")
        return view_func(request, *args, **kwargs)

    return _wrapped
