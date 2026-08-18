from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Prefetch, Q, Window
from django.db.models.functions import RowNumber
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .decorators import admin_required
from solicitudes_app.trash import enviar_a_papelera
from .forms import (
    GarantiaArchivosForm,
    GarantiaArchivoUploadForm,
    GarantiaComentarioForm,
    GarantiaColumnaCreateForm,
    GarantiaColumnaUpdateForm,
    GarantiaEditarForm,
    GarantiaEnlaceForm,
    GarantiaEnlaceCreateForm,
    GarantiaForm,
    GarantiaInlineCreateForm,
    GarantiaQuickEditForm,
)
from .models import (
    Garantia,
    GarantiaArchivo,
    GarantiaColumna,
    GarantiaComentario,
    GarantiaEnlace,
    GarantiaEtiqueta,
)
from .services import copiar_garantia_a_columna

User = get_user_model()

INITIAL_CARDS_PER_COLUMN = 10
CARDS_PAGE_SIZE = 10
GARANTIA_ORDERING = ("-fecha_creacion", "-id")
COLUMNAS_INICIALES = (
    (Garantia.Estado.SOLICITUD_NAVIERA, "En proceso"),
    (Garantia.Estado.PAGO_NAVIERA_ZAHA, "Pago naviera a zaha"),
    (Garantia.Estado.DEVOLUCION_CLIENTE, "Devolución a cliente"),
)


def _columnas_activas_queryset():
    return GarantiaColumna.objects.filter(activa=True).order_by("orden", "id")


def _columnas_activas():
    return list(_columnas_activas_queryset())


def _primer_columna_activa():
    return _columnas_activas_queryset().first()


def _columnas_estado_choices():
    return [(columna.codigo, columna.nombre) for columna in _columnas_activas()]


def _buscar_columna_activa_por_codigo(codigo: str):
    return _columnas_activas_queryset().filter(
        codigo=Garantia.normalizar_estado_codigo(codigo)
    ).first()


def _estado_label(estado):
    columna = _buscar_columna_activa_por_codigo(estado)
    if columna is not None:
        return columna.nombre
    return dict(COLUMNAS_INICIALES).get(estado, estado)


def _puede_operar_garantias(user) -> bool:
    return bool(user.is_authenticated and user.is_active)


def _estados_disponibles():
    return [codigo for codigo, _nombre in _columnas_estado_choices()]


def _generar_codigo_columna(nombre: str) -> str:
    base = slugify(nombre).replace("-", "_").upper()
    if not base:
        base = "COLUMNA"
    if base[0].isdigit():
        base = f"COLUMNA_{base}"
    candidato = base
    indice = 2
    while GarantiaColumna.objects.filter(codigo=candidato).exists():
        candidato = f"{base}_{indice}"
        indice += 1
    return candidato


def _siguiente_orden_columna() -> int:
    ultima = GarantiaColumna.objects.order_by("-orden", "-id").first()
    return (ultima.orden + 1) if ultima is not None else 1


def _column_context(*, columna: GarantiaColumna, items, count: int, loaded: int):
    return {
        "id": columna.pk,
        "columna_id": columna.pk,
        "codigo": columna.codigo,
        "estado": columna.codigo,
        "nombre": columna.nombre,
        "estado_texto": columna.nombre,
        "items": items,
        "count": count,
        "loaded": loaded,
        "has_more": count > loaded,
        "remaining": max(0, count - loaded),
        "load_url": reverse(
            "garantias:tarjetas_columna",
            kwargs={"codigo": columna.codigo},
        ),
        "paste_url": reverse(
            "garantias:tarjeta_pegar",
            kwargs={"columna_id": columna.pk},
        ),
    }


def _nombre_corto_usuario(usuario):
    return (usuario.first_name or "").strip()


def _iniciales_usuario(usuario):
    nombre = _nombre_corto_usuario(usuario)
    if not nombre:
        return ""
    partes = [parte for parte in nombre.split() if parte]
    if len(partes) >= 2:
        return f"{partes[0][0]}{partes[1][0]}".upper()
    return nombre[:2].upper()


def _es_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _garantia_queryset():
    return (
        Garantia.objects.filter(eliminado_en__isnull=True)
        .select_related("cliente", "creado_por", "columna")
        .prefetch_related("asignados", "etiquetas")
        .annotate(
            comentarios_count=Count("comentarios", distinct=True),
            archivos_count=Count("archivos", distinct=True),
            enlaces_count=Count("enlaces", distinct=True),
        )
        .order_by("-fecha_creacion", "-id")
    )


