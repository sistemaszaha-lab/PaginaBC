from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.contrib.auth import get_user_model
from django.db.models import Count
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_POST

from .forms import (
    PanelCotizacionArchivosForm,
    PanelCotizacionComentarioForm,
    PanelCotizacionCreateForm,
    PanelCotizacionEnlaceForm,
    PanelCotizacionUpdateForm,
    PanelCotizacionUserFilterForm,
)
from .models import (
    PanelCotizacion,
    PanelCotizacionArchivo,
    PanelCotizacionComentario,
    PanelCotizacionEnlace,
)

User = get_user_model()


def _safe_next_url(request: HttpRequest):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _get_usuario_filter(request: HttpRequest):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id:
        return None
    try:
        return User.objects.get(pk=int(usuario_id))
    except Exception:
        return None


def _board_queryset(usuario):
    qs = (
        PanelCotizacion.objects.all()
        .select_related("creado_por")
        .prefetch_related("asignados")
        .annotate(comentarios_count=Count("comentarios"))
    )
    if usuario:
        qs = qs.filter(asignados=usuario)
    return qs


def _columnas_kanban(qs):
    estados = [
        (PanelCotizacion.Estado.REQUERIMIENTO, "Requerimiento"),
        (PanelCotizacion.Estado.EN_PROGRESO, "En progreso"),
        (PanelCotizacion.Estado.ENVIADA, "Enviada"),
    ]
    columnas = []
    for estado, label in estados:
        columnas.append((estado, label, [c for c in qs if c.estado == estado]))
    return columnas


def _guardar_adjuntos_enlaces(request: HttpRequest, cotizacion: PanelCotizacion, enlace_form: PanelCotizacionEnlaceForm) -> None:
    for archivo in request.FILES.getlist("archivos"):
        PanelCotizacionArchivo.objects.create(
            cotizacion=cotizacion,
            archivo=archivo,
            subido_por=request.user,
        )

    if (enlace_form.cleaned_data.get("titulo") or "").strip() and (enlace_form.cleaned_data.get("url") or "").strip():
        enlace = PanelCotizacionEnlace(
            cotizacion=cotizacion,
            titulo=enlace_form.cleaned_data.get("titulo", "").strip(),
            url=enlace_form.cleaned_data.get("url", "").strip(),
            creado_por=request.user,
        )
        enlace.save()


@login_required
@require_GET
def panel_cotizaciones(request: HttpRequest) -> HttpResponse:
    usuario = _get_usuario_filter(request)
    qs = list(_board_queryset(usuario))
    context = {
        "current": "panel_cotizaciones",
        "usuario_filter_form": PanelCotizacionUserFilterForm(
            initial={"usuario": usuario.pk if usuario else None}
        ),
        "columnas_kanban": _columnas_kanban(qs),
        "estado_update_url": reverse("panel_cotizaciones:estado_update"),
    }
    return render(request, "panel_cotizaciones/panel.html", context)


@login_required
@require_GET
def tablero_partial(request: HttpRequest) -> HttpResponse:
    usuario = _get_usuario_filter(request)
    qs = list(_board_queryset(usuario))
    return render(
        request,
        "panel_cotizaciones/_tablero.html",
        {"columnas_kanban": _columnas_kanban(qs)},
    )


@login_required
def crear_panel_cotizacion(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(request)
    if request.method == "POST":
        form = PanelCotizacionCreateForm(request.POST, request.FILES)
        archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
        enlace_form = PanelCotizacionEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            obj: PanelCotizacion = form.save(commit=False)
            obj.creado_por = request.user
            obj.estado = PanelCotizacion.Estado.REQUERIMIENTO
            obj.save()
            form.save_m2m()
            _guardar_adjuntos_enlaces(request, obj, enlace_form)
            if next_url:
                return redirect(next_url)
            return redirect("panel_cotizaciones:panel_cotizaciones")
    else:
        form = PanelCotizacionCreateForm()
        archivos_form = PanelCotizacionArchivosForm()
        enlace_form = PanelCotizacionEnlaceForm()
    return render(
        request,
        "panel_cotizaciones/crear.html",
        {"form": form, "archivos_form": archivos_form, "enlace_form": enlace_form, "next_url": next_url},
    )


@login_required
@require_POST
def estado_update(request: HttpRequest) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    cotizacion_id = (request.POST.get("cotizacion_id") or "").strip()
    nuevo_estado = (request.POST.get("nuevo_estado") or "").strip()
    if not cotizacion_id or nuevo_estado not in PanelCotizacion.Estado.values:
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=cotizacion_id)
    obj.estado = nuevo_estado
    obj.save(update_fields=["estado"])
    return JsonResponse({"status": "ok"})


