from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST, require_http_methods

# pyrefly: ignore [missing-import]
from .forms import (
    OperacionArchivosForm,
    OperacionArchivoUploadForm,
    OperacionComentarioForm,
    OperacionEditarForm,
    OperacionEnlaceCreateForm,
    OperacionEnlaceForm,
    OperacionEtiquetaAssignForm,
    OperacionEtiquetaCreateForm,
    OperacionForm,
    OperacionInlineCreateForm,
    OperacionOpcionCreateForm,
    OperacionOpcionesSectionForm,
    OperacionQuickEditForm,
)
from .models import (
    Operacion,
    OperacionArchivo,
    OperacionComentario,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)

User = get_user_model()


# El orden del tablero es una regla de presentacion compartida por la vista y
# los parciales. No modifica los estados persistidos en el modelo.
COLUMNAS = list(Operacion.Estado.choices)


def _estado_label(estado):
    return dict(Operacion.Estado.choices).get(estado, estado)


def _estados_disponibles():
    return [choice[0] for choice in Operacion.Estado.choices]


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


def _operacion_queryset():
    return (
        Operacion.objects.select_related("cliente", "creado_por")
        .prefetch_related("asignados", "etiquetas")
        .annotate(
            comentarios_count=Count("comentarios", distinct=True),
            archivos_count=Count("archivos", distinct=True),
            enlaces_count=Count("enlaces", distinct=True),
        )
        .order_by("-fecha_creacion", "-id")
    )


