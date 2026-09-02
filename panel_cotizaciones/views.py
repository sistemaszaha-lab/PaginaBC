from __future__ import annotations
from django.views.decorators.csrf import ensure_csrf_cookie

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Max, Q, Window
from django.db.models.functions import RowNumber
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST
from solicitudes_app.trash import enviar_a_papelera

from .forms import (
    PanelCotizacionArchivosForm,
    PanelCotizacionComentarioForm,
    PanelCotizacionColumnaCreateForm,
    PanelCotizacionColumnaUpdateForm,
    PanelCotizacionCreateForm,
    PanelCotizacionElementoAccionForm,
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
    PanelCotizacionColumna,
    PanelCotizacionComentario,
    PanelCotizacionElementoAccion,
    PanelCotizacionEnlace,
    PanelCotizacionEtiqueta,
)
from .services import copiar_cotizacion_a_columna

User = get_user_model()

INLINE_FIELD_FORMS = {
    "titulo": PanelCotizacionInlineTituloForm,
    "prioridad": PanelCotizacionInlinePrioridadForm,
    "fecha_vencimiento": PanelCotizacionInlineVencimientoForm,
    "cliente": PanelCotizacionInlineClienteForm,
    "asignados": PanelCotizacionInlineAsignadosForm,
}

COLUMNAS_INICIALES = (
    (PanelCotizacion.Estado.REQUERIMIENTO, "Requerimiento"),
    (PanelCotizacion.Estado.EN_PROGRESO, "En progreso"),
    (PanelCotizacion.Estado.ENVIADA, "Enviada"),
)

PANEL_ORDERING = ("-fecha_creacion", "-id")


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


def _get_usuarios_filter_estricto(request: HttpRequest):
    raw_ids = [
        value.strip()
        for value in request.GET.getlist("usuario")
        if (value or "").strip()
    ]
    if not raw_ids:
        return [], None
    if any(not value.isdigit() or int(value) <= 0 for value in raw_ids):
        return [], JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    ids = list(dict.fromkeys(int(value) for value in raw_ids))
    usuarios = list(
        User.objects.filter(pk__in=ids).order_by("first_name", "id")
    )
    if len(usuarios) != len(ids):
        return [], JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    return usuarios, None


def _columnas_activas_queryset():
    return PanelCotizacionColumna.objects.filter(activa=True).order_by("orden", "id")


def _columnas_activas():
    return list(_columnas_activas_queryset())


def _primer_columna_activa():
    return _columnas_activas_queryset().first()


def _columnas_estado_choices():
    return [(columna.codigo, columna.nombre) for columna in _columnas_activas()]


def _buscar_columna_activa_por_codigo(codigo: str):
    return _columnas_activas_queryset().filter(codigo=codigo).first()


def _puede_operar_panel(user) -> bool:
    return bool(user.is_authenticated and user.is_active)


def _generar_codigo_columna(nombre: str) -> str:
    base = slugify(nombre).replace("-", "_").upper()
    if not base:
        base = "COLUMNA"
    if base[0].isdigit():
        base = f"COLUMNA_{base}"
    candidato = base
    indice = 2
    while PanelCotizacionColumna.objects.filter(codigo=candidato).exists():
        candidato = f"{base}_{indice}"
        indice += 1
    return candidato


def _siguiente_orden_columna() -> int:
    ultima = PanelCotizacionColumna.objects.order_by("-orden", "-id").first()
    return (ultima.orden + 1) if ultima is not None else 1


def _column_context(
    *,
    columna: PanelCotizacionColumna,
    items,
    count: int,
    loaded: int,
):
    return {
        "id": columna.pk,
        "columna_id": columna.pk,
        "codigo": columna.codigo,
        "estado": columna.codigo,
        "nombre": columna.nombre,
        "estado_texto": columna.nombre,
        "items": items,
        "count": count,
        "loaded": count,
        "has_more": False,
        "remaining": 0,
        "load_url": reverse(
            "panel_cotizaciones:tarjetas_columna",
            kwargs={"codigo": columna.codigo},
        ),
        "paste_url": reverse(
            "panel_cotizaciones:columna_pegar",
            kwargs={"columna_id": columna.pk},
        ),
    }


