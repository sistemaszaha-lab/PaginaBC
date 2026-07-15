from __future__ import annotations

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
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
    PanelCotizacionInlineAsignadosForm,
    PanelCotizacionInlineClienteForm,
    PanelCotizacionInlineCreateForm,
    PanelCotizacionInlinePrioridadForm,
    PanelCotizacionInlineTituloForm,
    PanelCotizacionInlineVencimientoForm,
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

INLINE_FIELD_FORMS = {
    "titulo": PanelCotizacionInlineTituloForm,
    "prioridad": PanelCotizacionInlinePrioridadForm,
    "fecha_vencimiento": PanelCotizacionInlineVencimientoForm,
    "cliente": PanelCotizacionInlineClienteForm,
    "asignados": PanelCotizacionInlineAsignadosForm,
}


def _safe_next_url(request: HttpRequest):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _get_usuarios_filter(request: HttpRequest):
    raw_ids = [
        value.strip()
        for value in request.GET.getlist("usuario")
        if (value or "").strip()
    ]
    if not raw_ids:
        single_value = (request.GET.get("usuario") or "").strip()
        if single_value:
            raw_ids = [single_value]
    if not raw_ids:
        return []
    try:
        ids = [int(value) for value in raw_ids]
    except Exception:
        return []
    return list(User.objects.filter(pk__in=ids).order_by("first_name", "id"))


def _board_queryset(usuarios):
    qs = (
        PanelCotizacion.objects.all()
        .select_related("creado_por")
        .prefetch_related("asignados")
        .annotate(comentarios_count=Count("comentarios"))
    )
    if usuarios:
        qs = qs.filter(asignados__in=usuarios).distinct()
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


def _guardar_adjuntos_enlaces(
    request: HttpRequest,
    cotizacion: PanelCotizacion,
    enlace_form: PanelCotizacionEnlaceForm,
) -> None:
    for archivo in request.FILES.getlist("archivos"):
        PanelCotizacionArchivo.objects.create(
            cotizacion=cotizacion,
            archivo=archivo,
            subido_por=request.user,
        )

    titulo = (enlace_form.cleaned_data.get("titulo") or "").strip()
    url = (enlace_form.cleaned_data.get("url") or "").strip()
    if titulo and url:
        PanelCotizacionEnlace.objects.create(
            cotizacion=cotizacion,
            titulo=titulo,
            url=url,
            creado_por=request.user,
        )


def _column_count(estado: str) -> int:
    return PanelCotizacion.objects.filter(estado=estado).count()


def _crear_panel_desde_form(*, form, creado_por, estado: str):
    obj: PanelCotizacion = form.save(commit=False)
    obj.creado_por = creado_por
    obj.estado = estado
    obj.save()
    form.save_m2m()
    return obj


def _render_inline_field(
    request: HttpRequest, obj: PanelCotizacion, field_name: str
) -> str:
    templates = {
        "titulo": "panel_cotizaciones/_inline_field_titulo.html",
        "prioridad": "panel_cotizaciones/_inline_field_prioridad.html",
        "fecha_vencimiento": "panel_cotizaciones/_inline_field_vencimiento.html",
        "cliente": "panel_cotizaciones/_inline_field_cliente.html",
        "asignados": "panel_cotizaciones/_inline_field_asignados.html",
    }
    return render_to_string(templates[field_name], {"c": obj}, request=request)


def _get_cotizacion_detalle(pk: int) -> PanelCotizacion:
    return get_object_or_404(
        PanelCotizacion.objects.prefetch_related(
            "asignados", "comentarios__creado_por", "archivos", "enlaces"
        ),
        pk=pk,
    )


def _render_archivos_section(
    request: HttpRequest, obj: PanelCotizacion, form=None
) -> str:
    return render_to_string(
        "panel_cotizaciones/_detalle_archivos_section.html",
        {
            "c": obj,
            "archivos_form": form or PanelCotizacionArchivosForm(),
        },
        request=request,
    )


def _render_enlaces_section(
    request: HttpRequest, obj: PanelCotizacion, form=None
) -> str:
    return render_to_string(
        "panel_cotizaciones/_detalle_enlaces_section.html",
        {
            "c": obj,
            "enlace_form": form or PanelCotizacionEnlaceForm(),
        },
        request=request,
    )


def _can_manage_attachment(request: HttpRequest, obj: PanelCotizacion) -> bool:
    return request.user.is_authenticated


