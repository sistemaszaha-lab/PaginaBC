from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import FileResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.urls import reverse
from django.views.decorators.http import require_POST

from .decorators import admin_required
from .forms import GarantiaArchivosForm, GarantiaComentarioForm, GarantiaEditarForm, GarantiaEnlaceForm, GarantiaForm
from .models import Garantia, GarantiaArchivo, GarantiaComentario, GarantiaEnlace


def _estado_label(estado):
    return {
        Garantia.Estado.SOLICITUD_NAVIERA: "Solicitud a naviera",
        Garantia.Estado.EN_PROCESO: "En proceso",
        Garantia.Estado.PAGO_NAVIERA_ZAHA: "Pago naviera a zaha",
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
        .prefetch_related("asignados", "comentarios__usuario", "archivos", "enlaces")
        .order_by("-fecha_creacion", "-id")
    )


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
    }


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
        {"g": garantia, "comentario_form": GarantiaComentarioForm()},
        request=request,
    )


@login_required
@admin_required
def panel_garantias(request):
    garantias = _garantia_queryset()
    columnas = {
        Garantia.Estado.SOLICITUD_NAVIERA: [],
        Garantia.Estado.EN_PROCESO: [],
        Garantia.Estado.PAGO_NAVIERA_ZAHA: [],
        Garantia.Estado.DEVOLUCION_CLIENTE: [],
    }
    for garantia in garantias:
        columnas.setdefault(garantia.estado, []).append(garantia)

    estados = _estados_disponibles()
    estados_ui = [(estado, _estado_label(estado)) for estado in estados]

    return render(
        request,
        "garantias/panel_garantias.html",
        {
            "columnas_kanban": [
                (
                    Garantia.Estado.SOLICITUD_NAVIERA,
                    _estado_label(Garantia.Estado.SOLICITUD_NAVIERA),
                    columnas.get(Garantia.Estado.SOLICITUD_NAVIERA, []),
                ),
                (
                    Garantia.Estado.EN_PROCESO,
                    _estado_label(Garantia.Estado.EN_PROCESO),
                    columnas.get(Garantia.Estado.EN_PROCESO, []),
                ),
                (
                    Garantia.Estado.PAGO_NAVIERA_ZAHA,
                    _estado_label(Garantia.Estado.PAGO_NAVIERA_ZAHA),
                    columnas.get(Garantia.Estado.PAGO_NAVIERA_ZAHA, []),
                ),
                (
                    Garantia.Estado.DEVOLUCION_CLIENTE,
                    _estado_label(Garantia.Estado.DEVOLUCION_CLIENTE),
                    columnas.get(Garantia.Estado.DEVOLUCION_CLIENTE, []),
                ),
            ],
            "comentario_form": GarantiaComentarioForm(),
            "estado_update_url": reverse("garantias:actualizar_estado_garantia"),
        },
    )


@login_required
@admin_required
def crear_garantia(request):
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
            return redirect("garantias:panel_garantias")
    else:
        form = GarantiaForm()
        archivos_form = GarantiaArchivosForm()
        enlace_form = GarantiaEnlaceForm()

    return render(
        request,
        "garantias/crear_garantia.html",
        {"form": form, "archivos_form": archivos_form, "enlace_form": enlace_form},
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
    if form.is_valid():
        GarantiaComentario.objects.create(
            garantia=garantia,
            usuario=request.user,
            comentario=form.cleaned_data["comentario"].strip(),
        )
        if _es_ajax(request):
            comentario = garantia.comentarios.select_related("usuario").order_by("-fecha", "-id").first()
            return JsonResponse(
                {
                    "status": "ok",
                    "id": garantia.pk,
                    "comentario": {
                        "usuario": comentario.usuario.get_full_name() or comentario.usuario.username,
                        "fecha": comentario.fecha.isoformat(),
                        "texto": comentario.comentario,
                    },
                }
            )
        messages.success(request, "Comentario agregado.")
    else:
        if _es_ajax(request):
            return JsonResponse({"status": "error", "error": "Comentario inválido."}, status=400)
        messages.error(request, "No se pudo agregar el comentario.")

    return redirect(f"{reverse('garantias:panel_garantias')}#garantia-{garantia.pk}")


@login_required
@admin_required
def detalle_garantia(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    contexto = _contexto_modal_garantia(garantia)
    if _es_ajax(request):
        return render(request, "garantias/_detalle_modal_content.html", contexto)
    return render(request, "garantias/detalle_garantia.html", contexto)


@login_required
@admin_required
def detalle_garantia_parcial(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    return render(request, "garantias/_detalle_modal_content.html", _contexto_modal_garantia(garantia))


@login_required
@admin_required
def editar_garantia(request, pk):
    garantia = get_object_or_404(_garantia_queryset(), pk=pk)
    if request.method == "POST":
        form = GarantiaEditarForm(request.POST, instance=garantia)
        archivos_form = GarantiaArchivosForm(request.POST, request.FILES)
        enlace_form = GarantiaEnlaceForm(request.POST)
        if form.is_valid() and archivos_form.is_valid() and enlace_form.is_valid():
            form.save()
            _guardar_adjuntos_enlaces(request, garantia, enlace_form)
            garantia = get_object_or_404(_garantia_queryset(), pk=pk)
            messages.success(request, "Garantía actualizada.")
            if _es_ajax(request):
                return JsonResponse(
                    {
                        "status": "ok",
                        "html": render_to_string(
                            "garantias/_detalle_modal_content.html",
                            _contexto_modal_garantia(garantia),
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
    if _es_ajax(request):
        return render(request, "garantias/_detalle_modal_content.html", contexto, status=400 if request.method == "POST" else 200)
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
def eliminar_archivo(request, pk, archivo_id):
    garantia = get_object_or_404(Garantia, pk=pk)
    archivo = get_object_or_404(GarantiaArchivo, pk=archivo_id, garantia=garantia)
    archivo.delete()
    messages.success(request, "Archivo eliminado.")
    if _es_ajax(request):
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "status": "ok",
                "html": render_to_string(
                    "garantias/_detalle_modal_content.html",
                    _contexto_modal_garantia(garantia),
                    request=request,
                ),
                "card_html": _render_card_html(request, garantia),
                "id": garantia.pk,
            }
        )
    return redirect("garantias:editar_garantia", pk=garantia.pk)


@login_required
@admin_required
@require_POST
def eliminar_enlace(request, pk, enlace_id):
    garantia = get_object_or_404(Garantia, pk=pk)
    enlace = get_object_or_404(GarantiaEnlace, pk=enlace_id, garantia=garantia)
    enlace.delete()
    messages.success(request, "Enlace eliminado.")
    if _es_ajax(request):
        garantia = get_object_or_404(_garantia_queryset(), pk=pk)
        return JsonResponse(
            {
                "status": "ok",
                "html": render_to_string(
                    "garantias/_detalle_modal_content.html",
                    _contexto_modal_garantia(garantia),
                    request=request,
                ),
                "card_html": _render_card_html(request, garantia),
                "id": garantia.pk,
            }
        )
    return redirect("garantias:editar_garantia", pk=garantia.pk)