def _garantia_detalle_queryset():
    return (
        Garantia.objects.filter(eliminado_en__isnull=True)
        .select_related("cliente", "creado_por", "columna")
        .prefetch_related(
            "asignados",
            "etiquetas",
            Prefetch(
                "comentarios",
                queryset=GarantiaComentario.objects.select_related("usuario").order_by("-fecha", "-id"),
                to_attr="comentarios_detalle",
            ),
            Prefetch(
                "archivos",
                queryset=GarantiaArchivo.objects.select_related("subido_por").order_by("-fecha", "-id"),
                to_attr="archivos_detalle",
            ),
            Prefetch(
                "enlaces",
                queryset=GarantiaEnlace.objects.select_related("creado_por").order_by("-fecha", "-id"),
                to_attr="enlaces_detalle",
            ),
        )
        .annotate(
            comentarios_count=Count("comentarios", distinct=True),
            archivos_count=Count("archivos", distinct=True),
            enlaces_count=Count("enlaces", distinct=True),
        )
        .order_by("-fecha_creacion", "-id")
    )


def _board_queryset(usuario=None):
    codigos_activos = [codigo for codigo, _nombre in _columnas_estado_choices()]
    queryset = _garantia_queryset().filter(estado__in=codigos_activos).filter(
        Q(columna__activa=True) | Q(columna__isnull=True)
    )
    if usuario is not None:
        queryset = queryset.filter(asignados__id=usuario.id).distinct()
    return queryset.order_by(*GARANTIA_ORDERING)


def _columnas_kanban(usuario=None):
    columnas = _columnas_activas()
    garantias = list(
        _board_queryset(usuario)
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
        .filter(posicion_columna__lte=INITIAL_CARDS_PER_COLUMN)
    )
    items_por_estado = {columna.codigo: [] for columna in columnas}
    totales = {columna.codigo: 0 for columna in columnas}
    for garantia in garantias:
        if garantia.estado in items_por_estado:
            items_por_estado[garantia.estado].append(garantia)
            totales[garantia.estado] = garantia.total_columna

    return [
        _column_context(
            columna=columna,
            items=items_por_estado[columna.codigo],
            count=totales[columna.codigo],
            loaded=len(items_por_estado[columna.codigo]),
        )
        for columna in columnas
    ]


def _get_usuario_filter(request):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id.isdigit():
        return None
    return User.objects.filter(pk=int(usuario_id)).first()


def _get_usuario_filter_estricto(request):
    raw_values = [
        value.strip()
        for value in request.GET.getlist("usuario")
        if (value or "").strip()
    ]
    if not raw_values:
        return None, None
    if (
        len(raw_values) != 1
        or not raw_values[0].isdigit()
        or int(raw_values[0]) <= 0
    ):
        return None, JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    usuario = User.objects.filter(
        pk=int(raw_values[0]),
        is_active=True,
    ).first()
    if usuario is None:
        return None, JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    return usuario, None


def _parse_loaded_ids(request, offset):
    raw_values = request.GET.getlist("loaded")
    parts = []
    for raw_value in raw_values:
        parts.extend(
            value.strip()
            for value in raw_value.split(",")
            if value.strip()
        )
    if not parts:
        return [] if offset == 0 else None
    if any(not value.isdigit() or int(value) <= 0 for value in parts):
        return None
    loaded_ids = list(dict.fromkeys(int(value) for value in parts))
    if len(loaded_ids) != len(parts) or len(loaded_ids) != offset:
        return None
    return loaded_ids


def _usuarios_filtro(selected_user_id=None):
    usuarios = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username", "id")
    return [
        {
            "id": usuario.id,
            "nombre": usuario.first_name or usuario.get_full_name() or usuario.username,
            "seleccionado": usuario.id == selected_user_id,
        }
        for usuario in usuarios
    ]


def _safe_next_url(request):
    next_url = (request.POST.get("next") or request.GET.get("next") or "").strip()
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _contexto_modal_garantia(garantia, form=None, archivos_form=None, enlace_form=None, comentario_form=None):
    asignados = [usuario for usuario in garantia.asignados.all() if _nombre_corto_usuario(usuario)]
    etiquetas = list(garantia.etiquetas.all())
    return {
        "garantia": garantia,
        "form": form or GarantiaEditarForm(instance=garantia),
        "archivos_form": archivos_form or GarantiaArchivosForm(),
        "enlace_form": enlace_form or GarantiaEnlaceForm(),
        "comentario_form": comentario_form or GarantiaComentarioForm(),
        "etiquetas_form": GarantiaEtiquetaAssignForm(),
        "etiqueta_create_form": GarantiaEtiquetaCreateForm(),
        "nombre_corto_asignados": [_nombre_corto_usuario(usuario) for usuario in asignados],
        "iniciales_asignados": [_iniciales_usuario(usuario) for usuario in asignados],
        "asignados_count": len(asignados),
        "comentarios": getattr(garantia, "comentarios_detalle", _comentarios_queryset(garantia)),
        "comentarios_count": garantia.comentarios_count,
        "archivos": getattr(garantia, "archivos_detalle", _archivos_queryset(garantia)),
        "enlaces": getattr(garantia, "enlaces_detalle", _enlaces_queryset(garantia)),
        "etiquetas": etiquetas,
        "etiquetas_count": len(etiquetas),
    }


