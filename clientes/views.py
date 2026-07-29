from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError
from django.db.models import Case, IntegerField, Q, Value, When
from django.db.models.deletion import PROTECT, ProtectedError
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import ClienteForm, MENSAJE_CLIENTE_DUPLICADO
from .models import Cliente, es_integrity_error_duplicado_cliente


RELACIONES_PROTEGIDAS_CLIENTE = {
    "operaciones": ("operacion", "operaciones"),
    "garantias": ("garantia", "garantias"),
    "cuentas_gastos": ("cuenta de gastos", "cuentas de gastos"),
}
CLIENTES_POR_PAGINA = 25


def _es_fetch_json(request):
    return (
        request.headers.get("X-Requested-With") == "XMLHttpRequest"
        or "application/json" in request.headers.get("Accept", "")
    )


def _conteos_relaciones_protegidas(cliente):
    relaciones = {}
    for relacion in Cliente._meta.related_objects:
        if relacion.on_delete is not PROTECT:
            continue
        accessor_name = relacion.get_accessor_name()
        if not accessor_name or not hasattr(cliente, accessor_name):
            continue
        count = getattr(cliente, accessor_name).count()
        if count:
            relaciones[accessor_name] = count
    return relaciones


def _formatear_relacion_protegida(nombre, count):
    singular, plural = RELACIONES_PROTEGIDAS_CLIENTE.get(
        nombre,
        (nombre.replace("_", " "), nombre.replace("_", " ")),
    )
    etiqueta = singular if count == 1 else plural
    return f"{count} {etiqueta}"


def _mensaje_cliente_protegido(relaciones):
    if not relaciones:
        return "No se puede eliminar este cliente porque tiene registros relacionados."
    resumen = ", ".join(
        _formatear_relacion_protegida(nombre, count)
        for nombre, count in relaciones.items()
    )
    return f"No se puede eliminar el cliente porque tiene registros relacionados: {resumen}."


def _next_url_valida(request, next_url):
    if not next_url:
        return None
    next_url = next_url.strip()
    if url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return None


def _agregar_parametros_url(url, **params):
    partes = urlsplit(url)
    query_actual = dict(parse_qsl(partes.query, keep_blank_values=True))
    query_actual.update(params)
    return urlunsplit(
        (
            partes.scheme,
            partes.netloc,
            partes.path,
            urlencode(query_actual),
            partes.fragment,
        )
    )


def _url_lista_clientes(query="", page=None):
    params = {}
    if query:
        params["q"] = query
    if page is not None:
        params["page"] = page
    query_string = urlencode(params)
    path = reverse("cliente_lista")
    return f"{path}?{query_string}" if query_string else path


def _elementos_paginacion(page_obj, radio=2):
    total = page_obj.paginator.num_pages
    visibles = {
        1,
        total,
        *range(
            max(1, page_obj.number - radio),
            min(total, page_obj.number + radio) + 1,
        ),
    }
    elementos = []
    anterior = None
    for numero in sorted(visibles):
        if anterior is not None and numero - anterior > 1:
            elementos.append(None)
        elementos.append(numero)
        anterior = numero
    return elementos


def _destino_retorno(request):
    return (
        _next_url_valida(request, request.POST.get("next"))
        or _next_url_valida(request, request.GET.get("next"))
        or reverse("cliente_lista")
    )


def _es_url_lista_clientes(url):
    return urlsplit(url).path == reverse("cliente_lista")


