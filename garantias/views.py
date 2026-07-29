from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Window
from django.db.models.functions import RowNumber
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from .decorators import admin_required
from .forms import (
    GarantiaArchivosForm,
    GarantiaArchivoUploadForm,
    GarantiaComentarioForm,
    GarantiaEditarForm,
    GarantiaEnlaceForm,
    GarantiaEnlaceCreateForm,
    GarantiaForm,
    GarantiaInlineCreateForm,
    GarantiaQuickEditForm,
)
from .models import Garantia, GarantiaArchivo, GarantiaComentario, GarantiaEnlace

User = get_user_model()

INITIAL_CARDS_PER_COLUMN = 10
CARDS_PAGE_SIZE = 10
GARANTIA_ORDERING = ("-fecha_creacion", "-id")
ESTADOS_VISIBLES = frozenset(
    (
        Garantia.Estado.SOLICITUD_NAVIERA,
        Garantia.Estado.EN_PROCESO,
        Garantia.Estado.PAGO_NAVIERA_ZAHA,
        Garantia.Estado.DEVOLUCION_CLIENTE,
    )
)


def _estado_label(estado):
    return {
        Garantia.Estado.SOLICITUD_NAVIERA: "Solicitud a naviera",
        Garantia.Estado.EN_PROCESO: "En proceso",
        Garantia.Estado.PAGO_NAVIERA_ZAHA: "Pago naviera a ZAHA",
        Garantia.Estado.DEVOLUCION_CLIENTE: "Devolución a cliente",
    }.get(estado, estado)


def _estados_disponibles():
    return [
        Garantia.Estado.SOLICITUD_NAVIERA,
        Garantia.Estado.EN_PROCESO,
        Garantia.Estado.PAGO_NAVIERA_ZAHA,
        Garantia.Estado.DEVOLUCION_CLIENTE,
    ]


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
        Garantia.objects.select_related("cliente", "creado_por")
        .prefetch_related("asignados")
        .annotate(
            comentarios_count=Count("comentarios", distinct=True),
            archivos_count=Count("archivos", distinct=True),
            enlaces_count=Count("enlaces", distinct=True),
        )
        .order_by("-fecha_creacion", "-id")
    )


def _board_queryset(usuario=None):
    queryset = _garantia_queryset().filter(estado__in=ESTADOS_VISIBLES)
    if usuario is not None:
        queryset = queryset.filter(asignados__id=usuario.id).distinct()
    return queryset.order_by(*GARANTIA_ORDERING)