def _board_queryset(usuarios):
    codigos_activos = [codigo for codigo, _nombre in _columnas_estado_choices()]
    qs = (
        PanelCotizacion.objects.filter(
            estado__in=codigos_activos,
            eliminado_en__isnull=True,
        ).filter(
            Q(columna__activa=True) | Q(columna__isnull=True)
        )
        .select_related("columna", "creado_por")
        .prefetch_related("asignados", "etiquetas")
        .annotate(comentarios_count=Count("comentarios"))
    )
    if usuarios:
        qs = qs.filter(asignados__in=usuarios).distinct()
    return qs.order_by(*PANEL_ORDERING)


def _columnas_kanban(usuarios):
    columnas = _columnas_activas()
    objetos = list(
        _board_queryset(usuarios)
        .annotate(
            posicion_columna=Window(
                expression=RowNumber(),
                partition_by=[F("estado")],
                order_by=[
                    F("fecha_creacion").desc(),
                    F("id").desc(),
                ],
            ),
            total_columna=Window(
                expression=Count("id"),
                partition_by=[F("estado")],
            ),
        )
    )
    items_por_codigo = {columna.codigo: [] for columna in columnas}
    totales = {columna.codigo: 0 for columna in columnas}
    for obj in objetos:
        if obj.estado in items_por_codigo:
            items_por_codigo[obj.estado].append(obj)
            totales[obj.estado] = obj.total_columna

    return [
        _column_context(
            columna=columna,
            items=items_por_codigo[columna.codigo],
            count=totales[columna.codigo],
            loaded=len(items_por_codigo[columna.codigo]),
        )
        for columna in columnas
    ]


def _parse_loaded_ids(request: HttpRequest, offset: int):
    raw_ids = (request.GET.get("loaded") or "").strip()
    if not raw_ids:
        return [] if offset == 0 else None
    parts = raw_ids.split(",")
    if any(not value.isdigit() or int(value) <= 0 for value in parts):
        return None
    loaded_ids = list(dict.fromkeys(int(value) for value in parts))
    if len(loaded_ids) != len(parts) or len(loaded_ids) != offset:
        return None
    return loaded_ids


def _guardar_adjuntos_enlaces(
    *,
    request: HttpRequest,
    cotizacion: PanelCotizacion,
    archivos,
    enlaces,
) -> None:
    for archivo in archivos:
        PanelCotizacionArchivo.objects.create(
            cotizacion=cotizacion,
            archivo=archivo,
            subido_por=request.user,
        )

    for enlace in enlaces:
        PanelCotizacionEnlace.objects.create(
            cotizacion=cotizacion,
            titulo=enlace["titulo"],
            url=enlace["url"],
            creado_por=request.user,
        )


def _column_count(columna: PanelCotizacionColumna) -> int:
    return PanelCotizacion.objects.filter(
        estado=columna.codigo,
        eliminado_en__isnull=True,
    ).count()


def _crear_panel_desde_form(*, form, creado_por, columna: PanelCotizacionColumna):
    obj: PanelCotizacion = form.save(commit=False)
    obj.creado_por = creado_por
    obj.columna = columna
    obj.estado = columna.codigo
    obj.save()
    form.save_m2m()
    return obj


def _render_card_html(request: HttpRequest, obj: PanelCotizacion) -> str:
    return render_to_string(
        "panel_cotizaciones/_card.html",
        {"c": obj, "columnas_estado": _columnas_estado_choices()},
        request=request,
    )


def _get_cotizacion_para_copia(pk: int) -> PanelCotizacion:
    return get_object_or_404(
        PanelCotizacion.objects.filter(eliminado_en__isnull=True).select_related("columna", "creado_por")
        .prefetch_related("asignados", "etiquetas"),
        pk=pk,
    )


def _render_inline_create_form(
    request: HttpRequest,
    form: PanelCotizacionInlineCreateForm,
    columna: PanelCotizacionColumna,
) -> str:
    return render_to_string(
        "panel_cotizaciones/_inline_create_form.html",
        {
            "form": form,
            "estado": columna.codigo,
            "estado_texto": columna.nombre,
            "columna": columna,
        },
        request=request,
    )


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