def _render_inline_create_form(request, form, columna):
    return render_to_string(
        "garantias/_inline_create_form.html",
        {
            "form": form,
            "estado": columna.codigo,
            "estado_texto": columna.nombre,
            "columna": columna,
        },
        request=request,
    )


def _guardar_adjuntos_enlaces(request, garantia, enlace_form):
    for archivo in request.FILES.getlist("archivos"):
        GarantiaArchivo.objects.create(garantia=garantia, archivo=archivo, subido_por=request.user)

    if (enlace_form.cleaned_data.get("titulo") or "").strip() and (enlace_form.cleaned_data.get("url") or "").strip():
        enlace = enlace_form.save(commit=False)
        enlace.garantia = garantia
        enlace.creado_por = request.user
        enlace.save()


def _guardar_enlaces_payload(garantia, enlaces_payload, usuario):
    for enlace in enlaces_payload:
        GarantiaEnlace.objects.create(
            garantia=garantia,
            titulo=enlace["titulo"],
            url=enlace["url"],
            creado_por=usuario,
        )


def _estado_inicial_garantia():
    return _primer_columna_activa()


def _columna_manual_permitida():
    return _primer_columna_activa()


def _column_count(columna: GarantiaColumna) -> int:
    return Garantia.objects.filter(estado=columna.codigo, eliminado_en__isnull=True).count()


def _es_columna_base(columna: GarantiaColumna) -> bool:
    return columna.codigo in {codigo for codigo, _nombre in COLUMNAS_INICIALES}


def _render_card_html(request, garantia):
    return render_to_string(
        "garantias/_garantia_card.html",
        {
            "g": garantia,
            "today": timezone.localdate(),
            "columnas_estado": _columnas_estado_choices(),
        },
        request=request,
    )


def _get_garantia_para_copia(pk: int) -> Garantia:
    return get_object_or_404(
        Garantia.objects.filter(eliminado_en__isnull=True).select_related("columna", "cliente", "creado_por")
        .prefetch_related("asignados", "etiquetas"),
        pk=pk,
    )


def _render_quick_edit_form(request, garantia, form=None):
    return render_to_string(
        "garantias/_quick_edit_form.html",
        {"g": garantia, "form": form or GarantiaQuickEditForm(instance=garantia)},
        request=request,
    )


def _comentarios_queryset(garantia):
    return garantia.comentarios.select_related("usuario").order_by("-fecha", "-id")


def _render_comentarios_section(request, garantia, *, form=None, layout="modal"):
    return render_to_string(
        "garantias/comentarios/_comentarios_section.html",
        {
            "garantia": garantia,
            "comentario_form": form or GarantiaComentarioForm(),
            "comentarios": _comentarios_queryset(garantia),
            "comentarios_count": garantia.comentarios_count,
            "layout": layout,
        },
        request=request,
    )


def _archivos_queryset(garantia):
    return garantia.archivos.select_related("subido_por").order_by("-fecha", "-id")


def _render_archivos_section(request, garantia, *, form=None):
    return render_to_string(
        "garantias/_archivos_section.html",
        {
            "garantia": garantia,
            "archivos": _archivos_queryset(garantia),
            "archivos_form": form or GarantiaArchivoUploadForm(),
        },
        request=request,
    )


def _enlaces_queryset(garantia):
    return garantia.enlaces.select_related("creado_por").order_by("-fecha", "-id")


def _render_enlaces_section(request, garantia, *, form=None):
    return render_to_string(
        "garantias/_enlaces_section.html",
        {
            "garantia": garantia,
            "enlaces": _enlaces_queryset(garantia),
            "enlace_form": form or GarantiaEnlaceCreateForm(),
        },
        request=request,
    )


def _detalle_template_name(layout: str) -> str:
    return (
        "garantias/_detalle_drawer.html"
        if layout == "drawer"
        else "garantias/_detalle_modal_content.html"
    )


@login_required
@admin_required
@ensure_csrf_cookie
def panel_garantias(request):
    usuario = _get_usuario_filter(request)
    return render(
        request,
        "garantias/panel_garantias.html",
        {
            "columnas_kanban": _columnas_kanban(usuario),
            "columnas_estado": _columnas_estado_choices(),
            "columnas_activas": _columnas_activas(),
            "columna_create_form": GarantiaColumnaCreateForm(),
            "panel_config": {
                "estadoUpdateUrl": reverse("garantias:actualizar_estado_garantia"),
                "boardUrl": reverse("garantias:tablero_partial"),
                "inlineCreateUrl": reverse("garantias:crear_garantia_inline"),
                "inlineFormUrl": reverse("garantias:formulario_garantia_inline"),
                "columnCreateUrl": reverse("garantias:columna_crear"),
                "columnReorderUrl": reverse("garantias:columna_reordenar"),
            },
            "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
            "today": timezone.localdate(),
        },
    )