def _preservar_vacios_cotizacion(form, objeto):
    """
    Restaura valores existentes cuando un guardado parcial envia un campo vacio.
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
@require_GET
def panel_cotizaciones(request: HttpRequest) -> HttpResponse:
    usuarios = _get_usuarios_filter(request)
    qs = list(_board_queryset(usuarios))
    inline_fake_c = PanelCotizacion(pk="__PK__")
    context = {
        "current": "panel_cotizaciones",
        "usuario_filter_form": PanelCotizacionUserFilterForm(
            initial={"usuario": [usuario.pk for usuario in usuarios]}
        ),
        "columnas_kanban": _columnas_kanban(qs),
        "inline_form": PanelCotizacionInlineCreateForm(),
        "inline_fake_c": inline_fake_c,
        "inline_titulo_form": PanelCotizacionInlineTituloForm(),
        "inline_prioridad_form": PanelCotizacionInlinePrioridadForm(),
        "inline_vencimiento_form": PanelCotizacionInlineVencimientoForm(),
        "inline_cliente_form": PanelCotizacionInlineClienteForm(),
        "inline_asignados_form": PanelCotizacionInlineAsignadosForm(),
        "estado_update_url": reverse("panel_cotizaciones:estado_update"),
    }
    return render(request, "panel_cotizaciones/panel.html", context)


@login_required
@require_GET
def tablero_partial(request: HttpRequest) -> HttpResponse:
    usuarios = _get_usuarios_filter(request)
    qs = list(_board_queryset(usuarios))
    return render(
        request,
        "panel_cotizaciones/_tablero.html",
        {
            "columnas_kanban": _columnas_kanban(qs),
            "inline_form": PanelCotizacionInlineCreateForm(),
        },
    )


@login_required
def crear_panel_cotizacion(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(request)
    if request.method == "POST":
        form = PanelCotizacionCreateForm(request.POST, request.FILES)
        archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
        enlace_form = PanelCotizacionEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            obj = _crear_panel_desde_form(
                form=form,
                creado_por=request.user,
                estado=PanelCotizacion.Estado.REQUERIMIENTO,
            )
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
        {
            "form": form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
            "next_url": next_url,
        },
    )


@login_required
@require_POST
def crear_inline(request: HttpRequest) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    estado = (request.POST.get("estado") or "").strip()
    if estado not in PanelCotizacion.Estado.values:
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Estado invalido."]}}, status=400
        )

    form = PanelCotizacionInlineCreateForm(request.POST)
    if not form.is_valid():
        form_html = render_to_string(
            "panel_cotizaciones/_inline_create_form.html",
            {"form": form, "estado": estado},
            request=request,
        )
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": form_html,
            },
            status=400,
        )

    obj = _crear_panel_desde_form(form=form, creado_por=request.user, estado=estado)
    obj = (
        PanelCotizacion.objects.filter(pk=obj.pk)
        .select_related("creado_por")
        .prefetch_related("asignados")
        .annotate(comentarios_count=Count("comentarios"))
        .get()
    )
    card_html = render_to_string("panel_cotizaciones/_card.html", {"c": obj}, request=request)
    return JsonResponse(
        {
            "ok": True,
            "html": card_html,
            "id": obj.pk,
            "estado": obj.estado,
            "column_count": _column_count(obj.estado),
        }
    )


@login_required
@require_POST
def inline_update(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    field_name = (request.POST.get("field") or "").strip()
    form_class = INLINE_FIELD_FORMS.get(field_name)
    if form_class is None:
        return JsonResponse(
            {"ok": False, "errors": {"field": ["Campo no permitido."]}},
            status=400,
        )

    obj = get_object_or_404(
        PanelCotizacion.objects.prefetch_related("asignados"), pk=pk
    )
    form = form_class(request.POST, instance=obj)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": form.errors.get_json_data(escape_html=True)},
            status=400,
        )

    if field_name == "asignados":
        obj.asignados.set(form.cleaned_data.get("asignados"))
    else:
        obj = form.save()

    obj = (
        PanelCotizacion.objects.filter(pk=obj.pk)
        .select_related("creado_por")
        .prefetch_related("asignados")
        .annotate(comentarios_count=Count("comentarios"))
        .get()
    )
    return JsonResponse(
        {
            "ok": True,
            "field": field_name,
            "html": _render_inline_field(request, obj, field_name),
        }
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
    return JsonResponse(
        {
            "status": "ok",
            "estado": obj.estado,
            "estado_display": obj.get_estado_display(),
        }
    )


@login_required
@require_GET
def detalle_modal(request: HttpRequest, pk: int) -> HttpResponse:
    obj = _get_cotizacion_detalle(pk)
    form = PanelCotizacionUpdateForm(instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    archivos_form = PanelCotizacionArchivosForm()
    enlace_form = PanelCotizacionEnlaceForm()
    return render(
        request,
        "panel_cotizaciones/_detalle_drawer.html"
        if request.GET.get("layout") == "drawer"
        else "panel_cotizaciones/_detalle_modal.html",
        {
            "c": obj,
            "form": form,
            "comentario_form": comentario_form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
        },
    )


@login_required
@require_POST
def detalle_modal_update(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk)
    layout = (request.POST.get("layout") or "modal").strip()
    template_name = (
        "panel_cotizaciones/_detalle_drawer.html"
        if layout == "drawer"
        else "panel_cotizaciones/_detalle_modal.html"
    )
    form = PanelCotizacionUpdateForm(request.POST, request.FILES, instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
    enlace_form = PanelCotizacionEnlaceForm(request.POST)
    if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
        _preservar_vacios_cotizacion(form, obj)

        saved_obj = form.save(commit=False)
        saved_obj.save()

        if "asignados" in request.POST:
            valores = form.cleaned_data.get("asignados")
            if valores is not None:
                saved_obj.asignados.set(valores)

        _guardar_adjuntos_enlaces(request, saved_obj, enlace_form)

        saved_obj = _get_cotizacion_detalle(pk)
        html = render_to_string(
            template_name,
            {
                "c": saved_obj,
                "form": PanelCotizacionUpdateForm(instance=saved_obj),
                "comentario_form": comentario_form,
                "archivos_form": PanelCotizacionArchivosForm(),
                "enlace_form": PanelCotizacionEnlaceForm(),
                "layout": layout,
            },
            request=request,
        )
        card_html = render_to_string(
            "panel_cotizaciones/_card.html", {"c": saved_obj}, request=request
        )
        return JsonResponse(
            {"status": "ok", "html": html, "card_html": card_html, "id": saved_obj.pk}
        )
    html = render_to_string(
        template_name,
        {
            "c": obj,
            "form": form,
            "comentario_form": comentario_form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
            "layout": layout,
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
        return JsonResponse(
            {
                "status": "error",
                "errors": form.errors.get_json_data(escape_html=True),
            },
            status=400,
        )
    comentario: PanelCotizacionComentario = form.save(commit=False)
    comentario.cotizacion = obj
    comentario.creado_por = request.user
    comentario.save()
    html = render_to_string(
        "panel_cotizaciones/_comentario_item.html",
        {"com": comentario},
        request=request,
    )
    return JsonResponse(
        {
            "status": "ok",
            "html": html,
            "comentarios_count": PanelCotizacionComentario.objects.filter(
                cotizacion=obj
            ).count(),
        }
    )


@login_required
@require_POST
def archivo_agregar(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    form = PanelCotizacionArchivosForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_archivos_section(request, obj, form=form),
            },
            status=400,
        )

    for archivo in request.FILES.getlist("archivos"):
        PanelCotizacionArchivo.objects.create(
            cotizacion=obj,
            archivo=archivo,
            subido_por=request.user,
        )
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_archivos_section(request, obj)})


@login_required
@require_POST
def archivo_eliminar(request: HttpRequest, pk: int, archivo_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    obj = _get_cotizacion_detalle(pk)
    if not _can_manage_attachment(request, obj):
        raise PermissionDenied("No tienes permisos para eliminar archivos.")
    archivo = get_object_or_404(PanelCotizacionArchivo, pk=archivo_id, cotizacion=obj)
    archivo.delete()
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_archivos_section(request, obj)})


@login_required
@require_POST
def enlace_agregar(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    form = PanelCotizacionEnlaceForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_enlaces_section(request, obj, form=form),
            },
            status=400,
        )

    titulo = (form.cleaned_data.get("titulo") or "").strip()
    url = (form.cleaned_data.get("url") or "").strip()
    if not titulo and not url:
        return JsonResponse(
            {
                "ok": False,
                "errors": {"url": [{"message": "Debes capturar un enlace valido."}]},
                "html": _render_enlaces_section(request, obj, form=form),
            },
            status=400,
        )

    PanelCotizacionEnlace.objects.create(
        cotizacion=obj,
        titulo=titulo,
        url=url,
        creado_por=request.user,
    )
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_enlaces_section(request, obj)})


@login_required
@require_POST
def enlace_eliminar(request: HttpRequest, pk: int, enlace_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    obj = _get_cotizacion_detalle(pk)
    if not _can_manage_attachment(request, obj):
        raise PermissionDenied("No tienes permisos para eliminar enlaces.")
    enlace = get_object_or_404(PanelCotizacionEnlace, pk=enlace_id, cotizacion=obj)
    enlace.delete()
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_enlaces_section(request, obj)})


@login_required
@require_POST
def eliminar_panel_cotizacion(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk)
    obj.delete()
    return JsonResponse({"status": "ok", "id": pk})