def _render_inline_editor(
    request: HttpRequest,
    obj: PanelCotizacion,
    field_name: str,
    form=None,
) -> str:
    form = form or INLINE_FIELD_FORMS[field_name](instance=obj)
    return render_to_string(
        "panel_cotizaciones/_inline_editor_form.html",
        {
            "c": obj,
            "field_name": field_name,
            "bound_field": form[field_name],
        },
        request=request,
    )


def _get_cotizacion_detalle(pk: int) -> PanelCotizacion:
    return get_object_or_404(
        PanelCotizacion.objects.filter(eliminado_en__isnull=True).prefetch_related(
            "asignados",
            "etiquetas",
            "elementos_accion",
            "comentarios__creado_por",
            "archivos",
            "enlaces",
        ).select_related("columna"),
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


def _render_checklist_section(
    request: HttpRequest,
    obj: PanelCotizacion,
    *,
    form: PanelCotizacionElementoAccionForm | None = None,
    section_error: str = "",
) -> str:
    return render_to_string(
        "panel_cotizaciones/_detalle_checklist_section.html",
        {
            "c": obj,
            "checklist_form": form or PanelCotizacionElementoAccionForm(),
            "checklist_section_error": section_error,
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


def _normalizar_post_etiquetas_panel(post_data):
    raw_values = [
        value.strip()
        for value in post_data.getlist("etiquetas")
        if (value or "").strip()
    ]
    if not raw_values:
        return post_data, []

    normalized_ids = []
    errors = []

    for raw_value in raw_values:
        if raw_value.isdigit():
            etiqueta = PanelCotizacionEtiqueta.objects.filter(pk=int(raw_value)).only("pk").first()
            if etiqueta is None:
                errors.append("Selecciona una etiqueta valida.")
                continue
        else:
            if len(raw_value) > 100:
                errors.append("Cada etiqueta debe tener como maximo 100 caracteres.")
                continue
            etiqueta = (
                PanelCotizacionEtiqueta.objects.filter(nombre__iexact=raw_value)
                .only("pk", "nombre")
                .order_by("id")
                .first()
            )
            if etiqueta is None:
                etiqueta = PanelCotizacionEtiqueta.objects.create(
                    nombre=raw_value,
                    color="#3E9FA2",
                )
        normalized_ids.append(str(etiqueta.pk))

    if errors:
        return post_data, errors

    normalized_data = post_data.copy()
    normalized_data.setlist("etiquetas", list(dict.fromkeys(normalized_ids)))
    return normalized_data, []


@login_required
@require_GET
@ensure_csrf_cookie
def panel_cotizaciones(request: HttpRequest) -> HttpResponse:
    usuarios = _get_usuarios_filter(request)
    columnas_activas = _columnas_activas()
    context = {
        "current": "panel_cotizaciones",
        "usuario_filter_form": PanelCotizacionUserFilterForm(
            initial={"usuario": [usuario.pk for usuario in usuarios]}
        ),
        "columnas_kanban": _columnas_kanban(usuarios),
        "columnas_activas": columnas_activas,
        "columnas_estado": _columnas_estado_choices(),
        "columna_create_form": PanelCotizacionColumnaCreateForm(),
        "panel_config": {
            "estadoUpdateUrl": reverse("panel_cotizaciones:estado_update"),
            "boardUrl": reverse("panel_cotizaciones:tablero_partial"),
            "inlineCreateUrl": reverse("panel_cotizaciones:crear_inline"),
            "inlineFormUrl": reverse("panel_cotizaciones:formulario_inline"),
            "columnCreateUrl": reverse("panel_cotizaciones:columna_crear"),
            "columnReorderUrl": reverse("panel_cotizaciones:columna_reordenar"),
        },
    }
    return render(request, "panel_cotizaciones/panel.html", context)


@login_required
@require_GET
def tablero_partial(request: HttpRequest) -> HttpResponse:
    usuarios = _get_usuarios_filter(request)
    return render(
        request,
        "panel_cotizaciones/_tablero.html",
        {
            "columnas_kanban": _columnas_kanban(usuarios),
            "columnas_estado": _columnas_estado_choices(),
        },
    )


@login_required
@require_GET
def tarjetas_columna(request: HttpRequest, codigo: str) -> JsonResponse:
    columna_obj = _buscar_columna_activa_por_codigo(codigo)
    if columna_obj is None:
        return JsonResponse(
            {"ok": False, "error": "Estado no encontrado."},
            status=404,
        )

    raw_offset = (request.GET.get("offset") or "").strip()
    if not raw_offset.isdigit():
        return JsonResponse(
            {"ok": False, "error": "Offset invalido."},
            status=400,
        )
    offset = int(raw_offset)
    usuarios, error = _get_usuarios_filter_estricto(request)
    if error is not None:
        return error
    loaded_ids = _parse_loaded_ids(request, offset)
    if loaded_ids is None:
        return JsonResponse(
            {"ok": False, "error": "Tarjetas cargadas invalidas."},
            status=400,
        )

    columna = _board_queryset(usuarios).filter(estado=columna_obj.codigo)
    total = columna.count()
    recognized_loaded_ids = set(
        columna.filter(pk__in=loaded_ids).values_list("pk", flat=True)
    )
    stale_ids = [
        pk for pk in loaded_ids if pk not in recognized_loaded_ids
    ]
    siguientes = list(
        columna.exclude(pk__in=loaded_ids)
    )
    has_more = False
    objetos = siguientes
    columnas_estado = _columnas_estado_choices()
    html = "".join(
        render_to_string(
            "panel_cotizaciones/_tarjeta.html",
            {"c": obj, "columnas_estado": columnas_estado},
            request=request,
        )
        for obj in objetos
    )
    loaded = len(objetos)
    return JsonResponse(
        {
            "ok": True,
            "estado": columna_obj.codigo,
            "columna_id": columna_obj.pk,
            "columna_codigo": columna_obj.codigo,
            "html": html,
            "loaded": loaded,
            "next_offset": len(recognized_loaded_ids) + loaded,
            "has_more": has_more,
            "total": total,
            "stale_ids": stale_ids,
        }
    )


@login_required
@require_GET
def formulario_inline(request: HttpRequest) -> HttpResponse:
    columna = _primer_columna_activa()
    if columna is None:
        return HttpResponse("")
    return HttpResponse(
        _render_inline_create_form(
            request,
            PanelCotizacionInlineCreateForm(),
            columna,
        )
    )


@login_required
def crear_panel_cotizacion(request: HttpRequest) -> HttpResponse:
    next_url = _safe_next_url(request)
    columna_inicial = _primer_columna_activa()
    if columna_inicial is None:
        raise PermissionDenied("No hay columnas disponibles en el panel.")
    if request.method == "POST":
        form_data, etiquetas_errors = _normalizar_post_etiquetas_panel(request.POST)
        form = PanelCotizacionCreateForm(form_data, request.FILES)
        archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
        enlace_form = PanelCotizacionEnlaceForm(request.POST)
        if etiquetas_errors:
            form.add_error("etiquetas", etiquetas_errors)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            obj = _crear_panel_desde_form(
                form=form,
                creado_por=request.user,
                columna=columna_inicial,
            )
            titulo = (enlace_form.cleaned_data.get("titulo") or "").strip()
            url = (enlace_form.cleaned_data.get("url") or "").strip()
            _guardar_adjuntos_enlaces(
                request=request,
                cotizacion=obj,
                archivos=archivos_form.cleaned_data.get("archivos", []),
                enlaces=(
                    [{"titulo": titulo, "url": url}]
                    if titulo and url
                    else []
                ),
            )
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
@require_GET
def inline_editor(request: HttpRequest, pk: int) -> JsonResponse:
    field_name = (request.GET.get("field") or "").strip()
    if field_name not in INLINE_FIELD_FORMS:
        return JsonResponse(
            {"ok": False, "errors": {"field": ["Campo no permitido."]}},
            status=400,
        )

    obj = get_object_or_404(
        PanelCotizacion.objects.filter(eliminado_en__isnull=True).prefetch_related("asignados"),
        pk=pk,
    )
    return JsonResponse(
        {
            "ok": True,
            "id": obj.pk,
            "field": field_name,
            "html": _render_inline_editor(request, obj, field_name),
        }
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
    columna = _buscar_columna_activa_por_codigo(estado)
    if columna is None:
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Estado invalido."]}}, status=400
        )

    form_data, etiquetas_errors = _normalizar_post_etiquetas_panel(request.POST)
    form = PanelCotizacionInlineCreateForm(form_data, request.FILES)
    if etiquetas_errors:
        form.add_error("etiquetas", etiquetas_errors)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "message": "Revisa los campos indicados.",
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, columna),
            },
            status=400,
        )

    try:
        with transaction.atomic():
            obj = _crear_panel_desde_form(
                form=form,
                creado_por=request.user,
                columna=columna,
            )
            _guardar_adjuntos_enlaces(
                request=request,
                cotizacion=obj,
                archivos=form.cleaned_data.get("archivos", []),
                enlaces=form.cleaned_data.get("enlaces_payload", []),
            )
    except Exception:
        return JsonResponse(
            {
                "ok": False,
                "errors": {
                    "__all__": [
                        "Ocurrio un error inesperado al guardar la cotizacion."
                    ]
                },
            },
            status=500,
        )

    obj = (
        PanelCotizacion.objects.filter(pk=obj.pk, eliminado_en__isnull=True)
        .select_related("creado_por")
        .prefetch_related("asignados", "etiquetas")
        .annotate(comentarios_count=Count("comentarios"))
        .get()
    )
    return JsonResponse(
        {
            "ok": True,
            "message": "La cotizacion se creo correctamente.",
            "html": _render_card_html(request, obj),
            "card_html": _render_card_html(request, obj),
            "id": obj.pk,
            "estado": obj.estado,
            "column_count": _column_count(columna),
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
        },
        status=201,
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
        PanelCotizacion.objects.filter(eliminado_en__isnull=True).prefetch_related("asignados"), pk=pk
    )
    form = form_class(request.POST, instance=obj)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "id": obj.pk,
                "field": field_name,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_editor(
                    request,
                    obj,
                    field_name,
                    form=form,
                ),
            },
            status=400,
        )

    if field_name == "asignados":
        obj.asignados.set(form.cleaned_data.get("asignados"))
    else:
        obj = form.save()

    obj = (
        PanelCotizacion.objects.filter(pk=obj.pk, eliminado_en__isnull=True)
        .select_related("creado_por")
        .prefetch_related("asignados", "etiquetas")
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
def columna_crear(request: HttpRequest) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    form = PanelCotizacionColumnaCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": form.errors.get_json_data(escape_html=True)},
            status=400,
        )
    with transaction.atomic():
        columna = form.save(commit=False)
        columna.codigo = _generar_codigo_columna(columna.nombre)
        columna.orden = _siguiente_orden_columna()
        columna.creada_por = request.user
        columna.save()
    html = render_to_string(
        "panel_cotizaciones/_columna.html",
        {"columna": _column_context(columna=columna, items=[], count=0, loaded=0)},
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
            "html": html,
        },
        status=201,
    )


