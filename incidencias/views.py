import json

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .forms import IncidenciaForm
from .models import Incidencia


def _panel_incidencias_queryset():
    return Incidencia.objects.select_related("responsable").order_by("-fecha_creacion")


def _build_incidencia_row(inc: Incidencia) -> dict:
    return {
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


def _build_resumen_incidencias(queryset) -> dict:
    hoy = timezone.localdate()
    return queryset.aggregate(
        pendientes=Count("id", filter=Q(estado=Incidencia.Estado.ABIERTO)),
        en_proceso=Count("id", filter=Q(estado=Incidencia.Estado.PROCESO)),
        resueltas=Count("id", filter=Q(estado=Incidencia.Estado.CERRADO)),
        vencidas=Count(
            "id",
            filter=Q(fecha_limite__lt=hoy) & ~Q(estado=Incidencia.Estado.CERRADO),
        ),
    )


@login_required
def panel_incidencias(request):
    incidencias = _panel_incidencias_queryset()
    resumen = _build_resumen_incidencias(incidencias)

    table_data = [_build_incidencia_row(inc) for inc in incidencias]

    return render(
        request,
        "incidencias/panel_incidencias.html",
        {
            "current": "panel_incidencias",
            "incidencias_json": json.dumps(table_data, ensure_ascii=False),
            "incidencia_form": IncidenciaForm(),
            "resumen": resumen,
            "q": (request.GET.get("q") or "").strip(),
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
            "row": _build_incidencia_row(inc),
            "resumen": _build_resumen_incidencias(_panel_incidencias_queryset()),
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
            "row": _build_incidencia_row(inc),
            "resumen": _build_resumen_incidencias(_panel_incidencias_queryset()),
        }
    )


@login_required
@require_POST
def eliminar_incidencia(request, pk: int):
    inc = get_object_or_404(Incidencia, pk=pk)
    inc.delete()
    return JsonResponse(
        {
            "ok": True,
            "resumen": _build_resumen_incidencias(_panel_incidencias_queryset()),
        }
    )

# Create your views here.