@login_required
@require_GET
def detalle_modal(request: HttpRequest, pk: int) -> HttpResponse:
    obj = get_object_or_404(
        PanelCotizacion.objects.prefetch_related("asignados", "comentarios__creado_por", "archivos", "enlaces"),
        pk=pk,
    )
    form = PanelCotizacionUpdateForm(instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    archivos_form = PanelCotizacionArchivosForm()
    enlace_form = PanelCotizacionEnlaceForm()
    return render(
        request,
        "panel_cotizaciones/_detalle_modal.html",
        {
            "c": obj,
            "form": form,
            "comentario_form": comentario_form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
        },
    )


def _preservar_vacios_cotizacion(form, objeto):
    """
    Antes de guardar, si un campo no-m2m llega vacío/None en el POST
    y el objeto ya tenía un valor, restaura el valor original.
    """
    m2m_names = {f.name for f in objeto._meta.many_to_many}
    for campo in list(form.fields.keys()):
        if campo in m2m_names:
            continue
        valor = form.cleaned_data.get(campo)
        if valor in (None, ""):
            actual = getattr(objeto, campo, None)
            if actual not in (None, ""):
                setattr(form.instance, campo, actual)


@login_required
@require_POST
def detalle_modal_update(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk)
    form = PanelCotizacionUpdateForm(request.POST, request.FILES, instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
    enlace_form = PanelCotizacionEnlaceForm(request.POST)
    if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
        # Preservar campos no-m2m que llegan vacíos
        _preservar_vacios_cotizacion(form, obj)

        saved_obj = form.save(commit=False)
        saved_obj.save()

        # M2M: solo actualizar asignados si fue enviado explícitamente en el POST
        if "asignados" in request.POST:
            valores = form.cleaned_data.get("asignados")
            if valores is not None:
                saved_obj.asignados.set(valores)

        _guardar_adjuntos_enlaces(request, saved_obj, enlace_form)

        # Refrescar con prefetch para el modal y la tarjeta
        saved_obj = get_object_or_404(
            PanelCotizacion.objects.prefetch_related("asignados", "comentarios__creado_por", "archivos", "enlaces"),
            pk=pk,
        )
        html = render_to_string(
            "panel_cotizaciones/_detalle_modal.html",
            {
                "c": saved_obj,
                "form": PanelCotizacionUpdateForm(instance=saved_obj),
                "comentario_form": comentario_form,
                "archivos_form": PanelCotizacionArchivosForm(),
                "enlace_form": PanelCotizacionEnlaceForm(),
            },
            request=request,
        )
        card_html = render_to_string(
            "panel_cotizaciones/_card.html", {"c": saved_obj}, request=request
        )
        return JsonResponse({"status": "ok", "html": html, "card_html": card_html, "id": saved_obj.pk})
    html = render_to_string(
        "panel_cotizaciones/_detalle_modal.html",
        {
            "c": obj,
            "form": form,
            "comentario_form": comentario_form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
        },
        request=request,
    )
    return JsonResponse({"status": "error", "html": html})


@login_required
@require_POST
def comentario_create(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk)
    form = PanelCotizacionComentarioForm(request.POST)
    if not form.is_valid():
        return JsonResponse({"status": "error"}, status=400)
    comentario: PanelCotizacionComentario = form.save(commit=False)
    comentario.cotizacion = obj
    comentario.creado_por = request.user
    comentario.save()
    return JsonResponse(
        {
            "status": "ok",
            "comentario": {
                "texto": comentario.texto,
                "usuario": (request.user.first_name or "").strip() or str(request.user.pk),
                "fecha": comentario.fecha_creacion.isoformat(),
            },
        }
    )


@login_required
@require_POST
def eliminar_panel_cotizacion(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk)
    obj.delete()
    return JsonResponse({"status": "ok", "id": pk})