@login_required
@require_POST
def columna_editar(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    columna = get_object_or_404(PanelCotizacionColumna, pk=pk, activa=True)
    form = PanelCotizacionColumnaUpdateForm(request.POST, instance=columna)
    if not form.is_valid():
        return JsonResponse(
            {"ok": False, "errors": form.errors.get_json_data(escape_html=True)},
            status=400,
        )
    form.save()
    return JsonResponse(
        {
            "ok": True,
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
            "nombre": columna.nombre,
        }
    )


@login_required
@require_POST
def columna_reordenar(request: HttpRequest) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    raw_ids = request.POST.getlist("columnas[]") or request.POST.getlist("columnas")
    if not raw_ids:
        return JsonResponse({"ok": False, "error": "Debes enviar columnas."}, status=400)
    if any(not value.isdigit() or int(value) <= 0 for value in raw_ids):
        return JsonResponse({"ok": False, "error": "IDs invalidos."}, status=400)
    ids = [int(value) for value in raw_ids]
    if len(ids) != len(set(ids)):
        return JsonResponse({"ok": False, "error": "IDs duplicados."}, status=400)
    columnas = list(PanelCotizacionColumna.objects.filter(pk__in=ids, activa=True))
    if len(columnas) != len(ids):
        return JsonResponse({"ok": False, "error": "Columna no encontrada."}, status=400)
    with transaction.atomic():
        for orden, columna_id in enumerate(ids, start=1):
            PanelCotizacionColumna.objects.filter(pk=columna_id).update(orden=orden)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def columna_eliminar(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    columna = get_object_or_404(PanelCotizacionColumna, pk=pk, activa=True)
    activas = _columnas_activas()
    if len(activas) <= 1:
        return JsonResponse(
            {"ok": False, "error": "No puedes eliminar la ultima columna activa."},
            status=400,
        )

    destino_id = (request.POST.get("columna_destino_id") or "").strip()
    tarjetas_qs = PanelCotizacion.objects.filter(
        Q(columna=columna) | Q(columna__isnull=True, estado=columna.codigo),
        eliminado_en__isnull=True,
    )
    total_tarjetas = tarjetas_qs.count()
    if total_tarjetas > 0:
        if not destino_id.isdigit():
            return JsonResponse(
                {"ok": False, "error": "Debes seleccionar una columna destino."},
                status=400,
            )
        if int(destino_id) == columna.pk:
            return JsonResponse(
                {"ok": False, "error": "La columna destino debe ser distinta."},
                status=400,
            )
        destino = get_object_or_404(PanelCotizacionColumna, pk=int(destino_id), activa=True)
    else:
        destino = None

    with transaction.atomic():
        if destino is not None:
            tarjetas_qs.update(columna=destino, estado=destino.codigo)
        columna.activa = False
        columna.save(update_fields=["activa", "fecha_actualizacion"])
        for orden, columna_id in enumerate(
            PanelCotizacionColumna.objects.filter(activa=True)
            .order_by("orden", "id")
            .values_list("pk", flat=True),
            start=1,
        ):
            PanelCotizacionColumna.objects.filter(pk=columna_id).update(orden=orden)

    return JsonResponse(
        {
            "ok": True,
            "columna_id": pk,
            "movidas": total_tarjetas,
            "columna_destino_id": destino.pk if destino is not None else None,
        }
    )


@login_required
@require_POST
def columna_pegar(request: HttpRequest, columna_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    if not _puede_operar_panel(request.user):
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=403)

    raw_tarjeta_id = (request.POST.get("tarjeta_id") or "").strip()
    if not raw_tarjeta_id.isdigit() or int(raw_tarjeta_id) <= 0:
        return JsonResponse({"ok": False, "error": "Tarjeta invalida."}, status=400)

    columna_destino = get_object_or_404(
        PanelCotizacionColumna,
        pk=columna_id,
        activa=True,
    )
    cotizacion_original = _get_cotizacion_para_copia(int(raw_tarjeta_id))
    if not _puede_operar_panel(request.user):
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=403)

    nueva = copiar_cotizacion_a_columna(
        cotizacion_original=cotizacion_original,
        columna_destino=columna_destino,
        usuario=request.user,
    )
    nueva = (
        PanelCotizacion.objects.filter(pk=nueva.pk, eliminado_en__isnull=True)
        .select_related("columna", "creado_por")
        .prefetch_related("asignados", "etiquetas")
        .annotate(comentarios_count=Count("comentarios"))
        .get()
    )
    return JsonResponse(
        {
            "ok": True,
            "tarjeta_id": nueva.pk,
            "columna_id": columna_destino.pk,
            "html": _render_card_html(request, nueva),
            "estado": nueva.estado,
            "column_count": _column_count(columna_destino),
        },
        status=201,
    )


@login_required
@require_POST
def estado_update(request: HttpRequest) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    cotizacion_id = (request.POST.get("cotizacion_id") or "").strip()
    nuevo_estado = (request.POST.get("nuevo_estado") or "").strip()
    if not cotizacion_id:
        return JsonResponse({"status": "error"}, status=400)
    columna = _buscar_columna_activa_por_codigo(nuevo_estado)
    if columna is None:
        return JsonResponse(
            {"status": "error", "error": "Columna destino invalida."},
            status=400,
        )
    obj = get_object_or_404(PanelCotizacion, pk=cotizacion_id, eliminado_en__isnull=True)
    obj.columna = columna
    obj.estado = columna.codigo
    obj.save(update_fields=["columna", "estado"])
    return JsonResponse(
        {
            "status": "ok",
            "estado": obj.estado,
            "estado_display": columna.nombre,
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
        }
    )


@login_required
@require_GET
def detalle_modal(request: HttpRequest, pk: int) -> HttpResponse:
    obj = _get_cotizacion_detalle(pk)
    form = PanelCotizacionUpdateForm(instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    checklist_form = PanelCotizacionElementoAccionForm()
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
            "checklist_form": checklist_form,
            "archivos_form": archivos_form,
            "enlace_form": enlace_form,
        },
    )


