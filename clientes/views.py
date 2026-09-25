from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Count, F, OuterRef, Subquery, IntegerField, Window, DecimalField, Sum, Case, When, Value
from django.db.models.functions import Coalesce
from django.db.models.functions import Concat
from django.db.models.deletion import PROTECT, ProtectedError
from django.db.utils import OperationalError, ProgrammingError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST
from .forms import ClienteForm, MENSAJE_CLIENTE_DUPLICADO
from .models import Cliente, ClienteConsecutivo, es_integrity_error_duplicado_cliente
from solicitudes.models import Referencia


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
    existentes_pagination_query = urlencode(
        [
            (clave, valor)
            for clave, valor in request.GET.items()
            if clave not in {"page", "page_existentes"}
        ]
    )
    nuevos_pagination_query = urlencode(
        [
            (clave, valor)
            for clave, valor in request.GET.items()
            if clave not in {"page", "page_nuevos"}
        ]
    )
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
                | Q(cuentas_por_cobrar__icontains=query)
            )
        referencia_base = Referencia.objects.filter(
            eliminado_en__isnull=True, cliente=OuterRef("nombre")
        ).values("cliente").annotate(total=Count("pk")).values("total")[:1]
        referencia_compuesta = Referencia.objects.filter(
            eliminado_en__isnull=True,
            cliente=Concat(OuterRef("nombre"), Value(" ("), OuterRef("empresa"), Value(")")),
        ).values("cliente").annotate(total=Count("pk")).values("total")[:1]
        utilidad_base = Referencia.objects.filter(
            eliminado_en__isnull=True, cliente=OuterRef("nombre")
        ).values("cliente").annotate(total=Sum(Case(
            When(movimientos__tipo="INGRESO", then=F("movimientos__monto")),
            When(movimientos__tipo="GASTO", then=-F("movimientos__monto")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ))).values("total")[:1]
        utilidad_compuesta = Referencia.objects.filter(
            eliminado_en__isnull=True,
            cliente=Concat(OuterRef("nombre"), Value(" ("), OuterRef("empresa"), Value(")")),
        ).values("cliente").annotate(total=Sum(Case(
            When(movimientos__tipo="INGRESO", then=F("movimientos__monto")),
            When(movimientos__tipo="GASTO", then=-F("movimientos__monto")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        ))).values("total")[:1]
        clientes = clientes.annotate(
            referencias_count=Coalesce(Subquery(referencia_base, output_field=IntegerField()), Value(0))
            + Case(
                When(empresa__gt="", then=Coalesce(Subquery(referencia_compuesta, output_field=IntegerField()), Value(0))),
                default=Value(0),
                output_field=IntegerField(),
            )
        ).annotate(
            utilidad_calculada=Coalesce(Subquery(utilidad_base, output_field=DecimalField(max_digits=14, decimal_places=2)), Value(0, output_field=DecimalField(max_digits=14, decimal_places=2)))
            + Case(
                When(empresa__gt="", then=Coalesce(Subquery(utilidad_compuesta, output_field=DecimalField(max_digits=14, decimal_places=2)), Value(0, output_field=DecimalField(max_digits=14, decimal_places=2)))),
                default=Value(0),
                output_field=DecimalField(max_digits=14, decimal_places=2),
            )
        ).order_by("nombre", "pk")
        existentes_paginator = Paginator(
            clientes.filter(tipo_cliente=Cliente.TIPO_EXISTENTE),
            CLIENTES_POR_PAGINA,
        )
        nuevos_paginator = Paginator(
            clientes.filter(tipo_cliente=Cliente.TIPO_NUEVO),
            CLIENTES_POR_PAGINA,
        )
        existentes_page = existentes_paginator.get_page(
            request.GET.get("page_existentes")
        )
        nuevos_page = nuevos_paginator.get_page(request.GET.get("page_nuevos"))
    except (OperationalError, ProgrammingError):
        messages.error(
            request,
            "No se pudo cargar el directorio de clientes. Revisa que las migraciones esten aplicadas.",
        )
        existentes_page = Paginator([], CLIENTES_POR_PAGINA).get_page(1)
        nuevos_page = Paginator([], CLIENTES_POR_PAGINA).get_page(1)
    return_url = reverse("cliente_lista")
    query_actual = request.GET.urlencode()
    if query_actual:
        return_url = f"{return_url}?{query_actual}"
    context = {
        "clientes": list(existentes_page.object_list) + list(nuevos_page.object_list),
        "query": query,
        "existentes_page": existentes_page,
        "nuevos_page": nuevos_page,
        "existentes_pagination_items": _elementos_paginacion(existentes_page),
        "nuevos_pagination_items": _elementos_paginacion(nuevos_page),
        "existentes_pagination_query": existentes_pagination_query,
        "nuevos_pagination_query": nuevos_pagination_query,
        "return_url": return_url,
        "clientes_existentes": existentes_page.object_list,
        "clientes_nuevos": nuevos_page.object_list,
    }
    return render(request, "clientes/cliente_lista.html", context)


@login_required
def cliente_crear(request):
    next_url = _next_url_valida(
        request, request.GET.get("next")
    ) or _next_url_valida(request, request.POST.get("next"))
    if request.method == "POST":
        form = ClienteForm(request.POST, requerir_datos_alta=True)
        if form.is_valid():
            try:
                cliente = form.save(commit=False)
                cliente.tipo_cliente = Cliente.TIPO_NUEVO
                cliente.numero_cliente = None
                cliente.save()
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
        form = ClienteForm(requerir_datos_alta=True)
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
    with transaction.atomic():
        cliente = Cliente.objects.select_for_update().get(pk=pk)
        if cliente.tipo_cliente == Cliente.TIPO_NUEVO and cliente.numero_cliente is None:
            contador, _ = ClienteConsecutivo.objects.select_for_update().get_or_create(
                clave="clientes", defaults={"ultimo_numero": 0}
            )
            contador.ultimo_numero += 1
            contador.save(update_fields=["ultimo_numero"])
            cliente.numero_cliente = contador.ultimo_numero
            cliente.tipo_cliente = Cliente.TIPO_EXISTENTE
            cliente.save(update_fields=["tipo_cliente", "numero_cliente"])
    return redirect(destino)