@login_required
@admin_required
@require_GET
def tablero_partial(request):
    usuario = _get_usuario_filter(request)
    return render(
        request,
        "garantias/_tablero.html",
        {
            "columnas_kanban": _columnas_kanban(usuario),
            "columnas_estado": _columnas_estado_choices(),
            "today": timezone.localdate(),
        },
    )


@login_required
@admin_required
@require_GET
def tarjetas_columna(request, codigo):
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
    usuario, error = _get_usuario_filter_estricto(request)
    if error is not None:
        return error
    loaded_ids = _parse_loaded_ids(request, offset)
    if loaded_ids is None:
        return JsonResponse(
            {"ok": False, "error": "Tarjetas cargadas invalidas."},
            status=400,
        )

    columna = _board_queryset(usuario).filter(estado=columna_obj.codigo)
    total = columna.count()
    recognized_loaded_ids = set(
        columna.filter(pk__in=loaded_ids).values_list("pk", flat=True)
    )
    stale_ids = [
        pk for pk in loaded_ids if pk not in recognized_loaded_ids
    ]
    siguientes = list(
        columna.exclude(pk__in=loaded_ids)[: CARDS_PAGE_SIZE + 1]
    )
    has_more = len(siguientes) > CARDS_PAGE_SIZE
    garantias = siguientes[:CARDS_PAGE_SIZE]
    columnas_estado = _columnas_estado_choices()
    html = "".join(
        render_to_string(
            "garantias/_garantia_card.html",
            {
                "g": garantia,
                "today": timezone.localdate(),
                "columnas_estado": columnas_estado,
            },
            request=request,
        )
        for garantia in garantias
    )
    loaded = len(garantias)
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
@admin_required
@require_GET
def formulario_garantia_inline(request):
    columna = _estado_inicial_garantia()
    if columna is None:
        return JsonResponse({"ok": False, "error": "No hay columnas disponibles."}, status=400)
    return render(
        request,
        "garantias/_inline_create_form.html",
        {
            "form": GarantiaInlineCreateForm(),
            "estado": columna.codigo,
            "estado_texto": columna.nombre,
            "columna": columna,
        },
    )


@login_required
@admin_required
def crear_garantia(request):
    next_url = _safe_next_url(request)
    columna_inicial = _estado_inicial_garantia()
    if columna_inicial is None:
        raise PermissionDenied("No hay columnas disponibles en garantias.")
    if request.method == "POST":
        form = GarantiaForm(request.POST, request.FILES)
        archivos_form = GarantiaArchivosForm(request.POST, request.FILES)
        enlace_form = GarantiaEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            with transaction.atomic():
                garantia = form.save(commit=False)
                garantia.columna = columna_inicial
                garantia.estado = columna_inicial.codigo
                garantia.creado_por = request.user
                garantia.save()
                form.save_m2m()
                _guardar_adjuntos_enlaces(request, garantia, enlace_form)
            messages.success(request, "Garantía creada.")
            if next_url:
                return redirect(next_url)
            return redirect("garantias:panel_garantias")
    else:
        form = GarantiaForm()
        archivos_form = GarantiaArchivosForm()
        enlace_form = GarantiaEnlaceForm()

    return render(
        request,
        "garantias/crear_garantia.html",
        {"form": form, "archivos_form": archivos_form, "enlace_form": enlace_form, "next_url": next_url},
    )


@login_required
@admin_required
@require_POST
def crear_garantia_inline(request):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    estado = (request.POST.get("estado") or "").strip()
    columna = _buscar_columna_activa_por_codigo(estado) or _estado_inicial_garantia()
    if columna is None:
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Columna invalida."]}},
            status=400,
        )
    columna_permitida = _columna_manual_permitida()
    if (
        columna_permitida is None
        or columna.pk != columna_permitida.pk
    ):
        return JsonResponse(
            {
                "ok": False,
                "message": "Solo se pueden crear tarjetas desde la primera columna activa.",
                "errors": {
                    "estado": [
                        {
                            "message": "Solo se pueden crear tarjetas desde la primera columna activa.",
                            "code": "invalid",
                        }
                    ]
                },
            },
            status=400,
        )
    form = GarantiaInlineCreateForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "message": "Revisa los campos marcados.",
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, columna),
            },
            status=400,
        )

    with transaction.atomic():
        garantia = form.save(commit=False)
        garantia.columna = columna
        garantia.estado = columna.codigo
        garantia.creado_por = request.user
        garantia.save()
        form.save_m2m()
        for archivo in request.FILES.getlist("archivos"):
            GarantiaArchivo.objects.create(
                garantia=garantia,
                archivo=archivo,
                subido_por=request.user,
            )
        _guardar_enlaces_payload(
            garantia,
            form.cleaned_data.get("enlaces_payload", []),
            request.user,
        )

    garantia = get_object_or_404(_garantia_queryset(), pk=garantia.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": "Garantia creada correctamente.",
            "html": _render_card_html(request, garantia),
            "card_html": _render_card_html(request, garantia),
            "id": garantia.pk,
            "garantia_id": garantia.pk,
            "estado": garantia.estado,
            "column_count": _column_count(columna),
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
        },
        status=201,
    )