@login_required
@require_POST
def detalle_modal_update(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse({"status": "error"}, status=400)
    obj = get_object_or_404(PanelCotizacion, pk=pk, eliminado_en__isnull=True)
    layout = (request.POST.get("layout") or "modal").strip()
    template_name = (
        "panel_cotizaciones/_detalle_drawer.html"
        if layout == "drawer"
        else "panel_cotizaciones/_detalle_modal.html"
    )
    form_data, etiquetas_errors = _normalizar_post_etiquetas_panel(request.POST)
    form = PanelCotizacionUpdateForm(form_data, request.FILES, instance=obj)
    comentario_form = PanelCotizacionComentarioForm()
    checklist_form = PanelCotizacionElementoAccionForm()
    archivos_form = PanelCotizacionArchivosForm(request.POST, request.FILES)
    enlace_form = PanelCotizacionEnlaceForm(request.POST)
    if etiquetas_errors:
        form.add_error("etiquetas", etiquetas_errors)
    if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
        _preservar_vacios_cotizacion(form, obj)

        with transaction.atomic():
            saved_obj = form.save(commit=False)
            saved_obj.save()

            if "asignados" in request.POST:
                valores = form.cleaned_data.get("asignados")
                if valores is not None:
                    saved_obj.asignados.set(valores)
            if "etiquetas" in request.POST:
                etiquetas = form.cleaned_data.get("etiquetas")
                if etiquetas is not None:
                    saved_obj.etiquetas.set(etiquetas)

            titulo = (enlace_form.cleaned_data.get("titulo") or "").strip()
            url = (enlace_form.cleaned_data.get("url") or "").strip()
            _guardar_adjuntos_enlaces(
                request=request,
                cotizacion=saved_obj,
                archivos=archivos_form.cleaned_data.get("archivos", []),
                enlaces=(
                    [{"titulo": titulo, "url": url}]
                    if titulo and url
                    else []
                ),
            )

        saved_obj = _get_cotizacion_detalle(pk)
        html = render_to_string(
            template_name,
            {
                "c": saved_obj,
                "form": PanelCotizacionUpdateForm(instance=saved_obj),
                "comentario_form": comentario_form,
                "checklist_form": PanelCotizacionElementoAccionForm(),
                "archivos_form": PanelCotizacionArchivosForm(),
                "enlace_form": PanelCotizacionEnlaceForm(),
                "layout": layout,
            },
            request=request,
        )
        return JsonResponse(
            {
                "status": "ok",
                "html": html,
                "card_html": _render_card_html(request, saved_obj),
                "id": saved_obj.pk,
            }
        )
    html = render_to_string(
        template_name,
        {
            "c": obj,
            "form": form,
            "comentario_form": comentario_form,
            "checklist_form": checklist_form,
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
    obj = get_object_or_404(PanelCotizacion, pk=pk, eliminado_en__isnull=True)
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
def checklist_item_create(request: HttpRequest, pk: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    form = PanelCotizacionElementoAccionForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_checklist_section(request, obj, form=form),
            },
            status=400,
        )

    max_orden = obj.elementos_accion.aggregate(max_orden=Max("orden")).get("max_orden")
    PanelCotizacionElementoAccion.objects.create(
        cotizacion=obj,
        texto=form.cleaned_data["texto"],
        orden=(max_orden or 0) + 1,
    )
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_checklist_section(request, obj)})


