from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.utils import OperationalError, ProgrammingError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse

from .forms import ClienteForm
from .models import Cliente


def _next_url_valida(next_url):
    if not next_url:
        return None
    if "://" in next_url:
        return None
    if not next_url.startswith("/"):
        return None
    return next_url


@login_required
def cliente_lista(request):
    query = request.GET.get("q", "").strip()
    try:
        clientes = Cliente.objects.all()
        if query:
            clientes = clientes.filter(
                Q(nombre__icontains=query)
                | Q(empresa__icontains=query)
                | Q(telefono__icontains=query)
                | Q(correo__icontains=query)
                | Q(direccion__icontains=query)
                | Q(rfc__icontains=query)
            )
    except (OperationalError, ProgrammingError):
        messages.error(
            request,
            "No se pudo cargar el directorio de clientes. Revisa que las migraciones esten aplicadas.",
        )
        clientes = []
    context = {
        "clientes": clientes,
        "query": query,
    }
    return render(request, "clientes/cliente_lista.html", context)


@login_required
def cliente_crear(request):
    next_url = _next_url_valida(request.GET.get("next")) or _next_url_valida(request.POST.get("next"))
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            cliente = form.save()
            if next_url:
                params = urlencode({"cliente": str(cliente)})
                return redirect(f"{next_url}?{params}")
            return redirect("cliente_lista")
    else:
        form = ClienteForm()
    return render(
        request,
        "clientes/cliente_form.html",
        {
            "form": form,
            "titulo": "Nuevo cliente",
            "next_url": next_url,
        },
    )


@login_required
def cliente_editar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            form.save()
            return redirect("cliente_lista")
    else:
        form = ClienteForm(instance=cliente)
    return render(
        request,
        "clientes/cliente_form.html",
        {"form": form, "titulo": "Editar cliente"},
    )


@login_required
def cliente_eliminar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    if request.method == "POST":
        cliente.delete()
        return redirect("cliente_lista")
    return render(request, "clientes/cliente_confirm_delete.html", {"cliente": cliente})