def _columnas_kanban(usuario=None):
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
    items_por_estado = {estado: [] for estado in _estados_disponibles()}
    totales = {estado: 0 for estado in _estados_disponibles()}
    for garantia in garantias:
        if garantia.estado in items_por_estado:
            items_por_estado[garantia.estado].append(garantia)
            totales[garantia.estado] = garantia.total_columna

    return [
        {
            "estado": estado,
            "estado_texto": _estado_label(estado),
            "items": items_por_estado[estado],
            "count": totales[estado],
            "loaded": len(items_por_estado[estado]),
            "has_more": totales[estado] > len(items_por_estado[estado]),
            "remaining": max(
                0, totales[estado] - len(items_por_estado[estado])
            ),
            "load_url": reverse(
                "garantias:tarjetas_columna",
                kwargs={"estado": estado},
            ),
        }
        for estado in _estados_disponibles()
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
    return {
        "garantia": garantia,
        "form": form or GarantiaEditarForm(instance=garantia),
        "archivos_form": archivos_form or GarantiaArchivosForm(),
        "enlace_form": enlace_form or GarantiaEnlaceForm(),
        "comentario_form": comentario_form or GarantiaComentarioForm(),
        "nombre_corto_asignados": [_nombre_corto_usuario(usuario) for usuario in asignados],
        "iniciales_asignados": [_iniciales_usuario(usuario) for usuario in asignados],
        "asignados_count": len(asignados),
        "comentarios": _comentarios_queryset(garantia),
        "comentarios_count": garantia.comentarios_count,
        "archivos": _archivos_queryset(garantia),
        "enlaces": _enlaces_queryset(garantia),
    }


def _render_inline_create_form(request, form, estado):
    return render_to_string(
        "garantias/_inline_create_form.html",
        {"form": form, "estado": estado},
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


def _render_card_html(request, garantia):
    return render_to_string(
        "garantias/_garantia_card.html",
        {"g": garantia, "today": timezone.localdate()},
        request=request,
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
def panel_garantias(request):
    usuario = _get_usuario_filter(request)
    return render(
        request,
        "garantias/panel_garantias.html",
        {
            "columnas_kanban": _columnas_kanban(usuario),
            "panel_config": {
                "estadoUpdateUrl": reverse("garantias:actualizar_estado_garantia"),
                "inlineCreateUrl": reverse("garantias:crear_garantia_inline"),
                "inlineFormUrl": reverse("garantias:formulario_garantia_inline"),
            },
            "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
            "today": timezone.localdate(),
        },
    )


@login_required
@admin_required
@require_GET
def tarjetas_columna(request, estado):
    if estado not in ESTADOS_VISIBLES:
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

    columna = _board_queryset(usuario).filter(estado=estado)
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
    html = "".join(
        render_to_string(
            "garantias/_garantia_card.html",
            {"g": garantia, "today": timezone.localdate()},
            request=request,
        )
        for garantia in garantias
    )
    loaded = len(garantias)
    return JsonResponse(
        {
            "ok": True,
            "estado": estado,
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
    estado = Garantia.Estado.SOLICITUD_NAVIERA
    return render(
        request,
        "garantias/_inline_create_form.html",
        {
            "form": GarantiaInlineCreateForm(),
            "estado": estado,
            "estado_texto": _estado_label(estado),
        },
    )


@login_required
@admin_required
def crear_garantia(request):
    next_url = _safe_next_url(request)
    if request.method == "POST":
        form = GarantiaForm(request.POST)
        archivos_form = GarantiaArchivosForm(request.POST, request.FILES)
        enlace_form = GarantiaEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            garantia = form.save(commit=False)
            garantia.estado = Garantia.Estado.SOLICITUD_NAVIERA
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

    estado = (request.POST.get("estado") or "").strip().upper()
    estados_validos = set(_estados_disponibles())
    if estado not in estados_validos:
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Estado invalido."]}},
            status=400,
        )

    form = GarantiaInlineCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, estado),
            },
            status=400,
        )

    garantia = form.save(commit=False)
    garantia.estado = estado
    garantia.creado_por = request.user
    garantia.save()
    form.save_m2m()

    garantia = get_object_or_404(_garantia_queryset(), pk=garantia.pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_card_html(request, garantia),
            "id": garantia.pk,
            "estado": garantia.estado,
            "column_count": Garantia.objects.filter(estado=garantia.estado).count(),
        }
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
def actualizar_estado_garantia(request):
    garantia_id = (request.POST.get("garantia_id") or "").strip()
    nuevo_estado = (request.POST.get("nuevo_estado") or request.POST.get("estado") or "").strip().upper()
    garantia = get_object_or_404(Garantia, pk=garantia_id)
    estados_validos = set(_estados_disponibles())
    if nuevo_estado not in estados_validos:
        raise PermissionDenied("Estado inválido.")
    if garantia.estado != nuevo_estado:
        garantia.estado = nuevo_estado
        garantia.save(update_fields=["estado"])

    if _es_ajax(request):
        return JsonResponse(
            {
                "status": "ok",
                "id": garantia.pk,
                "estado": garantia.estado,
                "estado_label": _estado_label(garantia.estado),
            }
        )
    return redirect("garantias:panel_garantias")


@login_required
@admin_required
@require_POST
def cambiar_estado_garantia(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
    nuevo_estado = (request.POST.get("estado") or request.POST.get("nuevo_estado") or "").strip().upper()
    estados_validos = set(_estados_disponibles())
    if nuevo_estado not in estados_validos:
        raise PermissionDenied("Estado inválido.")
    if garantia.estado != nuevo_estado:
        garantia.estado = nuevo_estado
        garantia.save(update_fields=["estado"])

    if _es_ajax(request):
        return JsonResponse(
            {
                "status": "ok",
                "id": garantia.pk,
                "estado": garantia.estado,
                "estado_label": _estado_label(garantia.estado),
            }
        )
    return redirect("garantias:panel_garantias")


@login_required
@admin_required
@require_POST
def agregar_comentario(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
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
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    layout = (request.GET.get("layout") or "modal").strip()
    contexto = _contexto_modal_garantia(garantia)
    contexto["layout"] = layout
    if _es_ajax(request):
        return render(request, _detalle_template_name(layout), contexto)
    return render(request, "garantias/detalle_garantia.html", contexto)


@login_required
@admin_required
def detalle_garantia_parcial(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
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
def eliminar_garantia(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
    if request.method == "POST":
        garantia.delete()
        messages.success(request, "Garantía eliminada.")
        if _es_ajax(request):
            return JsonResponse({"status": "ok", "deleted": True, "id": pk})
        return redirect("garantias:panel_garantias")

    return render(request, "garantias/eliminar_garantia.html", {"garantia": garantia})


@login_required
@admin_required
def descargar_archivo(request, pk, archivo_id):
    garantia = get_object_or_404(Garantia, pk=pk)
    archivo = get_object_or_404(GarantiaArchivo, pk=archivo_id, garantia=garantia)
    fh = archivo.archivo.open("rb")
    return FileResponse(fh, as_attachment=True, filename=archivo.archivo.name.split("/")[-1])


@login_required
@admin_required
@require_POST
def agregar_archivos(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
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
    garantia = get_object_or_404(Garantia, pk=pk)
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
    garantia = get_object_or_404(Garantia, pk=pk)
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
    garantia = get_object_or_404(Garantia, pk=pk)
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