def _construir_columnas(operaciones):
    """Agrupa las operaciones para que el tablero solo reciba datos de UI."""
    operaciones_por_estado = {estado: [] for estado, _label in COLUMNAS}
    for operacion in operaciones:
        operaciones_por_estado.setdefault(operacion.estado, []).append(operacion)

    return [
        {
            "posicion": posicion,
            "estado": estado,
            "titulo": titulo,
            "items": operaciones_por_estado.get(estado, []),
            "count": len(operaciones_por_estado.get(estado, [])),
        }
        for posicion, (estado, titulo) in enumerate(COLUMNAS, start=1)
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


def _puede_modificar_operacion(user, operacion):
    if not user.is_authenticated:
        return False
    if user.is_superuser or operacion.creado_por_id == user.id:
        return True
    return operacion.asignados.filter(id=user.id).exists()


def _get_usuario_filter(request):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id.isdigit():
        return None
    return User.objects.filter(pk=int(usuario_id)).first()


def _usuarios_filtro(selected_user_id=None):
    usuarios = User.objects.filter(is_active=True).order_by("first_name", "last_name", "username", "id")
    return [
        {
            "nombre": usuario.first_name or usuario.get_full_name() or usuario.username,
            "id": usuario.id,
            "seleccionado": usuario.id == selected_user_id,
        }
        for usuario in usuarios
    ]


def _contexto_modal_operacion(operacion, form=None, archivos_form=None, enlace_form=None, comentario_form=None):
    asignados = [usuario for usuario in operacion.asignados.all() if _nombre_corto_usuario(usuario)]
    comentarios = list(_comentarios_queryset(operacion))
    archivos = list(_archivos_queryset(operacion))
    enlaces = list(_enlaces_queryset(operacion))
    etiquetas = list(_etiquetas_queryset(operacion))
    opciones = list(_opciones_queryset(operacion))
    return {
        "operacion": operacion,
        "form": form or OperacionEditarForm(instance=operacion),
        "archivos_form": archivos_form or OperacionArchivoUploadForm(),
        "archivos": archivos,
        "files_count": len(archivos),
        "enlace_form": enlace_form or OperacionEnlaceCreateForm(),
        "enlaces": enlaces,
        "links_count": len(enlaces),
        "etiquetas": etiquetas,
        "etiquetas_count": len(etiquetas),
        "etiquetas_form": OperacionEtiquetaAssignForm(),
        "etiqueta_create_form": OperacionEtiquetaCreateForm(),
        "opciones": opciones,
        "opciones_count": len(opciones),
        "opciones_form": OperacionOpcionesSectionForm(instance=operacion),
        "opcion_create_form": OperacionOpcionCreateForm(),
        "comentario_form": comentario_form or OperacionComentarioForm(),
        "comentarios": comentarios,
        "comentarios_count": len(comentarios),
        "nombre_corto_asignados": [_nombre_corto_usuario(usuario) for usuario in asignados],
        "iniciales_asignados": [_iniciales_usuario(usuario) for usuario in asignados],
        "asignados_count": len(asignados),
    }


def _comentarios_queryset(operacion):
    return operacion.comentarios.select_related("usuario").order_by("-fecha", "-id")


def _render_comentarios_section(request, operacion, comentario_form=None):
    comentarios = list(_comentarios_queryset(operacion))
    return render_to_string(
        "operaciones/_comentarios_section.html",
        {
            "operacion": operacion,
            "comentario_form": comentario_form or OperacionComentarioForm(),
            "comentarios": comentarios,
            "comentarios_count": len(comentarios),
        },
        request=request,
    )


def _archivos_queryset(operacion):
    return operacion.archivos.order_by("-fecha", "-id")


def _render_archivos_section(request, operacion, archivos_form=None):
    archivos = list(_archivos_queryset(operacion))
    return render_to_string(
        "operaciones/_archivos_section.html",
        {
            "operacion": operacion,
            "archivos_form": archivos_form or OperacionArchivoUploadForm(),
            "archivos": archivos,
            "files_count": len(archivos),
        },
        request=request,
    )


def _enlaces_queryset(operacion):
    return operacion.enlaces.order_by("-fecha", "-id")


def _render_enlaces_section(request, operacion, enlace_form=None, return_count=False):
    enlaces = list(_enlaces_queryset(operacion))
    html = render_to_string(
        "operaciones/_enlaces_section.html",
        {
            "operacion": operacion,
            "enlace_form": enlace_form or OperacionEnlaceCreateForm(),
            "enlaces": enlaces,
            "links_count": len(enlaces),
        },
        request=request,
    )
    if return_count:
        return html, len(enlaces)
    return html


def _etiquetas_queryset(operacion):
    return operacion.etiquetas.order_by("nombre", "id")


def _etiquetas_data(etiquetas):
    return [
        {"id": etiqueta.id, "nombre": etiqueta.nombre, "color": etiqueta.color}
        for etiqueta in etiquetas
    ]


def _render_etiquetas_section(
    request,
    operacion,
    etiquetas_form=None,
    etiqueta_create_form=None,
    return_data=False,
):
    etiquetas = list(_etiquetas_queryset(operacion))
    html = render_to_string(
        "operaciones/_etiquetas_section.html",
        {
            "operacion": operacion,
            "etiquetas": etiquetas,
            "etiquetas_count": len(etiquetas),
            "etiquetas_form": etiquetas_form or OperacionEtiquetaAssignForm(),
            "etiqueta_create_form": etiqueta_create_form or OperacionEtiquetaCreateForm(),
        },
        request=request,
    )
    if return_data:
        return html, _etiquetas_data(etiquetas)
    return html


def _opciones_queryset(operacion):
    return operacion.opciones.order_by("nombre", "id")


def _opciones_data(opciones):
    return [{"id": opcion.id, "nombre": opcion.nombre} for opcion in opciones]


def _render_opciones_section(
    request,
    operacion,
    opciones_form=None,
    opcion_create_form=None,
    return_data=False,
):
    opciones = list(_opciones_queryset(operacion))
    html = render_to_string(
        "operaciones/_opciones_section.html",
        {
            "operacion": operacion,
            "opciones": opciones,
            "opciones_count": len(opciones),
            "opciones_form": opciones_form or OperacionOpcionesSectionForm(instance=operacion),
            "opcion_create_form": opcion_create_form or OperacionOpcionCreateForm(),
        },
        request=request,
    )
    if return_data:
        return html, _opciones_data(opciones)
    return html


def _guardar_adjuntos_enlaces(request, operacion, enlace_form):
    for archivo in request.FILES.getlist("archivos"):
        OperacionArchivo.objects.create(operacion=operacion, archivo=archivo, subido_por=request.user)

    if (enlace_form.cleaned_data.get("titulo") or "").strip() and (enlace_form.cleaned_data.get("url") or "").strip():
        enlace = enlace_form.save(commit=False)
        enlace.operacion = operacion
        enlace.creado_por = request.user
        enlace.save()


def _render_card_html(request, operacion):
    # Las respuestas AJAX reutilizan la misma tarjeta enriquecida del tablero.
    operacion = _operacion_queryset().filter(pk=operacion.pk).first() or operacion
    return render_to_string(
        "operaciones/_operacion_card.html",
        {
            "operacion": operacion,
            "comentario_form": OperacionComentarioForm(),
            "estados": COLUMNAS,
        },
        request=request,
    )


def _render_inline_create_form(request, form, estado):
    return render_to_string(
        "operaciones/_inline_create_form.html",
        {"form": form, "estado": estado},
        request=request,
    )


def _render_quick_edit_form(request, operacion, form=None):
    return render_to_string(
        "operaciones/_quick_edit_form.html",
        {
            "operacion": operacion,
            "form": form or OperacionQuickEditForm(instance=operacion),
        },
        request=request,
    )


@login_required
def panel_operaciones(request):

    usuario = _get_usuario_filter(request)

    operaciones = _operacion_queryset()

    # limpiar vacíos y valores inválidos
    if usuario:
        operaciones = (
            operaciones
            .filter(
                asignados__id=usuario.id
            )
            .distinct()
        )

    
    columnas = _construir_columnas(operaciones)

    return render(request, "operaciones/panel_operaciones.html", {
        "columnas": columnas,
        "estados": COLUMNAS,
        "inline_form": OperacionInlineCreateForm(),
        "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
        "current": "panel_operaciones",
    })


@login_required
def crear_operacion(request):
    next_url = _safe_next_url(request)
    if request.method == "POST":
        form = OperacionForm(request.POST)
        archivos_form = OperacionArchivosForm(request.POST, request.FILES)
        enlace_form = OperacionEnlaceForm(request.POST, prefix="enlace")
        if form.is_valid():
            operacion = form.save(commit=False)
            operacion.creado_por = request.user
            operacion.save()
            form.save_m2m()
            if archivos_form.is_valid() and enlace_form.is_valid():
                _guardar_adjuntos_enlaces(request, operacion, enlace_form)
            
            if _es_ajax(request):
                return JsonResponse({
                    "success": True,
                    "html": _render_card_html(request, operacion),
                    "estado": operacion.estado,
                    "id": operacion.id,
                })
            
            messages.success(request, "Operación creada exitosamente.")
            if next_url:
                return redirect(next_url)
            return redirect("operaciones:panel_operaciones")
    else:
        form = OperacionForm()
        archivos_form = OperacionArchivosForm()
        enlace_form = OperacionEnlaceForm(prefix="enlace")
    
    return render(
        request,
        "operaciones/crear_operacion.html",
        {"form": form, "archivos_form": archivos_form, "enlace_form": enlace_form, "current": "crear_operacion", "next_url": next_url},
    )


@login_required
@require_POST
def crear_operacion_inline(request):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    estado = (request.POST.get("estado") or "").strip()
    if estado not in _estados_disponibles():
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Estado invalido."]}},
            status=400,
        )

    form = OperacionInlineCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, estado),
            },
            status=400,
        )

    operacion = form.save(commit=False)
    operacion.estado = estado
    operacion.creado_por = request.user
    operacion.save()

    return JsonResponse(
        {
            "ok": True,
            "html": _render_card_html(request, operacion),
            "id": operacion.id,
            "estado": operacion.estado,
        }
    )