@login_required
@admin_required
@require_http_methods(["GET", "POST"])
def actualizar_garantia_inline(request, pk):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    if request.method == "GET":
        return JsonResponse({"ok": True, "html": _render_quick_edit_form(request, garantia)})

    form = GarantiaQuickEditForm(request.POST, instance=garantia)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_quick_edit_form(request, garantia, form),
            },
            status=400,
        )

    # Cada formulario inline contiene exclusivamente el campo solicitado y se
    # enlaza a la instancia existente. ModelForm se encarga tanto de los campos
    # simples como de la relación M2M; por ello no se toca ningún otro valor de
    # la garantía ni se vacían relaciones ajenas al formulario.
    garantia = form.save()

    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "id": garantia.id,
            # El cliente reemplaza la tarjeta completa para conservar todos los
            # bloques visuales sincronizados (comentarios, estado y metadatos).
            "html": _render_card_html(request, garantia),
        }
    )


@login_required
@admin_required
@require_POST
def columna_crear(request):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    form = GarantiaColumnaCreateForm(request.POST)
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
        "garantias/_columna.html",
        {
            "columna": _column_context(columna=columna, items=[], count=0, loaded=0),
            "columnas_estado": _columnas_estado_choices(),
            "es_primera_columna": False,
            "today": timezone.localdate(),
        },
        request=request,
    )
    return JsonResponse(
        {
            "ok": True,
            "columna_id": columna.pk,
            "columna_codigo": columna.codigo,
            "nombre": columna.nombre,
            "html": html,
        },
        status=201,
    )


@login_required
@admin_required
@require_POST
def columna_editar(request, pk):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    columna = get_object_or_404(GarantiaColumna, pk=pk, activa=True)
    form = GarantiaColumnaUpdateForm(request.POST, instance=columna)
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
@admin_required
@require_POST
def columna_reordenar(request):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    raw_ids = request.POST.getlist("columnas[]") or request.POST.getlist("columnas")
    if not raw_ids:
        return JsonResponse({"ok": False, "error": "Debes enviar columnas."}, status=400)
    if any(not value.isdigit() or int(value) <= 0 for value in raw_ids):
        return JsonResponse({"ok": False, "error": "IDs invalidos."}, status=400)
    ids = [int(value) for value in raw_ids]
    if len(ids) != len(set(ids)):
        return JsonResponse({"ok": False, "error": "IDs duplicados."}, status=400)
    columnas = list(GarantiaColumna.objects.filter(pk__in=ids, activa=True))
    if len(columnas) != len(ids):
        return JsonResponse({"ok": False, "error": "Columna no encontrada."}, status=400)
    with transaction.atomic():
        for orden, columna_id in enumerate(ids, start=1):
            GarantiaColumna.objects.filter(pk=columna_id).update(orden=orden)
    return JsonResponse({"ok": True})


@login_required
@admin_required
@require_POST
def columna_eliminar(request, pk):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    columna = get_object_or_404(GarantiaColumna, pk=pk, activa=True)
    if _es_columna_base(columna):
        return JsonResponse(
            {
                "ok": False,
                "error": "Esta columna base no puede eliminarse porque tiene dependencias criticas.",
            },
            status=400,
        )
    activas = _columnas_activas()
    if len(activas) <= 1:
        return JsonResponse(
            {"ok": False, "error": "No puedes eliminar la ultima columna activa."},
            status=400,
        )
    destino_id = (request.POST.get("columna_destino_id") or "").strip()
    garantias_qs = Garantia.objects.filter(
        Q(columna=columna) | Q(columna__isnull=True, estado=columna.codigo),
        eliminado_en__isnull=True,
    )
    total_garantias = garantias_qs.count()
    if total_garantias > 0:
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
        destino = get_object_or_404(GarantiaColumna, pk=int(destino_id), activa=True)
    else:
        destino = None
    with transaction.atomic():
        if destino is not None:
            garantias_qs.update(columna=destino, estado=destino.codigo)
        columna.activa = False
        columna.save(update_fields=["activa", "fecha_actualizacion"])
        for orden, columna_id in enumerate(
            GarantiaColumna.objects.filter(activa=True)
            .order_by("orden", "id")
            .values_list("pk", flat=True),
            start=1,
        ):
            GarantiaColumna.objects.filter(pk=columna_id).update(orden=orden)
    response_data = {"ok": True, "columna_id": columna.pk}
    if destino is not None:
        response_data.update(
            {
                "moved_count": total_garantias,
                "columna_destino_id": destino.pk,
                "columna_destino_codigo": destino.codigo,
                "column_count": _column_count(destino),
            }
        )
    return JsonResponse(response_data)


