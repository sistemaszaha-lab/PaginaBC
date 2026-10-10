from django.http import JsonResponse, HttpResponseForbidden

from .permissions import es_solo_lectura


SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
SAFE_POST_PATHS = {"/login/", "/logout/"}


class SoloLecturaWriteProtectionMiddleware:
    """Reject unsafe HTTP methods before any application view runs.

    Phase 2 deliberately protects only authenticated read-only users. GET,
    HEAD and OPTIONS remain available for navigation and consultation. The
    only POST exceptions are the authentication endpoints; all business POST,
    PUT, PATCH and DELETE requests are writes and are rejected here.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            getattr(request, "user", None)
            and es_solo_lectura(request.user)
            and request.method not in SAFE_METHODS
            and request.path not in SAFE_POST_PATHS
        ):
            message = "El usuario tiene permisos de solo lectura y no puede modificar información."
            accepts = request.headers.get("Accept", "")
            is_json = request.path.startswith("/api/") or "application/json" in accepts or request.headers.get("X-Requested-With") == "XMLHttpRequest"
            if is_json:
                return JsonResponse({"ok": False, "error": "solo_lectura", "message": message}, status=403)
            return HttpResponseForbidden(message)
        return self.get_response(request)
