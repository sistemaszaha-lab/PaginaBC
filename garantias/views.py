from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from .decorators import admin_required
from .forms import GarantiaComentarioForm, GarantiaForm, GarantiaEditarForm
from .models import Garantia, GarantiaComentario


def _estado_label(estado):
    return {
        Garantia.Estado.CREADA: "Creada",
        Garantia.Estado.PRESENTADA: "Presentada",
        Garantia.Estado.RESUELTA: "Resuelta",
    }.get(estado, estado)


@login_required
@admin_required
def panel_garantias(request):
    garantias = (
        Garantia.objects.select_related("cliente", "creado_por")
        .prefetch_related("comentarios__usuario")
        .order_by("-fecha_creacion", "-id")
    )
    columnas = {
        Garantia.Estado.CREADA: [],
        Garantia.Estado.PRESENTADA: [],
        Garantia.Estado.RESUELTA: [],
    }
    for g in garantias:
        columnas.setdefault(g.estado, []).append(g)

    return render(
        request,
        "garantias/panel_garantias.html",
        {
            "columnas_kanban": [
                (Garantia.Estado.CREADA, _estado_label(Garantia.Estado.CREADA), columnas.get(Garantia.Estado.CREADA, [])),
                (
                    Garantia.Estado.PRESENTADA,
                    _estado_label(Garantia.Estado.PRESENTADA),
                    columnas.get(Garantia.Estado.PRESENTADA, []),
                ),
                (
                    Garantia.Estado.RESUELTA,
                    _estado_label(Garantia.Estado.RESUELTA),
                    columnas.get(Garantia.Estado.RESUELTA, []),
                ),
            ],
            "estados": [Garantia.Estado.CREADA, Garantia.Estado.PRESENTADA, Garantia.Estado.RESUELTA],
            "comentario_form": GarantiaComentarioForm(),
        },
    )


@login_required
@admin_required
def crear_garantia(request):
    if request.method == "POST":
        form = GarantiaForm(request.POST)
        if form.is_valid():
            garantia = form.save(commit=False)
            garantia.estado = Garantia.Estado.CREADA
            garantia.creado_por = request.user
            garantia.save()
            messages.success(request, "Garantía creada.")
            return redirect("garantias:panel_garantias")
    else:
        form = GarantiaForm()

    return render(request, "garantias/crear_garantia.html", {"form": form})


@login_required
@admin_required
@require_POST
def cambiar_estado_garantia(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
    nuevo_estado = (request.POST.get("estado") or "").strip().upper()
    estados_validos = {Garantia.Estado.CREADA, Garantia.Estado.PRESENTADA, Garantia.Estado.RESUELTA}
    if nuevo_estado not in estados_validos:
        raise PermissionDenied("Estado inválido.")
    if garantia.estado != nuevo_estado:
        garantia.estado = nuevo_estado
        garantia.save(update_fields=["estado"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
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
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return JsonResponse({"status": "error", "error": "Comentario inválido."}, status=400)
        messages.error(request, "No se pudo agregar el comentario.")

    return redirect(f"{reverse('garantias:panel_garantias')}#garantia-{garantia.pk}")


@login_required
@admin_required
def detalle_garantia(request, pk):
    garantia = get_object_or_404(
        Garantia.objects.select_related("cliente", "creado_por").prefetch_related("comentarios__usuario"),
        pk=pk,
    )
    return render(
        request,
        "garantias/detalle_garantia.html",
        {
            "garantia": garantia,
            "comentario_form": GarantiaComentarioForm(),
            "estados": [Garantia.Estado.CREADA, Garantia.Estado.PRESENTADA, Garantia.Estado.RESUELTA],
        },
    )


@login_required
@admin_required
def editar_garantia(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
    if request.method == "POST":
        form = GarantiaEditarForm(request.POST, instance=garantia)
        if form.is_valid():
            form.save()
            messages.success(request, "Garantía actualizada.")
            return redirect("garantias:detalle_garantia", pk=garantia.pk)
    else:
        form = GarantiaEditarForm(instance=garantia)

    return render(request, "garantias/editar_garantia.html", {"form": form, "garantia": garantia})


@login_required
@admin_required
def eliminar_garantia(request, pk):
    garantia = get_object_or_404(Garantia, pk=pk)
    if request.method == "POST":
        garantia.delete()
        messages.success(request, "Garantía eliminada.")
        return redirect("garantias:panel_garantias")

    return render(request, "garantias/eliminar_garantia.html", {"garantia": garantia})