@login_required
@require_POST
def checklist_item_update(request: HttpRequest, pk: int, item_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    item = get_object_or_404(PanelCotizacionElementoAccion, pk=item_id, cotizacion=obj)
    form = PanelCotizacionElementoAccionForm(request.POST, instance=item)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_checklist_section(
                    request,
                    obj,
                    section_error="No se pudo guardar el elemento.",
                ),
            },
            status=400,
        )
    form.save()
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_checklist_section(request, obj)})


@login_required
@require_POST
def checklist_item_toggle(request: HttpRequest, pk: int, item_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    item = get_object_or_404(PanelCotizacionElementoAccion, pk=item_id, cotizacion=obj)
    item.completado = (request.POST.get("completado") or "").strip().lower() in {
        "1",
        "true",
        "on",
        "yes",
    }
    item.save(update_fields=["completado"])
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_checklist_section(request, obj)})


@login_required
@require_POST
def checklist_item_delete(request: HttpRequest, pk: int, item_id: int) -> JsonResponse:
    if request.headers.get("X-Requested-With") != "XMLHttpRequest":
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    obj = _get_cotizacion_detalle(pk)
    item = get_object_or_404(PanelCotizacionElementoAccion, pk=item_id, cotizacion=obj)
    item.delete()
    obj = _get_cotizacion_detalle(pk)
    return JsonResponse({"ok": True, "html": _render_checklist_section(request, obj)})


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
    obj = get_object_or_404(PanelCotizacion, pk=pk, eliminado_en__isnull=True)
    with transaction.atomic():
        enviar_a_papelera(obj, request.user)
    return JsonResponse(
        {
            "status": "ok",
            "ok": True,
            "id": pk,
            "message": "La tarjeta se envió a la papelera correctamente.",
        }
    )


