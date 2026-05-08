import json

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.views.decorators.http import require_POST

from .forms import IncidenciaForm
from .models import Incidencia


@login_required
def panel_incidencias(request):
    incidencias = (
        Incidencia.objects.select_related("responsable")
        .all()
        .order_by("-fecha_creacion")
    )

    table_data = [
        {
            "id": inc.id,
            "incidencia": inc.codigo,
            "titulo": inc.titulo,
            "responsable": getattr(inc.responsable, "get_full_name", lambda: "")()
            or getattr(inc.responsable, "username", ""),
            "responsable_id": inc.responsable_id,
            "estado": inc.estado,
            "prioridad": inc.prioridad,
            "fecha": inc.fecha_creacion.strftime("%Y-%m-%d %H:%M"),
            "descripcion": inc.descripcion or "",
            "fecha_limite": inc.fecha_limite.isoformat() if inc.fecha_limite else "",
        }
        for inc in incidencias
    ]

    return render(
        request,
        "incidencias/panel_incidencias.html",
        {
            "current": "panel_incidencias",
            "incidencias_json": json.dumps(table_data, ensure_ascii=False),
            "incidencia_form": IncidenciaForm(),
        },
    )


@login_required
@require_POST
def crear_incidencia(request):
    form = IncidenciaForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    inc = form.save()
    return JsonResponse(
        {
            "ok": True,
            "row": {
                "id": inc.id,
                "incidencia": inc.codigo,
                "titulo": inc.titulo,
                "responsable": getattr(inc.responsable, "get_full_name", lambda: "")()
                or getattr(inc.responsable, "username", ""),
                "responsable_id": inc.responsable_id,
                "estado": inc.estado,
                "prioridad": inc.prioridad,
                "fecha": inc.fecha_creacion.strftime("%Y-%m-%d %H:%M"),
                "descripcion": inc.descripcion or "",
                "fecha_limite": inc.fecha_limite.isoformat() if inc.fecha_limite else "",
            },
        }
    )


@login_required
@require_POST
def editar_incidencia(request, pk: int):
    inc = get_object_or_404(Incidencia, pk=pk)
    form = IncidenciaForm(request.POST, instance=inc)
    if not form.is_valid():
        return JsonResponse({"ok": False, "errors": form.errors}, status=400)

    inc = form.save()
    return JsonResponse(
        {
            "ok": True,
            "row": {
                "id": inc.id,
                "incidencia": inc.codigo,
                "titulo": inc.titulo,
                "responsable": getattr(inc.responsable, "get_full_name", lambda: "")()
                or getattr(inc.responsable, "username", ""),
                "responsable_id": inc.responsable_id,
                "estado": inc.estado,
                "prioridad": inc.prioridad,
                "fecha": inc.fecha_creacion.strftime("%Y-%m-%d %H:%M"),
                "descripcion": inc.descripcion or "",
                "fecha_limite": inc.fecha_limite.isoformat() if inc.fecha_limite else "",
            },
        }
    )


@login_required
@require_POST
def eliminar_incidencia(request, pk: int):
    inc = get_object_or_404(Incidencia, pk=pk)
    inc.delete()
    return JsonResponse({"ok": True})

# Create your views here.
