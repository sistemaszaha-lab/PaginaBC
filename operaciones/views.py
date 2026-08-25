import logging

from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, F, Prefetch, Q, Window
from django.db import IntegrityError, transaction
from django.db.models.functions import RowNumber
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils.text import slugify
from django.views.decorators.http import require_GET, require_POST, require_http_methods

# pyrefly: ignore [missing-import]
from .forms import (
    OperacionArchivosForm,
    OperacionArchivoUploadForm,
    OperacionComentarioForm,
    OperacionColumnaCreateForm,
    OperacionColumnaUpdateForm,
    OperacionEditarForm,
    OperacionElementoAccionCreateForm,
    OperacionElementoAccionUpdateForm,
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
    OperacionColumna,
    OperacionComentario,
    OperacionElementoAccion,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)
from solicitudes.models import Referencia
from solicitudes_app.trash import enviar_a_papelera
from .services import (
    copiar_operacion_a_columna,
    obtener_initial_operacion_desde_referencia,
)
from cuenta_gastos.services import crear_cuenta_gastos_desde_operacion_si_corresponde

User = get_user_model()
logger = logging.getLogger(__name__)


COLUMNAS_INICIALES = (
    (Operacion.Estado.PENDIENTE, "Pendientes"),
    (Operacion.Estado.SEGUROS, "Seguros"),
    (Operacion.Estado.PRUEBA_VALOR, "Prueba de valor"),
    (Operacion.Estado.EN_ADUANA, "En aduana"),
    (Operacion.Estado.TRANSITO_NACIONAL, "Tránsito nacional"),
    (Operacion.Estado.COORDINAR_PICKUP, "Pick up"),
    (Operacion.Estado.TRANSITO_INTERNACIONAL, "Tránsito internacional"),
    (Operacion.Estado.EXPEDIENTE_CG, "Expediente CG"),
    (Operacion.Estado.SOLICITUD_CUENTA_GASTOS, "Solicitud de cuenta gastos"),
)
OPERACION_ORDERING = ("posicion", "-fecha_creacion", "-id")


def _columnas_activas_queryset():
    return OperacionColumna.objects.filter(activa=True).order_by("orden", "id")


def _columnas_activas():
    return list(_columnas_activas_queryset())


def _primer_columna_activa():
    return _columnas_activas_queryset().first()


def _columnas_estado_choices():
    return [(columna.codigo, columna.nombre) for columna in _columnas_activas()]


def _buscar_columna_activa_por_codigo(codigo: str):
    return _columnas_activas_queryset().filter(codigo=codigo).first()


def _buscar_columna_destino(request):
    columna_id = (request.POST.get("columna_id") or "").strip()
    if columna_id.isdigit():
        return _columnas_activas_queryset().filter(pk=int(columna_id)).first()
    estado = (request.POST.get("estado") or "").strip()
    if estado:
        return _buscar_columna_activa_por_codigo(estado)
    return None


def _estado_label(estado):
    columna = _buscar_columna_activa_por_codigo(estado)
    if columna is not None:
        return columna.nombre
    return dict(COLUMNAS_INICIALES).get(estado, estado)


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
    while OperacionColumna.objects.filter(codigo=candidato).exists():
        candidato = f"{base}_{indice}"
        indice += 1
    return candidato


def _siguiente_orden_columna() -> int:
    ultima = OperacionColumna.objects.order_by("-orden", "-id").first()
    return (ultima.orden + 1) if ultima is not None else 1


def _column_context(*, columna: OperacionColumna, items, count: int, loaded: int):
    return {
        "id": columna.pk,
        "columna_id": columna.pk,
        "codigo": columna.codigo,
        "estado": columna.codigo,
        "nombre": columna.nombre,
        "titulo": columna.nombre,
        "estado_texto": columna.nombre,
        "items": items,
        "count": count,
        "loaded": loaded,
        "has_more": False,
        "remaining": 0,
        "load_url": "",
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
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in (request.headers.get("Accept") or "")
    )