@login_required
def cliente_lista(request):
    query = request.GET.get("q", "").strip()
    try:
        clientes = Cliente.objects.all()
        if query:
            clientes = clientes.filter(
                Q(nombre__icontains=query)
                | Q(empresa__icontains=query)
                | Q(representante_legal__icontains=query)
                | Q(contacto__icontains=query)
                | Q(telefono__icontains=query)
                | Q(celular__icontains=query)
                | Q(correo__icontains=query)
            )
        clientes = clientes.annotate(
            _orden_tipo=Case(
                When(tipo_cliente=Cliente.TIPO_EXISTENTE, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        ).order_by("_orden_tipo", "-fecha_alta", "nombre", "pk")
        paginator = Paginator(clientes, CLIENTES_POR_PAGINA)
        page_obj = paginator.get_page(request.GET.get("page"))
        clientes_pagina = list(page_obj.object_list)
        clientes_existentes = [
            cliente
            for cliente in clientes_pagina
            if cliente.tipo_cliente == Cliente.TIPO_EXISTENTE
        ]
        clientes_nuevos = [
            cliente
            for cliente in clientes_pagina
            if cliente.tipo_cliente == Cliente.TIPO_NUEVO
        ]
    except (OperationalError, ProgrammingError):
        messages.error(
            request,
            "No se pudo cargar el directorio de clientes. Revisa que las migraciones esten aplicadas.",
        )
        paginator = Paginator([], CLIENTES_POR_PAGINA)
        page_obj = paginator.get_page(1)
        clientes_pagina = []
        clientes_existentes = []
        clientes_nuevos = []
    incluir_pagina_retorno = (
        "page" in request.GET or page_obj.number != 1
    )
    return_url = _url_lista_clientes(
        query,
        page_obj.number if incluir_pagina_retorno else None,
    )
    context = {
        "clientes": clientes_pagina,
        "clientes_existentes": clientes_existentes,
        "clientes_nuevos": clientes_nuevos,
        "query": query,
        "page_obj": page_obj,
        "pagination_items": _elementos_paginacion(page_obj),
        "pagination_base_url": _url_lista_clientes(query),
        "return_url": return_url,
    }
    return render(request, "clientes/cliente_lista.html", context)


@login_required
def cliente_crear(request):
    next_url = _next_url_valida(
        request, request.GET.get("next")
    ) or _next_url_valida(request, request.POST.get("next"))
    if request.method == "POST":
        form = ClienteForm(request.POST)
        if form.is_valid():
            try:
                cliente = form.save()
            except IntegrityError as exc:
                if not es_integrity_error_duplicado_cliente(exc):
                    raise
                form.add_error(None, MENSAJE_CLIENTE_DUPLICADO)
            else:
                if next_url:
                    if _es_url_lista_clientes(next_url):
                        return redirect(next_url)
                    return redirect(_agregar_parametros_url(next_url, cliente=str(cliente)))
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
    next_url = _next_url_valida(
        request, request.GET.get("next")
    ) or _next_url_valida(request, request.POST.get("next"))
    if request.method == "POST":
        form = ClienteForm(request.POST, instance=cliente)
        if form.is_valid():
            try:
                form.save()
            except IntegrityError as exc:
                if not es_integrity_error_duplicado_cliente(exc):
                    raise
                form.add_error(None, MENSAJE_CLIENTE_DUPLICADO)
            else:
                return redirect(next_url or "cliente_lista")
    else:
        form = ClienteForm(instance=cliente)
    return render(
        request,
        "clientes/cliente_form.html",
        {
            "form": form,
            "titulo": "Editar cliente",
            "next_url": next_url,
        },
    )


@login_required
@require_POST
def cliente_eliminar(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    destino = _destino_retorno(request)
    try:
        cliente.delete()
    except ProtectedError:
        relaciones = _conteos_relaciones_protegidas(cliente)
        message = _mensaje_cliente_protegido(relaciones)
        if _es_fetch_json(request):
            return JsonResponse(
                {
                    "ok": False,
                    "error_code": "CLIENT_PROTECTED",
                    "message": message,
                    "relations": relaciones,
                },
                status=409,
            )
        messages.error(request, message)
        return redirect(destino)

    message = "Cliente eliminado correctamente."
    if _es_fetch_json(request):
        return JsonResponse({"ok": True, "message": message})
    messages.success(request, message)
    return redirect(destino)


@login_required
@require_POST
def cliente_cambiar_estado(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    destino = _destino_retorno(request)
    cliente.estado = (
        Cliente.ESTADO_INACTIVO
        if cliente.estado == Cliente.ESTADO_ACTIVO
        else Cliente.ESTADO_ACTIVO
    )
    cliente.save(update_fields=["estado"])
    return redirect(destino)


@login_required
@require_POST
def cliente_convertir_existente(request, pk):
    cliente = get_object_or_404(Cliente, pk=pk)
    destino = _destino_retorno(request)
    cliente.tipo_cliente = Cliente.TIPO_EXISTENTE
    cliente.save(update_fields=["tipo_cliente"])
    return redirect(destino)