@login_required
@admin_required
@require_POST
def tarjeta_pegar(request, columna_id):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    if not _puede_operar_garantias(request.user):
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=403)

    raw_tarjeta_id = (request.POST.get("tarjeta_id") or "").strip()
    modulo = (request.POST.get("modulo") or "").strip()
    if modulo and modulo != "garantias":
        return JsonResponse(
            {"ok": False, "error": "Solo se permite copiar tarjetas de garantias."},
            status=400,
        )
    if not raw_tarjeta_id.isdigit() or int(raw_tarjeta_id) <= 0:
        return JsonResponse({"ok": False, "error": "Tarjeta invalida."}, status=400)

    columna_destino = get_object_or_404(GarantiaColumna, pk=columna_id, activa=True)
    garantia_original = _get_garantia_para_copia(int(raw_tarjeta_id))
    if not _puede_operar_garantias(request.user):
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=403)

    nueva = copiar_garantia_a_columna(
        garantia_original=garantia_original,
        columna_destino=columna_destino,
        usuario=request.user,
    )
    nueva = get_object_or_404(_garantia_queryset(), pk=nueva.pk)
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
@admin_required
@require_POST
def actualizar_estado_garantia(request):
    garantia_id = (request.POST.get("garantia_id") or "").strip()
    nuevo_estado = (request.POST.get("nuevo_estado") or request.POST.get("estado") or "").strip().upper()
    garantia = get_object_or_404(_garantia_queryset(), pk=garantia_id)
    columna = _buscar_columna_activa_por_codigo(nuevo_estado)
    if columna is None:
        raise PermissionDenied("Estado inválido.")
    if garantia.estado != nuevo_estado or garantia.columna_id != columna.pk:
        garantia.columna = columna
        garantia.estado = columna.codigo
        garantia.save(update_fields=["columna", "estado"])

    if _es_ajax(request):
        return JsonResponse(
            {
                "status": "ok",
                "id": garantia.pk,
                "estado": garantia.estado,
                "estado_label": columna.nombre,
                "columna_id": columna.pk,
                "columna_codigo": columna.codigo,
            }
        )
    return redirect("garantias:panel_garantias")