@login_required
@require_http_methods(["GET", "POST"])
def editar_operacion_rapida(request, operacion_id):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")

    if request.method == "GET":
        return JsonResponse(
            {"ok": True, "html": _render_quick_edit_form(request, operacion)}
        )

    form = OperacionQuickEditForm(request.POST, instance=operacion)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_quick_edit_form(request, operacion, form),
            },
            status=400,
        )

    operacion = form.save()
    return JsonResponse(
        {
            "ok": True,
            "id": operacion.id,
            "html": _render_card_html(request, operacion),
        }
    )


@login_required
def detalle_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    contexto = _contexto_modal_operacion(operacion)
    html = render_to_string("operaciones/_detalle_modal_content.html", contexto, request=request)
    return JsonResponse({"html": html})


@login_required
def detalle_operacion_modal(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if request.method == "POST":
        form = OperacionEditarForm(request.POST, request.FILES, instance=operacion)
        if form.is_valid():
            original = Operacion.objects.get(id=operacion_id)
            for campo in form.fields:
                valor = form.cleaned_data.get(campo)
                if valor in (None, '', [], {}) or (hasattr(valor, 'exists') and not valor.exists()):
                    actual = getattr(original, campo)
                    if hasattr(actual, 'all'):
                        form.cleaned_data[campo] = actual.all()
                    else:
                        setattr(form.instance, campo, actual)
            obj = form.save(commit=False)
            obj.save()
            form.save_m2m()

            if _es_ajax(request):
                return JsonResponse({
                    "success": True,
                    "html": _render_card_html(request, operacion),
                })
            messages.success(request, "Operación actualizada exitosamente.")
            return redirect("operaciones:panel_operaciones")
    else:
        form = OperacionEditarForm(instance=operacion)

    contexto = _contexto_modal_operacion(operacion, form=form)
    if _es_ajax(request):
        html = render_to_string("operaciones/_detalle_modal_content.html", contexto, request=request)
        return JsonResponse({"html": html})
    return render(request, "operaciones/_detalle_modal_content.html", contexto)


@login_required
@require_http_methods(["POST"])
def editar_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operación.")
    form = OperacionEditarForm(request.POST, request.FILES, instance=operacion)

    if form.is_valid():
        original = Operacion.objects.get(id=operacion_id)
        for campo in form.fields:
            valor = form.cleaned_data.get(campo)
            if valor in (None, '', [], {}) or (hasattr(valor, 'exists') and not valor.exists()):
                actual = getattr(original, campo)
                if hasattr(actual, 'all'):
                    form.cleaned_data[campo] = actual.all()
                else:
                    setattr(form.instance, campo, actual)
        obj = form.save(commit=False)
        obj.save()
        form.save_m2m()

        operacion.refresh_from_db()

        if _es_ajax(request):
            return JsonResponse({
                "success": True,
                "html": _render_card_html(request, operacion),
            })

        messages.success(request, "Operación actualizada exitosamente.")
        return redirect("operaciones:panel_operaciones")

    contexto = _contexto_modal_operacion(operacion, form=form)
    if _es_ajax(request):
        html = render_to_string("operaciones/_detalle_modal_content.html", contexto, request=request)
        return JsonResponse({"html": html})
    return render(request, "operaciones/_detalle_modal_content.html", contexto)


@login_required
@require_POST
def agregar_comentario(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para comentar esta operación.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionComentarioForm(request.POST)
    if form.is_valid():
        OperacionComentario.objects.create(
            operacion=operacion,
            usuario=request.user,
            comentario=form.cleaned_data["comentario"],
        )
        return JsonResponse(
            {
                "success": True,
                "id": operacion.id,
                "comments_html": _render_comentarios_section(request, operacion),
                "comments_count": operacion.comentarios.count(),
            }
        )

    return JsonResponse(
        {
            "success": False,
            "id": operacion.id,
            "comments_html": _render_comentarios_section(request, operacion, form),
            "comments_count": operacion.comentarios.count(),
        },
        status=400,
    )


@login_required
@require_POST
def agregar_archivo(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operación.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionArchivoUploadForm(request.POST, request.FILES)
    if form.is_valid():
        for archivo in form.cleaned_data["archivos"]:
            OperacionArchivo.objects.create(
                operacion=operacion,
                archivo=archivo,
                subido_por=request.user,
            )
        return JsonResponse(
            {
                "success": True,
                "id": operacion.id,
                "files_html": _render_archivos_section(request, operacion),
                "files_count": operacion.archivos.count(),
            }
        )

    return JsonResponse(
        {
            "success": False,
            "id": operacion.id,
            "files_html": _render_archivos_section(request, operacion, form),
            "files_count": operacion.archivos.count(),
        },
        status=400,
    )


@login_required
@require_POST
def eliminar_archivo(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar archivos de esta operación.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    archivo_id = request.POST.get("archivo_id")
    archivo = get_object_or_404(OperacionArchivo, id=archivo_id, operacion=operacion)
    archivo.delete()
    return JsonResponse(
        {
            "success": True,
            "id": operacion.id,
            "files_html": _render_archivos_section(request, operacion),
            "files_count": operacion.archivos.count(),
        }
    )


@login_required
@require_POST
def agregar_enlace(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionEnlaceCreateForm(request.POST)
    if form.is_valid():
        enlace = form.save(commit=False)
        enlace.operacion = operacion
        enlace.creado_por = request.user
        enlace.save()
        links_html, links_count = _render_enlaces_section(request, operacion, return_count=True)
        return JsonResponse(
            {
                "success": True,
                "id": operacion.id,
                "links_html": links_html,
                "links_count": links_count,
            }
        )

    links_html, links_count = _render_enlaces_section(
        request, operacion, form, return_count=True
    )
    return JsonResponse(
        {
            "success": False,
            "id": operacion.id,
            "links_html": links_html,
            "links_count": links_count,
        },
        status=400,
    )


@login_required
@require_POST
def eliminar_enlace(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar enlaces de esta operación.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    enlace_id = request.POST.get("enlace_id")
    enlace = get_object_or_404(OperacionEnlace, id=enlace_id, operacion=operacion)
    enlace.delete()
    links_html, links_count = _render_enlaces_section(request, operacion, return_count=True)
    return JsonResponse(
        {
            "success": True,
            "id": operacion.id,
            "links_html": links_html,
            "links_count": links_count,
        }
    )


def _etiquetas_response(request, operacion, *, etiquetas_form=None, etiqueta_create_form=None, success=True, status=200):
    tags_html, tags = _render_etiquetas_section(
        request,
        operacion,
        etiquetas_form=etiquetas_form,
        etiqueta_create_form=etiqueta_create_form,
        return_data=True,
    )
    return JsonResponse(
        {
            "success": success,
            "id": operacion.id,
            "tags_html": tags_html,
            "tags": tags,
            "tags_count": len(tags),
        },
        status=status,
    )


@login_required
@require_POST
def agregar_etiqueta_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionEtiquetaAssignForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, operacion, etiquetas_form=form, success=False, status=400)

    operacion.etiquetas.add(form.cleaned_data["etiqueta"])
    return _etiquetas_response(request, operacion)


@login_required
@require_POST
def crear_etiqueta_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionEtiquetaCreateForm(request.POST)
    if not form.is_valid():
        return _etiquetas_response(request, operacion, etiqueta_create_form=form, success=False, status=400)

    nombre = form.cleaned_data["nombre"]
    etiqueta = OperacionEtiqueta.objects.filter(nombre__iexact=nombre).first()
    if etiqueta is None:
        etiqueta = OperacionEtiqueta.objects.create(nombre=nombre, color=form.cleaned_data["color"])
    operacion.etiquetas.add(etiqueta)
    return _etiquetas_response(request, operacion)


@login_required
@require_POST
def quitar_etiqueta_operacion(request, operacion_id, etiqueta_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    etiqueta = get_object_or_404(OperacionEtiqueta, id=etiqueta_id)
    operacion.etiquetas.remove(etiqueta)
    return _etiquetas_response(request, operacion)


def _opciones_response(request, operacion, *, opciones_form=None, opcion_create_form=None, success=True, status=200):
    options_html, options = _render_opciones_section(
        request,
        operacion,
        opciones_form=opciones_form,
        opcion_create_form=opcion_create_form,
        return_data=True,
    )
    return JsonResponse(
        {
            "success": success,
            "id": operacion.id,
            "options_html": options_html,
            "options": options,
            "options_count": len(options),
        },
        status=status,
    )


@login_required
@require_POST
def actualizar_opciones_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionOpcionesSectionForm(request.POST, instance=operacion)
    if not form.is_valid():
        return _opciones_response(request, operacion, opciones_form=form, success=False, status=400)

    operacion.opciones.set(form.cleaned_data["opciones"])
    return _opciones_response(request, operacion)


@login_required
@require_POST
def crear_opcion_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionOpcionCreateForm(request.POST)
    if not form.is_valid():
        return _opciones_response(request, operacion, opcion_create_form=form, success=False, status=400)

    opcion, _created = OperacionOpcion.objects.get_or_create(nombre=form.cleaned_data["nombre"])
    operacion.opciones.add(opcion)
    return _opciones_response(request, operacion)


@login_required
@require_POST
def quitar_opcion_operacion(request, operacion_id, opcion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    opcion = get_object_or_404(OperacionOpcion, id=opcion_id)
    operacion.opciones.remove(opcion)
    return _opciones_response(request, operacion)


@login_required
@require_POST
def crear_opcion(request):
    nombre = (request.POST.get("nombre") or "").strip()
    if not nombre:
        return JsonResponse({"success": False, "error": "Nombre requerido"}, status=400)

    opcion, _ = OperacionOpcion.objects.get_or_create(nombre=nombre)
    return JsonResponse({"success": True, "id": opcion.id, "nombre": opcion.nombre})


@login_required
@require_POST
def crear_etiqueta(request):
    nombre = (request.POST.get("nombre") or "").strip()
    color = (request.POST.get("color") or "").strip() or "#3E9FA2"
    if not nombre:
        return JsonResponse({"success": False, "error": "Nombre requerido"}, status=400)

    etiqueta, created = OperacionEtiqueta.objects.get_or_create(nombre=nombre, defaults={"color": color})
    if not created and etiqueta.color != color and color.startswith("#") and len(color) == 7:
        etiqueta.color = color
        etiqueta.save(update_fields=["color"])
    return JsonResponse({"success": True, "id": etiqueta.id, "nombre": etiqueta.nombre, "color": etiqueta.color})


@login_required
@require_POST
def editar_etiqueta(request, etiqueta_id):
    etiqueta = get_object_or_404(OperacionEtiqueta, id=etiqueta_id)
    nombre = (request.POST.get("nombre") or "").strip()
    color = (request.POST.get("color") or "").strip()
    if not nombre:
        return JsonResponse({"success": False, "error": "Nombre requerido"}, status=400)
    if not color or not color.startswith("#") or len(color) != 7:
        return JsonResponse({"success": False, "error": "Color inválido"}, status=400)

    etiqueta.nombre = nombre
    etiqueta.color = color
    etiqueta.save(update_fields=["nombre", "color"])
    return JsonResponse({"success": True, "id": etiqueta.id, "nombre": etiqueta.nombre, "color": etiqueta.color})


@login_required
@require_POST
def eliminar_etiqueta(request, etiqueta_id):
    etiqueta = get_object_or_404(OperacionEtiqueta, id=etiqueta_id)
    etiqueta.delete()
    # Si se proporciona un objeto en el POST (operacion abierta), devolver html actualizado
    obj_id = request.POST.get("obj_id")
    if _es_ajax(request) and obj_id:
        try:
            operacion = get_object_or_404(Operacion, id=int(obj_id))
            html = render_to_string("operaciones/_detalle_modal_content.html", _contexto_modal_operacion(operacion), request=request)
            card_html = _render_card_html(request, operacion)
            return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": operacion.id})
        except Exception:
            pass
    return JsonResponse({"success": True})


@login_required
@require_POST
def mover_operacion(
    request,
    operacion_id
):

    if request.method=="POST":

        operacion=get_object_or_404(
           Operacion,
           id=operacion_id
        )
        if not _puede_modificar_operacion(request.user, operacion):
            raise PermissionDenied("No tienes permisos para mover esta operación.")

        estado=request.POST.get(
           "estado"
        )

        if estado not in _estados_disponibles():
            return JsonResponse(
                {"status": "error", "error": "Estado invalido."},
                status=400,
            )

        if estado:

            operacion.estado=estado

            operacion.save(update_fields=["estado"])

            return JsonResponse({
                "status":"ok",
                "id": operacion.id,
                "estado": operacion.estado,
                "estado_label": _estado_label(operacion.estado),
            })

    return JsonResponse({
        "status":"error"
    })

@login_required
@require_POST
def eliminar_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar esta operación.")
    operacion.delete()
    
    if _es_ajax(request):
        return JsonResponse({"success": True, "redirect": True, "id": operacion_id})
    
    messages.success(request, "Operación eliminada exitosamente.")
    return redirect("operaciones:panel_operaciones")
