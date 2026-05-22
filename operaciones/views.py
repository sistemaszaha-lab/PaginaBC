from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST, require_http_methods

# pyrefly: ignore [missing-import]
from .forms import (
    OperacionArchivosForm,
    OperacionComentarioForm,
    OperacionEditarForm,
    OperacionEnlaceForm,
    OperacionForm,
)
from .models import (
    Operacion,
    OperacionArchivo,
    OperacionComentario,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)


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
        .prefetch_related("asignados", "comentarios__usuario", "archivos", "enlaces", "etiquetas")
        .order_by("-fecha_creacion", "-id")
    )


def _contexto_modal_operacion(operacion, form=None, archivos_form=None, enlace_form=None, comentario_form=None):
    asignados = [usuario for usuario in operacion.asignados.all() if _nombre_corto_usuario(usuario)]
    return {
        "operacion": operacion,
        "form": form or OperacionEditarForm(instance=operacion),
        "archivos_form": archivos_form or OperacionArchivosForm(),
        "enlace_form": enlace_form or OperacionEnlaceForm(),
        "comentario_form": comentario_form or OperacionComentarioForm(),
        "nombre_corto_asignados": [_nombre_corto_usuario(usuario) for usuario in asignados],
        "iniciales_asignados": [_iniciales_usuario(usuario) for usuario in asignados],
        "asignados_count": len(asignados),
    }


def _guardar_adjuntos_enlaces(request, operacion, enlace_form):
    for archivo in request.FILES.getlist("archivos"):
        OperacionArchivo.objects.create(operacion=operacion, archivo=archivo, subido_por=request.user)

    if (enlace_form.cleaned_data.get("titulo") or "").strip() and (enlace_form.cleaned_data.get("url") or "").strip():
        enlace = enlace_form.save(commit=False)
        enlace.operacion = operacion
        enlace.creado_por = request.user
        enlace.save()


def _render_card_html(request, operacion):
    return render_to_string(
        "operaciones/_operacion_card.html",
        {"operacion": operacion, "comentario_form": OperacionComentarioForm()},
        request=request,
    )


@login_required
def panel_operaciones(request):

    filtro_usuarios = request.GET.getlist("usuarios")

    operaciones = _operacion_queryset()

    # limpiar vacíos y valores inválidos
    filtro_usuarios = [
        int(x)
        for x in filtro_usuarios
        if x and x.isdigit()
    ]

    if filtro_usuarios:
        operaciones = (
            operaciones
            .filter(
                asignados__id__in=filtro_usuarios
            )
            .distinct()
        )

    
    # Organizar por estado (columnas Kanban)
    columnas = {
        Operacion.Estado.PENDIENTE: [],
        Operacion.Estado.SEGUROS: [],
        Operacion.Estado.PRUEBA_VALOR: [],
        Operacion.Estado.EN_ADUANA: [],
        Operacion.Estado.TRANSITO_NACIONAL: [],
        Operacion.Estado.COORDINAR_PICKUP: [],
        Operacion.Estado.TRANSITO_INTERNACIONAL: [],
        Operacion.Estado.EXPEDIENTE_CG: [],
        Operacion.Estado.SOLICITUD_CUENTA_GASTOS: [],
    }
    
    for operacion in operaciones:
        if operacion.estado in columnas:
            columnas[operacion.estado].append(operacion)
    
    # Obtener usuarios para filtros
    from django.contrib.auth import get_user_model
    User = get_user_model()
    usuarios_sistema = User.objects.filter(
        operaciones_asignadas__isnull=False
    ).distinct().order_by("first_name")
    
    # Mapeo de valores para filtros (usando nombres)
    usuarios_filtro = [
        {"nombre": u.first_name, "id": u.id, "seleccionado": u.id in filtro_usuarios}
        for u in usuarios_sistema
    ]
    
    return render(request, "operaciones/panel_operaciones.html", {
        "columnas": columnas,
        "estados": Operacion.Estado.choices,
        "usuarios_filtro": usuarios_filtro,
        "current": "panel_operaciones",
    })


@login_required
def crear_operacion(request):
    if request.method == "POST":
        form = OperacionForm(request.POST)
        if form.is_valid():
            operacion = form.save(commit=False)
            operacion.creado_por = request.user
            operacion.save()
            form.save_m2m()
            
            if _es_ajax(request):
                return JsonResponse({
                    "success": True,
                    "html": _render_card_html(request, operacion),
                    "estado": operacion.estado,
                    "id": operacion.id,
                })
            
            messages.success(request, "Operación creada exitosamente.")
            return redirect("operaciones:panel_operaciones")
    else:
        form = OperacionForm()
    
    return render(request, "operaciones/crear_operacion.html", {"form": form, "current": "crear_operacion"})


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
    form = OperacionComentarioForm(request.POST)
    
    if form.is_valid():
        comentario = OperacionComentario.objects.create(
            operacion=operacion,
            usuario=request.user,
            comentario=form.cleaned_data["comentario"],
        )
        
        if _es_ajax(request):
            html = render_to_string(
                "operaciones/_detalle_modal_content.html",
                _contexto_modal_operacion(operacion),
                request=request,
            )
            return JsonResponse({
                "success": True,
                "html": html,
                "id": operacion.id,
                "comentario": {
                    "usuario": comentario.usuario.first_name,
                    "texto": comentario.comentario,
                    "fecha": comentario.fecha.strftime("%Y-%m-%d %H:%M"),
                },
            })
    
    return JsonResponse({"success": False})


@login_required
@require_POST
def agregar_archivo(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    form = OperacionArchivosForm(request.POST, request.FILES)
    enlace_form = OperacionEnlaceForm(request.POST)
    
    if form.is_valid() or enlace_form.is_valid():
        _guardar_adjuntos_enlaces(request, operacion, enlace_form)
        
        if _es_ajax(request):
            html = render_to_string(
                "operaciones/_detalle_modal_content.html",
                _contexto_modal_operacion(operacion),
                request=request,
            )
            return JsonResponse({"success": True, "html": html, "id": operacion.id})
    
    return JsonResponse({"success": False})


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

        estado=request.POST.get(
           "estado"
        )

        if estado:

            operacion.estado=estado

            operacion.save()

            return JsonResponse({
                "status":"ok"
            })

    return JsonResponse({
        "status":"error"
    })

@login_required
@require_POST
def eliminar_operacion(request, operacion_id):
    operacion = get_object_or_404(Operacion, id=operacion_id)
    operacion.delete()
    
    if _es_ajax(request):
        return JsonResponse({"success": True, "redirect": True, "id": operacion_id})
    
    messages.success(request, "Operación eliminada exitosamente.")
    return redirect("operaciones:panel_operaciones")