@login_required
@admin_required
@require_POST
def cambiar_estado_garantia(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    nuevo_estado = (request.POST.get("estado") or request.POST.get("nuevo_estado") or "").strip().upper()
    columna = _buscar_columna_activa_por_codigo(nuevo_estado)
    if columna is None:
        raise PermissionDenied("Estado inválido.")
    if garantia.estado != nuevo_estado or garantia.columna_id != columna.pk:
        garantia.columna = columna
        garantia.estado = columna.codigo
        garantia.save(update_fields=["columna", "estado"])

    if _es_ajax(request):
        return JsonResponse(
            {
                "status": "ok",
                "id": garantia.pk,
                "estado": garantia.estado,
                "estado_label": columna.nombre,
                "columna_id": columna.pk,
                "columna_codigo": columna.codigo,
            }
        )
    return redirect("garantias:panel_garantias")


@login_required
@admin_required
@require_POST
def agregar_comentario(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    form = GarantiaComentarioForm(request.POST)
    layout = (request.POST.get("layout") or "modal").strip()
    if form.is_valid():
        GarantiaComentario.objects.create(
            garantia=garantia,
            usuario=request.user,
            comentario=form.cleaned_data["comentario"].strip(),
        )
        if _es_ajax(request):
            garantia = get_object_or_404(_garantia_queryset(), pk=pk)
            return JsonResponse(
                {
                    "success": True,
                    "status": "ok",
                    "id": garantia.pk,
                    "html": _render_comentarios_section(request, garantia, layout=layout),
                    "comentarios_count": garantia.comentarios.count(),
                }
            )
        messages.success(request, "Comentario agregado.")
    else:
        if _es_ajax(request):
            garantia = get_object_or_404(_garantia_queryset(), pk=pk)
            return JsonResponse(
                {
                    "success": False,
                    "status": "error",
                    "errors": form.errors.get_json_data(escape_html=True),
                    "html": _render_comentarios_section(request, garantia, form=form, layout=layout),
                    "comentarios_count": garantia.comentarios.count(),
                },
                status=400,
            )
        messages.error(request, "No se pudo agregar el comentario.")

    return redirect(f"{reverse('garantias:panel_garantias')}#garantia-{garantia.pk}")


@login_required
@admin_required
def detalle_garantia(request, pk):
    garantia = get_object_or_404(_garantia_detalle_queryset(), pk=pk)
    layout = (request.GET.get("layout") or "modal").strip()
    contexto = _contexto_modal_garantia(garantia)
    contexto["layout"] = layout
    if _es_ajax(request):
        return render(request, _detalle_template_name(layout), contexto)
    return render(request, "garantias/detalle_garantia.html", contexto)


@login_required
@admin_required
def detalle_garantia_parcial(request, pk):
    garantia = get_object_or_404(_garantia_detalle_queryset(), pk=pk)
    layout = (request.GET.get("layout") or "modal").strip()
    contexto = _contexto_modal_garantia(garantia)
    contexto["layout"] = layout
    return render(request, _detalle_template_name(layout), contexto)


def _preservar_vacios_garantia(form, objeto):
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
@admin_required
def editar_garantia(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    layout = (request.POST.get("layout") or request.GET.get("layout") or "modal").strip()
    if request.method == "POST":
        form = GarantiaEditarForm(request.POST, instance=garantia)
        archivos_form = GarantiaArchivosForm(request.POST, request.FILES)
        enlace_form = GarantiaEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            with transaction.atomic():
                # Preservar campos no-m2m que llegan vacíos
                _preservar_vacios_garantia(form, garantia)

                obj = form.save(commit=False)
                obj.save()

                # M2M: solo actualizar si el campo fue enviado explícitamente en el POST
                if "asignados" in request.POST:
                    valores = form.cleaned_data.get("asignados")
                    if valores is not None:
                        garantia.asignados.set(valores)

                _guardar_adjuntos_enlaces(request, garantia, enlace_form)
            garantia = get_object_or_404(_garantia_queryset(), pk=pk)
            messages.success(request, "Garantía actualizada.")
            if _es_ajax(request):
                contexto = _contexto_modal_garantia(garantia)
                contexto["layout"] = layout
                return JsonResponse(
                    {
                        "status": "ok",
                        "html": render_to_string(
                            _detalle_template_name(layout),
                            contexto,
                            request=request,
                        ),
                        "card_html": _render_card_html(request, garantia),
                        "id": garantia.pk,
                    }
                )
            return redirect("garantias:detalle_garantia", pk=garantia.pk)
    else:
        form = GarantiaEditarForm(instance=garantia)
        archivos_form = GarantiaArchivosForm()
        enlace_form = GarantiaEnlaceForm()

    contexto = _contexto_modal_garantia(garantia, form=form, archivos_form=archivos_form, enlace_form=enlace_form)
    contexto["layout"] = layout
    if _es_ajax(request):
        return render(request, _detalle_template_name(layout), contexto, status=400 if request.method == "POST" else 200)
    return render(request, "garantias/editar_garantia.html", contexto)


@login_required
@admin_required
@require_POST
def eliminar_garantia(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    with transaction.atomic():
        enviar_a_papelera(garantia, request.user)
    messages.success(request, "La tarjeta se envió a la papelera correctamente.")
    if _es_ajax(request):
        return JsonResponse(
            {
                "status": "ok",
                "ok": True,
                "deleted": True,
                "id": pk,
                "garantia_id": pk,
                "message": "La tarjeta se envió a la papelera correctamente.",
            }
        )
    return redirect("garantias:panel_garantias")




@login_required
@admin_required
def descargar_archivo(request, pk, archivo_id):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    archivo = get_object_or_404(GarantiaArchivo, pk=archivo_id, garantia=garantia)
    fh = archivo.archivo.open("rb")
    return FileResponse(fh, as_attachment=True, filename=archivo.archivo.name.split("/")[-1])


@login_required
@admin_required
@require_POST
def agregar_archivos(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    if not _es_ajax(request):
        return JsonResponse(
            {"success": False, "error": "Solicitud AJAX requerida."}, status=400
        )

    form = GarantiaArchivoUploadForm(request.POST, request.FILES)
    if form.is_valid():
        for archivo in form.cleaned_data["archivos"]:
            GarantiaArchivo.objects.create(
                garantia=garantia,
                archivo=archivo,
                subido_por=request.user,
            )
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "success": True,
                "id": garantia.pk,
                "files_html": _render_archivos_section(request, garantia),
                "files_count": garantia.archivos.count(),
            }
        )

    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    return JsonResponse(
        {
            "success": False,
            "id": garantia.pk,
            "files_html": _render_archivos_section(request, garantia, form=form),
            "files_count": garantia.archivos.count(),
        },
        status=400,
    )


@login_required
@admin_required
@require_POST
def eliminar_archivo(request, pk, archivo_id):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    archivo = get_object_or_404(GarantiaArchivo, pk=archivo_id, garantia=garantia)
    if _es_ajax(request):
        archivo.delete()
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "success": True,
                "id": garantia.pk,
                "files_html": _render_archivos_section(request, garantia),
                "files_count": garantia.archivos.count(),
            }
        )

    archivo.delete()
    messages.success(request, "Archivo eliminado.")
    return redirect("garantias:editar_garantia", pk=garantia.pk)


@login_required
@admin_required
@require_POST
def agregar_enlace(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    if not _es_ajax(request):
        return JsonResponse(
            {"success": False, "error": "Solicitud AJAX requerida."}, status=400
        )

    form = GarantiaEnlaceCreateForm(request.POST)
    if form.is_valid():
        enlace = form.save(commit=False)
        enlace.garantia = garantia
        enlace.creado_por = request.user
        enlace.save()
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "success": True,
                "id": garantia.pk,
                "links_html": _render_enlaces_section(request, garantia),
                "links_count": garantia.enlaces.count(),
            }
        )

    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    return JsonResponse(
        {
            "success": False,
            "id": garantia.pk,
            "links_html": _render_enlaces_section(request, garantia, form=form),
            "links_count": garantia.enlaces.count(),
        },
        status=400,
    )