# ETIQUETAS AJAX IMPLEMENTATION

from .forms import PanelCotizacionEtiquetaAssignForm, PanelCotizacionEtiquetaCreateForm

def _etiquetas_queryset(cotizacion):
    return cotizacion.etiquetas.order_by('nombre', 'id')

def _etiquetas_data(etiquetas):
    return [{'id': e.id, 'nombre': e.nombre, 'color': e.color} for e in etiquetas]

def _render_etiquetas_section(request, cotizacion, etiquetas_form=None, etiqueta_create_form=None, return_data=False):
    etiquetas = list(_etiquetas_queryset(cotizacion))
    html = render_to_string('panel_cotizaciones/_etiquetas_section.html', {
        'panel': cotizacion,
        'etiquetas': etiquetas,
        'etiquetas_count': len(etiquetas),
        'etiquetas_form': etiquetas_form or PanelCotizacionEtiquetaAssignForm(),
        'etiqueta_create_form': etiqueta_create_form or PanelCotizacionEtiquetaCreateForm()
    }, request=request)
    if return_data:
        return html, _etiquetas_data(etiquetas)
    return html

def _etiquetas_response(request, cotizacion, *, etiquetas_form=None, etiqueta_create_form=None, success=True, status=200):
    tags_html, tags = _render_etiquetas_section(request, cotizacion, etiquetas_form=etiquetas_form, etiqueta_create_form=etiqueta_create_form, return_data=True)
    return JsonResponse({'success': success, 'id': cotizacion.id, 'tags_html': tags_html, 'tags': tags, 'tags_count': len(tags)}, status=status)