def _operacion_queryset():
    return (
        Operacion.objects.filter(eliminado_en__isnull=True)
        .select_related("cliente", "creado_por", "columna")
        .prefetch_related(
            "asignados",
            "etiquetas",
            Prefetch(
                "elementos_accion",
                queryset=OperacionElementoAccion.objects.order_by("orden", "id"),
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
    queryset = _operacion_queryset().filter(estado__in=codigos_activos).filter(
        Q(columna__activa=True) | Q(columna__isnull=True)
    )
    if usuario is not None:
        queryset = queryset.filter(asignados__id=usuario.id).distinct()
    return queryset.order_by(*OPERACION_ORDERING)


def _columnas_kanban(usuario=None):
    columnas = _columnas_activas()
    operaciones = list(
        _board_queryset(usuario)
        .annotate(
            posicion_columna=Window(
                expression=RowNumber(),
                partition_by=[F("estado")],
                order_by=[
                    F("posicion").asc(),
                    F("fecha_creacion").desc(),
                    F("id").desc(),
                ]
            ),
            total_columna=Window(
                expression=Count("id"),
                partition_by=[F("estado")],
            ),
        )
    )
    items_por_estado = {columna.codigo: [] for columna in columnas}
    totales = {columna.codigo: 0 for columna in columnas}
    for operacion in operaciones:
        if operacion.estado in items_por_estado:
            items_por_estado[operacion.estado].append(operacion)
            totales[operacion.estado] = operacion.total_columna

    return [
        _column_context(
            columna=columna,
            items=items_por_estado[columna.codigo],
            count=totales[columna.codigo],
            loaded=len(items_por_estado[columna.codigo]),
        )
        for columna in columnas
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


def _puede_mover_operacion(user):
    """Los usuarios autenticados del sistema son administradores o ejecutivos."""
    return bool(user and user.is_authenticated)


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
    usuario = User.objects.filter(pk=int(raw_values[0])).first()
    if usuario is None:
        return None, JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    return usuario, None



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


def _elementos_accion_queryset(operacion):
    prefetched = getattr(operacion, "_prefetched_objects_cache", {}).get(
        "elementos_accion"
    )
    if prefetched is not None:
        return list(prefetched)
    return list(operacion.elementos_accion.order_by("orden", "id"))


def _elementos_accion_resumen(elementos):
    total = len(elementos)
    completados = sum(1 for elemento in elementos if elemento.completado)
    return {
        "completados": completados,
        "total": total,
    }


def _render_elemento_accion_item(request, elemento):
    return render_to_string(
        "operaciones/_elemento_accion_item.html",
        {"elemento": elemento},
        request=request,
    )


def _render_elementos_accion_section(
    request,
    operacion,
    *,
    create_form=None,
    update_form=None,
):
    elementos = _elementos_accion_queryset(operacion)
    resumen = _elementos_accion_resumen(elementos)
    return render_to_string(
        "operaciones/_elementos_accion_section.html",
        {
            "operacion": operacion,
            "elementos_accion": elementos,
            "elementos_accion_resumen": resumen,
            "elemento_accion_form": create_form or OperacionElementoAccionCreateForm(),
            "elemento_accion_update_form": update_form or OperacionElementoAccionUpdateForm(),
        },
        request=request,
    )


def _contexto_modal_operacion(operacion, form=None, archivos_form=None, enlace_form=None, comentario_form=None):
    asignados = [usuario for usuario in operacion.asignados.all() if _nombre_corto_usuario(usuario)]
    comentarios = list(_comentarios_queryset(operacion))
    archivos = list(_archivos_queryset(operacion))
    enlaces = list(_enlaces_queryset(operacion))
    etiquetas = list(_etiquetas_queryset(operacion))
    elementos_accion = _elementos_accion_queryset(operacion)
    elementos_accion_resumen = _elementos_accion_resumen(elementos_accion)
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
        "elementos_accion": elementos_accion,
        "elementos_accion_resumen": elementos_accion_resumen,
        "elemento_accion_form": OperacionElementoAccionCreateForm(),
        "elemento_accion_update_form": OperacionElementoAccionUpdateForm(),
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


def _guardar_archivos_y_enlaces_inline(request, operacion, form):
    for archivo in request.FILES.getlist("archivos"):
        OperacionArchivo.objects.create(
            operacion=operacion,
            archivo=archivo,
            subido_por=request.user,
        )

    for enlace_data in form.cleaned_data.get("enlaces_payload", []):
        OperacionEnlace.objects.create(
            operacion=operacion,
            titulo=enlace_data["titulo"],
            url=enlace_data["url"],
            creado_por=request.user,
        )


def _estado_inicial_operacion():
    return _primer_columna_activa()


def _columna_manual_permitida():
    return _primer_columna_activa()


def _column_count(columna: OperacionColumna) -> int:
    return Operacion.objects.filter(
        Q(columna=columna) | Q(columna__isnull=True, estado=columna.codigo)
    ).filter(eliminado_en__isnull=True).count()


def _es_columna_base(columna: OperacionColumna) -> bool:
    return columna.codigo in {codigo for codigo, _nombre in COLUMNAS_INICIALES}


def _get_operacion_para_copia(pk: int) -> Operacion:
    return get_object_or_404(
        Operacion.objects.filter(eliminado_en__isnull=True).select_related("columna", "cliente", "creado_por")
        .prefetch_related("asignados", "etiquetas", "opciones"),
        pk=pk,
    )


def _render_card_html(request, operacion):
    # Las respuestas AJAX reutilizan la misma tarjeta enriquecida del tablero.
    operacion = _operacion_queryset().filter(pk=operacion.pk).first() or operacion
    return render_to_string(
        "operaciones/_operacion_card.html",
        {
            "operacion": operacion,
            "comentario_form": OperacionComentarioForm(),
            "estados": _columnas_estado_choices(),
        },
        request=request,
    )


def _render_inline_create_form(request, form, columna):
    return render_to_string(
        "operaciones/_inline_create_form.html",
        {
            "form": form,
            "estado": columna.codigo,
            "estado_label": columna.nombre,
            "columna": columna,
        },
        request=request,
    )


def _json_error(error_code, *, message=None, errors=None, status=400, **extra):
    payload = {"ok": False, "error_code": error_code}
    if status == 400:
        payload["status"] = "error"
    if message:
        payload["message"] = message
    if errors is not None:
        payload["errors"] = errors
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _render_quick_edit_form(request, operacion, form=None):
    return render_to_string(
        "operaciones/_quick_edit_form.html",
        {
            "operacion": operacion,
            "form": form or OperacionQuickEditForm(instance=operacion),
        },
        request=request,
    )


def _preservar_campos_no_enviados(form, post_data, *field_names):
    for field_name in field_names:
        present_marker = f"{field_name}_present"
        if present_marker not in post_data and field_name not in post_data:
            form.fields.pop(field_name, None)


@login_required
def panel_operaciones(request):
    usuario = _get_usuario_filter(request)
    columnas = _columnas_kanban(usuario)

    return render(request, "operaciones/panel_operaciones.html", {
        "columnas": columnas,
        "estados": _columnas_estado_choices(),
        "columnas_activas": _columnas_activas(),
        "columna_create_form": OperacionColumnaCreateForm(),
        "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
        "current": "panel_operaciones",
        "today": timezone.localdate(),
        "panel_config": {
            "inlineCreateUrl": reverse("operaciones:crear_operacion_inline"),
            "inlineFormUrl": reverse("operaciones:formulario_operacion_inline"),
            "boardUrl": reverse("operaciones:tablero_partial"),
            "columnCreateUrl": reverse("operaciones:columna_crear"),
            "columnReorderUrl": reverse("operaciones:columna_reordenar"),
        },
    })


@login_required
@require_GET
def tablero_partial(request):
    usuario = _get_usuario_filter(request)
    return render(
        request,
        "operaciones/_tablero.html",
        {
            "columnas": _columnas_kanban(usuario),
            "estados": _columnas_estado_choices(),
            "today": timezone.localdate(),
        },
    )



@login_required
def crear_operacion(request):
    next_url = _safe_next_url(request)
    columna_inicial = _estado_inicial_operacion()
    if columna_inicial is None:
        raise PermissionDenied("No hay columnas disponibles en operaciones.")
    if request.method == "POST":
        form = OperacionForm(request.POST)
        archivos_form = OperacionArchivosForm(request.POST, request.FILES)
        enlace_form = OperacionEnlaceForm(request.POST, prefix="enlace")
        if form.is_valid():
            with transaction.atomic():
                operacion = form.save(commit=False)
                operacion.creado_por = request.user
                operacion.columna = columna_inicial
                operacion.estado = columna_inicial.codigo
                operacion.save()
                form.save_m2m()
                if archivos_form.is_valid() and enlace_form.is_valid():
                    _guardar_adjuntos_enlaces(request, operacion, enlace_form)
                crear_cuenta_gastos_desde_operacion_si_corresponde(
                    operacion, creado_por=request.user
                )
            
            if _es_ajax(request):
                return JsonResponse({
                    "success": True,
                    "html": _render_card_html(request, operacion),
                    "estado": operacion.estado,
                    "id": operacion.id,
                })
            
            messages.success(request, "OperaciÃ³n creada exitosamente.")
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
def enviar_referencia_a_operaciones(request, pk):
    referencia = get_object_or_404(Referencia.objects.filter(eliminado_en__isnull=True), pk=pk)
    # La vista ya estÃ¡ protegida por login_required. La creaciÃ³n manual de
    # Operaciones admite a cualquier usuario autenticado, por lo que la
    # conversiÃ³n mantiene la misma regla para administradores y ejecutivos.
    if getattr(referencia, "operacion_generada", None):
        messages.info(request, "Esta referencia ya fue enviada a Operaciones.")
        return redirect("operaciones:panel_operaciones")

    if request.method == "POST":
        form = OperacionForm(request.POST)
        archivos_form = OperacionArchivosForm(request.POST, request.FILES)
        enlace_form = OperacionEnlaceForm(request.POST, prefix="enlace")
        if form.is_valid():
            try:
                with transaction.atomic():
                    operacion = form.save(commit=False)
                    operacion.creado_por = request.user
                    operacion.referencia_origen = referencia
                    operacion.columna = _buscar_columna_activa_por_codigo(
                        Operacion.Estado.COORDINAR_PICKUP
                    )
                    # El estado se impone en el servidor para que un POST
                    # manipulado no pueda sacar la conversiÃ³n de Pick up.
                    operacion.estado = Operacion.Estado.COORDINAR_PICKUP
                    operacion.save()
                    form.save_m2m()
                    if archivos_form.is_valid() and enlace_form.is_valid():
                        _guardar_adjuntos_enlaces(request, operacion, enlace_form)
            except IntegrityError:
                messages.error(request, "Esta referencia ya fue enviada a Operaciones.")
                return redirect("operaciones:panel_operaciones")
            messages.success(request, "La referencia se enviÃ³ correctamente a Operaciones en la columna Pick up.")
            return redirect("operaciones:panel_operaciones")
    else:
        form = OperacionForm(initial=obtener_initial_operacion_desde_referencia(referencia))
        archivos_form = OperacionArchivosForm()
        enlace_form = OperacionEnlaceForm(prefix="enlace")

    return render(request, "operaciones/crear_operacion.html", {
        "form": form, "archivos_form": archivos_form, "enlace_form": enlace_form,
        "current": "crear_operacion", "referencia_origen": referencia,
    })


@login_required
@require_GET
def formulario_operacion_inline(request):
    columna = _estado_inicial_operacion()
    if columna is None:
        return JsonResponse(
            {"ok": False, "error": "No hay columnas disponibles."},
            status=400,
        )
    return render(
        request,
        "operaciones/_inline_create_form.html",
        {
            "form": OperacionInlineCreateForm(),
            "estado": columna.codigo,
            "estado_label": columna.nombre,
            "columna": columna,
        },
    )


@login_required
@require_POST
def crear_operacion_inline(request):
    estados_recibidos = request.POST.getlist("estado")
    estado = (estados_recibidos[0] if len(estados_recibidos) == 1 else "").strip()
    if len(estados_recibidos) != 1:
        return _json_error(
            "INVALID_STATE",
            message="Estado invalido.",
            errors={"estado": [{"message": "Estado invalido.", "code": "invalid"}]},
            status=400,
        )
    columna = _buscar_columna_activa_por_codigo(estado)
    if columna is None:
        return _json_error(
            "INVALID_STATE",
            message="Estado invalido.",
            errors={"estado": [{"message": "Estado invalido.", "code": "invalid"}]},
            status=400,
        )
    columna_permitida = _columna_manual_permitida()
    if (
        columna_permitida is None
        or columna.pk != columna_permitida.pk
    ):
        return _json_error(
            "INVALID_STATE",
            message="Solo se pueden crear tarjetas desde la primera columna activa.",
            errors={
                "estado": [
                    {
                        "message": "Solo se pueden crear tarjetas desde la primera columna activa.",
                        "code": "invalid",
                    }
                ]
            },
            status=400,
        )

    form = OperacionInlineCreateForm(request.POST, request.FILES)
    if not form.is_valid():
        return _json_error(
            "FORM_INVALID",
            message="No se pudo crear la operacion.",
            errors=form.errors.get_json_data(escape_html=True),
            html_form=_render_inline_create_form(request, form, columna),
            html=_render_inline_create_form(request, form, columna),
            status=400,
        )

    with transaction.atomic():
        operacion = form.save(commit=False)
        operacion.columna = columna
        operacion.estado = columna.codigo
        operacion.creado_por = request.user
        operacion.save()
        form.save_m2m()
        _guardar_archivos_y_enlaces_inline(request, operacion, form)
        cuenta_gastos, cuenta_gastos_creada = crear_cuenta_gastos_desde_operacion_si_corresponde(
            operacion, creado_por=request.user
        )

    return JsonResponse(
        {
            "ok": True,
            "html": _render_card_html(request, operacion),
            "operacion_id": operacion.id,
            "id": operacion.id,
            "estado": operacion.estado,
            "columna_id": columna.pk,
            "message": "Operacion creada correctamente.",
            "cuenta_gastos_creada": cuenta_gastos_creada,
            "cuenta_gastos_id": cuenta_gastos.pk if cuenta_gastos else None,
        },
        status=201,
    )


@login_required
@require_http_methods(["GET", "POST"])
def editar_operacion_rapida(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    # Regla de negocio: Administradores y ejecutivos tienen acceso permitido
    if getattr(request.user, "rol", None) not in ["admin", "ejecutivo"]:
        if not _puede_modificar_operacion(request.user, operacion):
            raise PermissionDenied("No tienes permisos para modificar esta operacion.")

    if request.method == "GET":
        return JsonResponse(
            {"ok": True, "html": _render_quick_edit_form(request, operacion)}
        )

    post_data = request.POST.copy()
    form = OperacionQuickEditForm(post_data, instance=operacion)
    _preservar_campos_no_enviados(form, post_data, "titulo", "cliente", "prioridad", "fecha_vencimiento", "asignados")
    if not form.is_valid():
        return _json_error(
            "FORM_INVALID",
            message="No se pudo guardar la edicion rapida.",
            errors=form.errors.get_json_data(escape_html=True),
            html_form=_render_quick_edit_form(request, operacion, form),
            html=_render_quick_edit_form(request, operacion, form),
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    contexto = _contexto_modal_operacion(operacion)
    html = render_to_string("operaciones/_detalle_modal_content.html", contexto, request=request)
    return JsonResponse({"html": html})


@login_required
def detalle_operacion_modal(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if request.method == "POST":
        form = OperacionEditarForm(request.POST, request.FILES, instance=operacion)
        _preservar_campos_no_enviados(
            form,
            request.POST,
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
            "opciones",
        )
        if form.is_valid():
            obj = form.save(commit=False)
            obj.save()
            form.save_m2m()

            if _es_ajax(request):
                return JsonResponse({
                    "success": True,
                    "html": _render_card_html(request, operacion),
                })
            messages.success(request, "OperaciÃ³n actualizada exitosamente.")
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operaciÃ³n.")
    form = OperacionEditarForm(request.POST, request.FILES, instance=operacion)
    _preservar_campos_no_enviados(
        form,
        request.POST,
        "titulo",
        "descripcion",
        "cliente",
        "prioridad",
        "fecha_vencimiento",
        "asignados",
        "etiquetas",
        "opciones",
    )

    if form.is_valid():
        obj = form.save(commit=False)
        obj.save()
        form.save_m2m()

        operacion.refresh_from_db()

        if _es_ajax(request):
            return JsonResponse({
                "success": True,
                "html": _render_card_html(request, operacion),
            })

        messages.success(request, "OperaciÃ³n actualizada exitosamente.")
        return redirect("operaciones:panel_operaciones")

    contexto = _contexto_modal_operacion(operacion, form=form)
    if _es_ajax(request):
        html = render_to_string("operaciones/_detalle_modal_content.html", contexto, request=request)
        return JsonResponse({"html": html})
    return render(request, "operaciones/_detalle_modal_content.html", contexto)


@login_required
@require_POST
def agregar_comentario(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para comentar esta operaciÃ³n.")
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operaciÃ³n.")
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar archivos de esta operaciÃ³n.")
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar enlaces de esta operaciÃ³n.")
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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


def _elementos_accion_response_payload(request, operacion):
    operacion.refresh_from_db()
    elementos = _elementos_accion_queryset(operacion)
    return {
        "id": operacion.id,
        "section_html": _render_elementos_accion_section(request, operacion),
        "resumen": _elementos_accion_resumen(elementos),
    }


@login_required
@require_POST
def crear_elemento_accion(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionElementoAccionCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "success": False,
                "id": operacion.id,
                "errors": form.errors.get_json_data(escape_html=True),
            },
            status=400,
        )

    ultimo_orden = (
        operacion.elementos_accion.order_by("-orden", "-id")
        .values_list("orden", flat=True)
        .first()
    )
    elemento = form.save(commit=False)
    elemento.operacion = operacion
    elemento.orden = (ultimo_orden or 0) + 1
    elemento.save()

    payload = _elementos_accion_response_payload(request, operacion)
    payload.update(
        {
            "success": True,
            "elemento": {
                "id": elemento.id,
                "texto": elemento.texto,
                "completado": elemento.completado,
                "orden": elemento.orden,
            },
            "item_html": _render_elemento_accion_item(request, elemento),
        }
    )
    return JsonResponse(payload)


@login_required
@require_POST
def toggle_elemento_accion(request, elemento_id):
    elemento = get_object_or_404(
        OperacionElementoAccion.objects.select_related("operacion"),
        id=elemento_id,
        operacion__eliminado_en__isnull=True,
    )
    operacion = get_object_or_404(_operacion_queryset(), id=elemento.operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    completado_raw = (request.POST.get("completado") or "").strip().lower()
    if completado_raw not in {"true", "false", "1", "0"}:
        return JsonResponse({"success": False, "error": "Valor de completado invalido."}, status=400)

    elemento.completado = completado_raw in {"true", "1"}
    elemento.save(update_fields=["completado", "fecha_actualizacion"])

    payload = _elementos_accion_response_payload(request, operacion)
    payload.update(
        {
            "success": True,
            "elemento": {
                "id": elemento.id,
                "texto": elemento.texto,
                "completado": elemento.completado,
                "orden": elemento.orden,
            },
        }
    )
    return JsonResponse(payload)


@login_required
@require_POST
def editar_elemento_accion(request, elemento_id):
    elemento = get_object_or_404(
        OperacionElementoAccion.objects.select_related("operacion"),
        id=elemento_id,
        operacion__eliminado_en__isnull=True,
    )
    operacion = get_object_or_404(_operacion_queryset(), id=elemento.operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    form = OperacionElementoAccionUpdateForm(request.POST, instance=elemento)
    if not form.is_valid():
        payload = _elementos_accion_response_payload(request, operacion)
        payload.update(
            {
                "success": False,
                "elemento_id": elemento.id,
                "errors": form.errors.get_json_data(escape_html=True),
            }
        )
        return JsonResponse(payload, status=400)

    elemento = form.save()
    payload = _elementos_accion_response_payload(request, operacion)
    payload.update(
        {
            "success": True,
            "elemento": {
                "id": elemento.id,
                "texto": elemento.texto,
                "completado": elemento.completado,
                "orden": elemento.orden,
            },
            "item_html": _render_elemento_accion_item(request, elemento),
        }
    )
    return JsonResponse(payload)


@login_required
@require_POST
def eliminar_elemento_accion(request, elemento_id):
    elemento = get_object_or_404(
        OperacionElementoAccion.objects.select_related("operacion"),
        id=elemento_id,
        operacion__eliminado_en__isnull=True,
    )
    operacion = get_object_or_404(_operacion_queryset(), id=elemento.operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    elemento_id = elemento.id
    elemento.delete()
    payload = _elementos_accion_response_payload(request, operacion)
    payload.update(
        {
            "success": True,
            "elemento_id": elemento_id,
        }
    )
    return JsonResponse(payload)


@login_required
@require_POST
def actualizar_opciones_operacion(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
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
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta operacion.")
    if not _es_ajax(request):
        return JsonResponse({"success": False, "error": "Solicitud AJAX requerida."}, status=400)

    opcion = get_object_or_404(OperacionOpcion, id=opcion_id)
    operacion.opciones.remove(opcion)
    return _opciones_response(request, operacion)


@login_required
@require_POST
def columna_crear(request):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    form = OperacionColumnaCreateForm(request.POST)
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
        "operaciones/_columna.html",
        {
            "columna": _column_context(columna=columna, items=[], count=0, loaded=0),
            "estados": _columnas_estado_choices(),
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
@require_POST
def columna_editar(request, pk):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )
    columna = get_object_or_404(OperacionColumna, pk=pk, activa=True)
    form = OperacionColumnaUpdateForm(request.POST, instance=columna)
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
    columnas = list(OperacionColumna.objects.filter(pk__in=ids, activa=True))
    if len(columnas) != len(ids):
        return JsonResponse({"ok": False, "error": "Columna no encontrada."}, status=400)
    with transaction.atomic():
        for orden, columna_id in enumerate(ids, start=1):
            OperacionColumna.objects.filter(pk=columna_id).update(orden=orden)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def columna_eliminar(request, pk):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    columna = get_object_or_404(OperacionColumna, pk=pk, activa=True)
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
    operaciones_qs = Operacion.objects.filter(
        Q(columna=columna) | Q(columna__isnull=True, estado=columna.codigo),
        eliminado_en__isnull=True,
    )
    return JsonResponse({
        "status": "ok",
        "id": operacion.id,
        "estado": operacion.estado,
        "estado_label": columna.nombre,
        "columna_id": columna.pk,
        "columna_codigo": columna.codigo,
        "cuenta_gastos_creada": cuenta_gastos_creada,
        "cuenta_gastos_id": cuenta_gastos.pk if cuenta_gastos else None,
    })

@login_required
@require_POST
def eliminar_operacion(request, operacion_id):
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        raise PermissionDenied("No tienes permisos para eliminar esta operación.")
    with transaction.atomic():
        enviar_a_papelera(operacion, request.user)

    if _es_ajax(request):
        return JsonResponse({
            "success": True,
            "ok": True,
            "redirect": True,
            "id": operacion_id,
            "message": "La tarjeta se envió a la papelera correctamente.",
        })

    messages.success(request, "La tarjeta se envió a la papelera correctamente.")
    return redirect("operaciones:panel_operaciones")


@login_required
@require_POST
def tarjeta_pegar(request, columna_id):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    
    import json
    if request.content_type == "application/json":
        try:
            data = json.loads(request.body)
            raw_tarjeta_id = str(data.get("tarjeta_id", "")).strip()
            modulo = str(data.get("modulo", "")).strip()
        except json.JSONDecodeError:
            raw_tarjeta_id = ""
            modulo = ""
    else:
        raw_tarjeta_id = (request.POST.get("tarjeta_id") or "").strip()
        modulo = (request.POST.get("modulo") or "").strip()

    if modulo and modulo != "operaciones":
        return JsonResponse(
            {"ok": False, "error": "Solo se permite copiar tarjetas de operaciones."},
            status=400,
        )
        
    if not raw_tarjeta_id.isdigit() or int(raw_tarjeta_id) <= 0:
        return JsonResponse({"ok": False, "error": "Tarjeta invalida."}, status=400)

    columna_destino = get_object_or_404(OperacionColumna, pk=columna_id, activa=True)
    operacion_original = get_object_or_404(_operacion_queryset(), pk=int(raw_tarjeta_id))

    if not _puede_modificar_operacion(request.user, operacion_original):
        return JsonResponse({"ok": False, "error": "No autorizado."}, status=403)

    with transaction.atomic():
        # Clonar la instancia principal
        nueva_operacion = get_object_or_404(_operacion_queryset(), pk=int(raw_tarjeta_id))
        nueva_operacion.pk = None
        
        # Modificar campos identificativos
        nueva_operacion.titulo = f"{operacion_original.titulo} - Copia"[:255]
        nueva_operacion.columna = columna_destino
        nueva_operacion.estado = columna_destino.codigo
        nueva_operacion.creado_por = request.user
        nueva_operacion.fecha_creacion = timezone.now()
        
        # Setear a None relaciones OneToOne
        nueva_operacion.referencia_origen = None
        
        # Guardar la nueva instancia principal
        nueva_operacion.save()

        # Copiar relaciones ManyToMany
        nueva_operacion.asignados.set(operacion_original.asignados.all())
        nueva_operacion.etiquetas.set(operacion_original.etiquetas.all())
        nueva_operacion.opciones.set(operacion_original.opciones.all())

    return JsonResponse(
        {
            "ok": True,
            "tarjeta_id": nueva_operacion.pk,
            "columna_id": columna_destino.pk,
            "html": _render_card_html(request, nueva_operacion),
            "estado": nueva_operacion.estado,
            "column_count": _column_count(columna_destino),
        },
        status=201,
    )


def crear_opcion(*args, **kwargs): pass
def crear_etiqueta(*args, **kwargs): pass
def editar_etiqueta(*args, **kwargs): pass
def eliminar_etiqueta(*args, **kwargs): pass

@login_required
@require_POST
def mover_operacion(request, operacion_id):
    if not _es_ajax(request):
        return JsonResponse({"ok": False, "error": "Solicitud invalida."}, status=400)
    
    operacion = get_object_or_404(_operacion_queryset(), id=operacion_id)
    if not _puede_modificar_operacion(request.user, operacion):
        return JsonResponse({"ok": False, "error": "No tienes permisos."}, status=403)
        
    estado = request.POST.get("estado")
    columna_id = request.POST.get("columna_id")
    posicion_str = request.POST.get("posicion")
    
    if not estado:
        return JsonResponse({"ok": False, "error": "Estado requerido."}, status=400)
        
    columna_obj = _buscar_columna_activa_por_codigo(estado)
    if not columna_obj:
        return JsonResponse({"ok": False, "error": "Estado invalido."}, status=400)
        
    posicion = 0
    if posicion_str and posicion_str.isdigit():
        posicion = int(posicion_str)
        
    with transaction.atomic():
        operacion.estado = estado
        operacion.columna = columna_obj
        operacion.posicion = posicion
        operacion.save(update_fields=["estado", "columna", "posicion"])
        
        operaciones = list(
            _operacion_queryset().filter(
                Q(columna=columna_obj) | Q(columna__isnull=True, estado=columna_obj.codigo)
            ).exclude(id=operacion.id).order_by("posicion", "-fecha_creacion", "-id")
        )
        
        # Insertamos en el nuevo índice
        if posicion >= len(operaciones):
            operaciones.append(operacion)
        else:
            operaciones.insert(posicion, operacion)
            
        operaciones_a_actualizar = []
        for idx, op in enumerate(operaciones):
            if op.posicion != idx:
                op.posicion = idx
                if op.id != operacion.id:
                    operaciones_a_actualizar.append(op)
                    
        if operaciones_a_actualizar:
            Operacion.objects.bulk_update(operaciones_a_actualizar, ["posicion"])
            
    return JsonResponse({
        "ok": True,
        "status": "ok",
        "id": operacion.id,
        "estado": operacion.estado,
        "estado_label": columna_obj.nombre,
        "columna_id": columna_obj.pk,
        "columna_codigo": columna_obj.codigo,
    })