@login_required
@admin_required
@require_POST
def eliminar_enlace(request, pk, enlace_id):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    enlace = get_object_or_404(GarantiaEnlace, pk=enlace_id, garantia=garantia)
    if _es_ajax(request):
        enlace.delete()
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "success": True,
                "id": garantia.pk,
                "links_html": _render_enlaces_section(request, garantia),
                "links_count": garantia.enlaces.count(),
            }
        )

    enlace.delete()
    messages.success(request, "Enlace eliminado.")
    return redirect("garantias:editar_garantia", pk=garantia.pk)


# ETIQUETAS AJAX IMPLEMENTATION

from .forms import GarantiaEtiquetaAssignForm, GarantiaEtiquetaCreateForm

def _etiquetas_queryset(garantia):
    return garantia.etiquetas.order_by('nombre', 'id')

def _etiquetas_data(etiquetas):
    return [{'id': e.id, 'nombre': e.nombre, 'color': e.color} for e in etiquetas]

def _render_etiquetas_section(request, garantia, etiquetas_form=None, etiqueta_create_form=None, return_data=False):
    etiquetas = list(_etiquetas_queryset(garantia))
    html = render_to_string('garantias/_etiquetas_section.html', {
        'garantia': garantia,
        'etiquetas': etiquetas,
        'etiquetas_count': len(etiquetas),
        'etiquetas_form': etiquetas_form or GarantiaEtiquetaAssignForm(),
        'etiqueta_create_form': etiqueta_create_form or GarantiaEtiquetaCreateForm()
    }, request=request)
    if return_data:
        return html, _etiquetas_data(etiquetas)
    return html

def _etiquetas_response(request, garantia, *, etiquetas_form=None, etiqueta_create_form=None, success=True, status=200):
    tags_html, tags = _render_etiquetas_section(request, garantia, etiquetas_form=etiquetas_form, etiqueta_create_form=etiqueta_create_form, return_data=True)
    return JsonResponse({'success': success, 'id': garantia.id, 'tags_html': tags_html, 'tags': tags, 'tags_count': len(tags)}, status=status)

@login_required
@require_POST
def agregar_etiqueta_garantia(request, garantia_id):
    garantia = get_object_or_404(Garantia, id=garantia_id)
    if not _puede_operar_garantias(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    form = GarantiaEtiquetaAssignForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, garantia, etiquetas_form=form, success=False, status=400)
    
    garantia.etiquetas.add(*form.cleaned_data['etiquetas'])
    return _etiquetas_response(request, garantia)

@login_required
@require_POST
def crear_etiqueta_garantia(request, garantia_id):
    garantia = get_object_or_404(Garantia, id=garantia_id)
    if not _puede_operar_garantias(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    form = GarantiaEtiquetaCreateForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, garantia, etiqueta_create_form=form, success=False, status=400)
    
    nombre = form.cleaned_data['nombre']
    etiqueta = GarantiaEtiqueta.objects.filter(nombre__iexact=nombre).first()
    if not etiqueta:
        etiqueta = GarantiaEtiqueta.objects.create(nombre=nombre, color=form.cleaned_data['color'])
    
    garantia.etiquetas.add(etiqueta)
    return _etiquetas_response(request, garantia)

@login_required
@require_POST
def quitar_etiqueta_garantia(request, garantia_id, etiqueta_id):
    garantia = get_object_or_404(Garantia, id=garantia_id)
    if not _puede_operar_garantias(request.user):
        raise PermissionDenied('No tienes permisos.')
    is_ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest'
    if not is_ajax:
        return JsonResponse({'success': False, 'error': 'Solicitud AJAX requerida.'}, status=400)
    
    etiqueta = get_object_or_404(GarantiaEtiqueta, id=etiqueta_id)
    garantia.etiquetas.remove(etiqueta)
    return _etiquetas_response(request, garantia)