@login_required
@require_POST
def agregar_etiqueta_cotizacion(request, panel_id):
    cotizacion = get_object_or_404(_board_queryset([request.user]), id=panel_id)
    if not _puede_operar_panel(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    form = PanelCotizacionEtiquetaAssignForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, cotizacion, etiquetas_form=form, success=False, status=400)
    
    cotizacion.etiquetas.add(*form.cleaned_data['etiquetas'])
    return _etiquetas_response(request, cotizacion)

@login_required
@require_POST
def crear_etiqueta_cotizacion(request, panel_id):
    cotizacion = get_object_or_404(_board_queryset([request.user]), id=panel_id)
    if not _puede_operar_panel(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    form = PanelCotizacionEtiquetaCreateForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, cotizacion, etiqueta_create_form=form, success=False, status=400)
    
    nombre = form.cleaned_data['nombre']
    etiqueta = PanelCotizacionEtiqueta.objects.filter(nombre__iexact=nombre).first()
    if not etiqueta:
        etiqueta = PanelCotizacionEtiqueta.objects.create(nombre=nombre, color=form.cleaned_data['color'])
    
    cotizacion.etiquetas.add(etiqueta)
    return _etiquetas_response(request, cotizacion)

@login_required
@require_POST
def quitar_etiqueta_cotizacion(request, panel_id, etiqueta_id):
    cotizacion = get_object_or_404(_board_queryset([request.user]), id=panel_id)
    if not _puede_operar_panel(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    etiqueta = get_object_or_404(PanelCotizacionEtiqueta, id=etiqueta_id)
    cotizacion.etiquetas.remove(etiqueta)
    return _etiquetas_response(request, cotizacion)

