from django.views.decorators.csrf import ensure_csrf_cookie
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, F, Window
from django.db.models.functions import RowNumber
from pathlib import Path

from django.http import FileResponse, JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.urls import reverse
from django.utils.http import content_disposition_header
from django.views.decorators.http import require_GET, require_POST
from django.utils.http import url_has_allowed_host_and_scheme


from .models import (
    CuentaGastos,
    CuentaGastosArchivo,
    CuentaGastosComentario,
    CuentaGastosEnlace,
    CuentaGastosEtiqueta,
    CuentaGastosOpcion,
    DocumentoRepositorio,
)
from .forms import (
    CuentaGastosForm,
    CuentaGastosTituloInlineForm,
    CuentaGastosPrioridadInlineForm,
    CuentaGastosVencimientoInlineForm,
    CuentaGastosClienteInlineForm,
    CuentaGastosAsignadosInlineForm,
    CuentaGastosInlineCreateForm,
    CuentaGastosComentarioForm,
    CuentaGastosEtiquetasSectionForm,
    CuentaGastosOpcionesSectionForm,
    CuentaGastosEtiquetaCreateForm,
    CuentaGastosOpcionCreateForm,
    CuentaGastosArchivosForm,
    CuentaGastosEnlaceForm,
    CuentaGastosEtiquetaForm,
    CuentaGastosOpcionForm,
)

INLINE_FIELD_FORMS = {
    "titulo": CuentaGastosTituloInlineForm,
    "prioridad": CuentaGastosPrioridadInlineForm,
    "fecha_vencimiento": CuentaGastosVencimientoInlineForm,
    "cliente": CuentaGastosClienteInlineForm,
    "asignados": CuentaGastosAsignadosInlineForm,
}


COLUMNAS = [

    ("SOLICITUD_PAGO","Solicitud de pago"),
    ("SOLICITUD_FACTURAS","Solicitud de facturas"),
    ("SOLICITUD_CUENTA_GASTOS","Solicitud de cuenta de agencia aduanal"),
    ("FACTURA_ANTICIPO","Factura por Anticipo"),
    ("FLETE_ESPERA_PAGO","Flete en espera de pago"),
    ("EN_PROCESO","En Proceso"),
    ("VOBO_ANGIE","VoBo Angie"),
    ("APROBADAS","Aprobadas"),
    ("SOLICITADAS_GEO","Solicitadas a Geo"),
    ("POR_ENVIAR_CLIENTE","Por enviar al cliente"),
    ("DEVOLUCION","Devolución"),
    ("COBRANZA","Cobranza"),
    ("COMPLEMENTO_PAGO","Complemento de pago"),
    ("DEUDORES_MOROSOS","Deudores Morosos"),
    ("COMERCIALIZADORAS","Comercializadoras"),

]

INITIAL_CARDS_PER_COLUMN = 3
CARDS_PAGE_SIZE = 10
CUENTA_ORDERING = ("-fecha_creacion", "-id")
ESTADOS_VALIDOS = frozenset(estado for estado, _nombre in COLUMNAS)
REPOSITORIO_INITIAL_LIMIT = 5
PDF_INVALID_MESSAGE = "EL FORMATO NO ES VÁLIDO"


def _cuenta_queryset():
    return CuentaGastos.objects\
        .select_related(
            "cliente",
            "creado_por"
        )\
        .prefetch_related(
            "asignados",
            "etiquetas",
            "comentarios__usuario",
            "archivos",
            "enlaces",
        )\
        .annotate(
            comentarios_count=Count("comentarios", distinct=True),
            archivos_count=Count("archivos", distinct=True),
            enlaces_count=Count("enlaces", distinct=True),
        )\
        .order_by(*CUENTA_ORDERING)


def _cuentas_filtradas(usuario=None):
    queryset = CuentaGastos.objects.all()
    if usuario is not None:
        queryset = queryset.filter(asignados=usuario)
    return queryset.order_by(*CUENTA_ORDERING)


def _columnas_panel(usuario=None):
    base = _cuentas_filtradas(usuario).filter(estado__in=ESTADOS_VALIDOS)
    filas_iniciales = list(
        base.annotate(
            posicion_columna=Window(
                expression=RowNumber(),
                partition_by=[F("estado")],
                order_by=[F("fecha_creacion").desc(), F("id").desc()],
            ),
            total_columna=Window(
                expression=Count("id"),
                partition_by=[F("estado")],
            ),
        )
        .filter(posicion_columna__lte=INITIAL_CARDS_PER_COLUMN)
        .values_list("id", "estado", "total_columna")
    )
    ids_iniciales = [pk for pk, _estado, _total in filas_iniciales]
    cuentas = list(_cuenta_queryset().filter(pk__in=ids_iniciales))
    cuentas_por_id = {cuenta.pk: cuenta for cuenta in cuentas}
    cuentas_por_estado = {estado: [] for estado, _nombre in COLUMNAS}
    totales = {estado: 0 for estado, _nombre in COLUMNAS}
    for pk, estado, total in filas_iniciales:
        cuenta = cuentas_por_id.get(pk)
        if cuenta is not None and estado in cuentas_por_estado:
            cuentas_por_estado[estado].append(cuenta)
            totales[estado] = total

    return [
        {
            "posicion": posicion,
            "titulo": nombre,
            "estado": estado,
            "items": cuentas_por_estado[estado],
            "count": totales[estado],
            "loaded": len(cuentas_por_estado[estado]),
            "has_more": totales[estado] > len(cuentas_por_estado[estado]),
            "remaining": max(
                0, totales[estado] - len(cuentas_por_estado[estado])
            ),
            "load_url": reverse(
                "cuenta_gastos:tarjetas_columna",
                kwargs={"estado": estado},
            ),
        }
        for posicion, (estado, nombre) in enumerate(COLUMNAS, start=1)
    ]


def _get_usuario_filter(request):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id.isdigit():
        return None
    return User.objects.filter(pk=int(usuario_id)).first()


def _get_usuario_filter_estricto(request):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id:
        return None, None
    if not usuario_id.isdigit():
        return None, JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    usuario = User.objects.filter(pk=int(usuario_id), is_active=True).first()
    if usuario is None:
        return None, JsonResponse(
            {"ok": False, "error": "Filtro de usuario invalido."},
            status=400,
        )
    return usuario, None


def _parse_loaded_ids(request, offset):
    raw_ids = (request.GET.get("loaded") or "").strip()
    if not raw_ids:
        return [] if offset == 0 else None
    parts = raw_ids.split(",")
    if any(not value.isdigit() or int(value) <= 0 for value in parts):
        return None
    loaded_ids = list(dict.fromkeys(int(value) for value in parts))
    if len(loaded_ids) != len(parts) or len(loaded_ids) != offset:
        return None
    return loaded_ids


def _filtro_post_id(request):
    value = (request.POST.get("usuario") or "").strip()
    return int(value) if value.isdigit() else None


def _matches_filter(cuenta, usuario_id):
    if usuario_id is None:
        return True
    return cuenta.asignados.filter(pk=usuario_id).exists()


def _column_count(estado, usuario_id=None):
    queryset = CuentaGastos.objects.filter(estado=estado)
    if usuario_id is not None:
        queryset = queryset.filter(asignados__pk=usuario_id)
    return queryset.count()


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


def _puede_modificar_cuenta(user, cuenta):
    if not user.is_authenticated:
        return False
    if user.is_superuser or cuenta.creado_por_id == user.id:
        return True
    return cuenta.asignados.filter(id=user.id).exists()


def _es_ajax(request):
    return request.headers.get("X-Requested-With") == "XMLHttpRequest"


def _render_inline_create_form(request, form, estado):
    return render_to_string(
        "cuenta_gastos/_inline_create_form.html",
        {
            "form": form,
            "estado": estado,
            "estado_label": dict(COLUMNAS).get(estado, estado),
        },
        request=request,
    )


def _render_card_html(request, cuenta):
    return render_to_string(
        "cuenta_gastos/_card.html",
        {"cuenta": cuenta, "estados_ui": COLUMNAS},
        request=request,
    )


def _render_inline_field(request, cuenta, field_name):
    templates = {
        "titulo": "cuenta_gastos/_inline_field_titulo.html",
        "prioridad": "cuenta_gastos/_inline_field_prioridad.html",
        "fecha_vencimiento": "cuenta_gastos/_inline_field_vencimiento.html",
        "cliente": "cuenta_gastos/_inline_field_cliente.html",
        "asignados": "cuenta_gastos/_inline_field_asignados.html",
    }
    return render_to_string(
        templates[field_name],
        {"cuenta": cuenta},
        request=request,
    )


def _render_inline_editor(request, cuenta, field_name, form=None):
    form = form or INLINE_FIELD_FORMS[field_name](instance=cuenta)
    return render_to_string(
        "cuenta_gastos/_inline_editor_form.html",
        {
            "cuenta": cuenta,
            "field_name": field_name,
            "bound_field": form[field_name],
        },
        request=request,
    )


def _detalle_template_name(layout: str) -> str:
    return (
        "cuenta_gastos/_detalle_drawer.html"
        if layout == "drawer"
        else "cuenta_gastos/_detalle_modal_content.html"
    )


def _comentarios_queryset(cuenta):
    return cuenta.comentarios.select_related("usuario").order_by("-fecha", "-id")


def _render_comentarios_section(request, cuenta, *, comentario_form=None, layout="modal"):
    comentarios = list(_comentarios_queryset(cuenta))
    return render_to_string(
        "cuenta_gastos/_comentarios_section.html",
        {
            "cuenta": cuenta,
            "comentario_form": comentario_form or CuentaGastosComentarioForm(),
            "comentarios": comentarios,
            "comentarios_count": len(comentarios),
            "layout": layout,
        },
        request=request,
    )


def _archivos_queryset(cuenta):
    return cuenta.archivos.order_by("-fecha", "-id")


def _enlaces_queryset(cuenta):
    return cuenta.enlaces.order_by("-fecha", "-id")


def _render_archivos_section(request, cuenta, *, archivos_form=None, layout="modal"):
    archivos = list(_archivos_queryset(cuenta))
    return render_to_string(
        "cuenta_gastos/_archivos_section.html",
        {
            "cuenta": cuenta,
            "archivos_form": archivos_form or CuentaGastosArchivosForm(),
            "archivos": archivos,
            "files_count": len(archivos),
            "layout": layout,
        },
        request=request,
    )


def _render_enlaces_section(request, cuenta, *, enlace_form=None, layout="modal"):
    enlaces = list(_enlaces_queryset(cuenta))
    return render_to_string(
        "cuenta_gastos/_enlaces_section.html",
        {
            "cuenta": cuenta,
            "enlace_form": enlace_form or CuentaGastosEnlaceForm(),
            "enlaces": enlaces,
            "links_count": len(enlaces),
            "layout": layout,
        },
        request=request,
    )


def _render_etiquetas_section(request, cuenta, *, etiquetas_form=None, etiqueta_create_form=None, layout="modal"):
    etiquetas = list(cuenta.etiquetas.all())
    return render_to_string(
        "cuenta_gastos/_etiquetas_section.html",
        {
            "cuenta": cuenta,
            "etiquetas": etiquetas,
            "etiquetas_count": len(etiquetas),
            "etiquetas_form": etiquetas_form or CuentaGastosEtiquetasSectionForm(instance=cuenta),
            "etiqueta_create_form": etiqueta_create_form or CuentaGastosEtiquetaCreateForm(),
            "layout": layout,
        },
        request=request,
    )


def _render_opciones_section(request, cuenta, *, opciones_form=None, opcion_create_form=None, layout="modal"):
    opciones = list(cuenta.opciones.all())
    return render_to_string(
        "cuenta_gastos/_opciones_section.html",
        {
            "cuenta": cuenta,
            "opciones": opciones,
            "opciones_count": len(opciones),
            "opciones_form": opciones_form or CuentaGastosOpcionesSectionForm(instance=cuenta),
            "opcion_create_form": opcion_create_form or CuentaGastosOpcionCreateForm(),
            "layout": layout,
        },
        request=request,
    )


def _detalle_contexto(cuenta, *, form=None, comentario_form=None, archivos_form=None, enlace_form=None, etiquetas_form=None, etiqueta_create_form=None, opciones_form=None, opcion_create_form=None, layout="modal"):
    comentarios = list(_comentarios_queryset(cuenta))
    archivos = list(_archivos_queryset(cuenta))
    enlaces = list(_enlaces_queryset(cuenta))
    etiquetas = list(cuenta.etiquetas.all())
    opciones = list(cuenta.opciones.all())
    return {
        "cuenta": cuenta,
        "form": form or CuentaGastosForm(instance=cuenta),
        "comentario_form": comentario_form or CuentaGastosComentarioForm(),
        "etiquetas_form": etiquetas_form or CuentaGastosEtiquetasSectionForm(instance=cuenta),
        "etiqueta_create_form": etiqueta_create_form or CuentaGastosEtiquetaCreateForm(),
        "opciones_form": opciones_form or CuentaGastosOpcionesSectionForm(instance=cuenta),
        "opcion_create_form": opcion_create_form or CuentaGastosOpcionCreateForm(),
        "archivos_form": archivos_form or CuentaGastosArchivosForm(),
        "enlace_form": enlace_form or CuentaGastosEnlaceForm(),
        "comentarios": comentarios,
        "comentarios_count": len(comentarios),
        "etiquetas": etiquetas,
        "etiquetas_count": len(etiquetas),
        "opciones": opciones,
        "opciones_count": len(opciones),
        "archivos": archivos,
        "files_count": len(archivos),
        "enlaces": enlaces,
        "links_count": len(enlaces),
        "layout": layout,
    }


def _repositorio_queryset():
    return DocumentoRepositorio.objects.select_related("subido_por").order_by(
        "-fecha_subida",
        "-id",
    )


def _repositorio_contexto(*, mostrar_todos=False):
    queryset = _repositorio_queryset()
    total = queryset.count()
    documentos = list(
        queryset if mostrar_todos else queryset[:REPOSITORIO_INITIAL_LIMIT]
    )
    return {
        "documentos": documentos,
        "total_documentos": total,
        "documentos_total": total,
        "documentos_visibles": len(documentos),
        "mostrar_todos": mostrar_todos,
        "hay_mas_documentos": total > len(documentos),
        "initial_limit": REPOSITORIO_INITIAL_LIMIT,
    }


def _render_repositorio(request, *, mostrar_todos=False):
    return render_to_string(
        "cuenta_gastos/_repositorio.html",
        _repositorio_contexto(mostrar_todos=mostrar_todos),
        request=request,
    )


def _validar_pdf_upload(uploaded_file):
    nombre_original = Path(uploaded_file.name or "").name.strip()
    extension = Path(nombre_original).suffix.lower()
    if not nombre_original or extension != ".pdf":
        return False, nombre_original

    mime_type = (getattr(uploaded_file, "content_type", "") or "").strip().lower()
    if mime_type and mime_type != "application/pdf":
        return False, nombre_original

    encabezado = uploaded_file.read(5)
    uploaded_file.seek(0)
    if encabezado != b"%PDF-":
        return False, nombre_original

    uploaded_file.name = nombre_original
    return True, nombre_original


def _json_pdf_invalido():
    return JsonResponse(
        {"ok": False, "message": PDF_INVALID_MESSAGE},
        status=400,
    )


@ensure_csrf_cookie
@login_required
def panel_cuenta_gastos(request):
    usuario = _get_usuario_filter(request)
    columnas = _columnas_panel(usuario)
    return render(

        request,

        "cuenta_gastos/panel_cuenta_gastos.html",

        {
            "columnas":columnas,
            "estados_ui": COLUMNAS,
            "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
            "usuario_filtro_id": usuario.id if usuario else "",
            "current":"panel_cuenta_gastos",
            "repositorio_contexto": _repositorio_contexto(),
            "panel_config": {
                "inlineCreateUrl": reverse(
                    "cuenta_gastos:crear_cuenta_gastos_inline"
                ),
                "inlineFormUrl": reverse(
                    "cuenta_gastos:formulario_cuenta_gastos_inline"
                ),
                "repositorioListUrl": reverse(
                    "cuenta_gastos:repositorio_listado"
                ),
                "repositorioUploadUrl": reverse(
                    "cuenta_gastos:repositorio_subir"
                ),
            },
        }

    )


@login_required
@require_GET
def repositorio_listado(request):
    mostrar_todos = request.GET.get("all") == "1"
    return JsonResponse(
        {
            "ok": True,
            "html": _render_repositorio(
                request,
                mostrar_todos=mostrar_todos,
            ),
            "mostrar_todos": mostrar_todos,
        }
    )


@login_required
@require_POST
def repositorio_subir(request):
    archivos = request.FILES.getlist("archivos")
    if not archivos:
        return _json_pdf_invalido()

    mostrar_todos = request.POST.get("mostrar_todos") == "1"
    archivos_validados = []
    for archivo in archivos:
        es_valido, nombre_original = _validar_pdf_upload(archivo)
        if not es_valido:
            return _json_pdf_invalido()
        archivos_validados.append((archivo, nombre_original))

    with transaction.atomic():
        for archivo, nombre_original in archivos_validados:
            DocumentoRepositorio.objects.create(
                archivo=archivo,
                nombre_original=nombre_original,
                subido_por=request.user,
            )

    return JsonResponse(
        {
            "ok": True,
            "message": "PDF cargado correctamente.",
            "html": _render_repositorio(
                request,
                mostrar_todos=mostrar_todos,
            ),
            "mostrar_todos": mostrar_todos,
        }
    )


@login_required
@require_GET
def repositorio_visualizar(request, pk):
    documento = get_object_or_404(_repositorio_queryset(), pk=pk)
    response = FileResponse(
        documento.archivo.open("rb"),
        content_type="application/pdf",
    )
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=False,
        filename=documento.nombre_original,
    )
    return response


@login_required
@require_GET
def repositorio_descargar(request, pk):
    documento = get_object_or_404(_repositorio_queryset(), pk=pk)
    response = FileResponse(
        documento.archivo.open("rb"),
        content_type="application/pdf",
    )
    response.headers["Content-Disposition"] = content_disposition_header(
        as_attachment=True,
        filename=documento.nombre_original,
    )
    return response


@login_required
@require_GET
def tarjetas_columna(request, estado):
    if estado not in ESTADOS_VALIDOS:
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

    columna = _cuentas_filtradas(usuario).filter(estado=estado)
    total = columna.count()
    recognized_loaded_ids = set(
        columna.filter(pk__in=loaded_ids).values_list("pk", flat=True)
    )
    stale_ids = [
        pk for pk in loaded_ids if pk not in recognized_loaded_ids
    ]
    effective_offset = len(recognized_loaded_ids)

    siguientes_ids = list(
        columna.exclude(pk__in=loaded_ids)
        .values_list("pk", flat=True)[: CARDS_PAGE_SIZE + 1]
    )
    has_more = len(siguientes_ids) > CARDS_PAGE_SIZE
    page_ids = siguientes_ids[:CARDS_PAGE_SIZE]
    cuentas_por_id = {
        cuenta.pk: cuenta
        for cuenta in _cuenta_queryset().filter(pk__in=page_ids)
    }
    cuentas = [
        cuentas_por_id[pk] for pk in page_ids if pk in cuentas_por_id
    ]
    html = "".join(
        render_to_string(
            "cuenta_gastos/_card.html",
            {"cuenta": cuenta, "estados_ui": COLUMNAS},
            request=request,
        )
        for cuenta in cuentas
    )
    loaded = len(cuentas)
    return JsonResponse(
        {
            "ok": True,
            "estado": estado,
            "html": html,
            "loaded": loaded,
            "next_offset": effective_offset + loaded,
            "has_more": has_more,
            "total": total,
            "stale_ids": stale_ids,
        }
    )

@login_required
def crear_cuenta_gastos(request):
    next_url = _safe_next_url(request)

    if request.method=="POST":

        form=CuentaGastosForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():

            cuenta = form.save(
            commit=False
            )

            cuenta.creado_por = (
            request.user
            )

            cuenta.save()

            form.save_m2m()

            if next_url:
                return redirect(next_url)
            return redirect(
            "cuenta_gastos:panel_cuenta_gastos"
            )       

    else:

        form=CuentaGastosForm()

    return render(
        request,
        "cuenta_gastos/crear_cuenta_gastos.html",
        {
            "form":form,
            "next_url": next_url,
        }
    )


@login_required
@require_GET
def formulario_cuenta_gastos_inline(request):
    estado = COLUMNAS[0][0]
    return render(
        request,
        "cuenta_gastos/_inline_create_form.html",
        {
            "form": CuentaGastosInlineCreateForm(),
            "estado": estado,
            "estado_label": dict(COLUMNAS)[estado],
        },
    )


@login_required
@require_GET
def editor_cuenta_inline(request, pk):
    field_name = (request.GET.get("field") or "").strip()
    if field_name not in INLINE_FIELD_FORMS:
        return JsonResponse(
            {"ok": False, "errors": {"field": ["Campo no permitido."]}},
            status=400,
        )

    cuenta = get_object_or_404(
        CuentaGastos.objects.select_related("creado_por").prefetch_related(
            "asignados"
        ),
        pk=pk,
    )
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied(
            "No tienes permisos para modificar esta cuenta de gastos."
        )
    return JsonResponse(
        {
            "ok": True,
            "id": cuenta.pk,
            "field": field_name,
            "html": _render_inline_editor(request, cuenta, field_name),
        }
    )


@login_required
@require_POST
def crear_cuenta_gastos_inline(request):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    estado = (request.POST.get("estado") or "").strip().upper()
    estados_validos = {value for value, _label in COLUMNAS}
    if estado not in estados_validos:
        return JsonResponse(
            {"ok": False, "errors": {"estado": ["Estado invalido."]}},
            status=400,
        )

    form = CuentaGastosInlineCreateForm(request.POST, request.FILES)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "message": "Revisa los campos indicados.",
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, estado),
            },
            status=400,
        )

    with transaction.atomic():
        cuenta = form.save(commit=False)
        cuenta.estado = estado
        cuenta.creado_por = request.user
        cuenta.save()
        form.save_m2m()

        for archivo in request.FILES.getlist("archivos"):
            CuentaGastosArchivo.objects.create(
                cuenta_gasto=cuenta,
                archivo=archivo,
                subido_por=request.user,
            )

        for enlace in form.cleaned_data.get("enlaces_payload", []):
            CuentaGastosEnlace.objects.create(
                cuenta_gasto=cuenta,
                titulo=enlace["titulo"],
                url=enlace["url"],
                creado_por=request.user,
            )

    usuario_filtro_id = _filtro_post_id(request)
    matches_filter = _matches_filter(cuenta, usuario_filtro_id)

    cuenta = get_object_or_404(_cuenta_queryset(), pk=cuenta.pk)
    return JsonResponse(
        {
            "ok": True,
            "message": "La cuenta de gastos se creo correctamente.",
            "html": _render_card_html(request, cuenta),
            "card_html": _render_card_html(request, cuenta),
            "id": cuenta.pk,
            "cuenta_id": cuenta.pk,
            "estado": cuenta.estado,
            "column_count": _column_count(
                cuenta.estado, usuario_filtro_id
            ),
            "matches_filter": matches_filter,
        },
        status=201,
    )


@login_required
@require_POST
def actualizar_cuenta_inline(request, pk):
    if not _es_ajax(request):
        return JsonResponse(
            {"ok": False, "errors": {"__all__": ["Solicitud invalida."]}},
            status=400,
        )

    field_name = (request.POST.get("field") or "").strip()
    form_class = INLINE_FIELD_FORMS.get(field_name)
    if form_class is None:
        return JsonResponse(
            {"ok": False, "errors": {"field": ["Campo no permitido."]}},
            status=400,
        )

    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")

    form = form_class(request.POST, instance=cuenta)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "id": cuenta.pk,
                "field": field_name,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_editor(
                    request,
                    cuenta,
                    field_name,
                    form=form,
                ),
            },
            status=400,
        )

    if field_name == "asignados":
        cuenta.asignados.set(form.cleaned_data.get("asignados"))
    else:
        cuenta = form.save()

    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    usuario_filtro_id = _filtro_post_id(request)
    return JsonResponse(
        {
            "ok": True,
            "id": cuenta.pk,
            "field": field_name,
            "html": _render_inline_field(request, cuenta, field_name),
            "estado": cuenta.estado,
            "matches_filter": _matches_filter(cuenta, usuario_filtro_id),
            "column_count": _column_count(
                cuenta.estado, usuario_filtro_id
            ),
        }
    )


@login_required
def editar_cuenta(request, pk):
    cuenta = get_object_or_404(
        CuentaGastos,
        pk=pk
    )
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")
    layout = (request.POST.get("layout") or request.GET.get("layout") or "modal").strip()

    form = CuentaGastosForm(
        request.POST or None,
        request.FILES or None,
        instance=cuenta
    )

    if request.method == "POST":
        if form.is_valid():
            original = CuentaGastos.objects.get(pk=pk)
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

            # Responder apropiadamente para AJAX
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
                html = render_to_string(
                    _detalle_template_name(layout),
                    _detalle_contexto(cuenta, layout=layout),
                    request=request,
                )
                card_html = render_to_string(
                    "cuenta_gastos/_card.html",
                    {"cuenta": cuenta, "estados_ui": COLUMNAS},
                    request=request,
                )
                usuario_filtro_id = _filtro_post_id(request)
                return JsonResponse(
                    {
                        "success": True,
                        "html": html,
                        "card_html": card_html,
                        "id": cuenta.pk,
                        "estado": cuenta.estado,
                        "matches_filter": _matches_filter(
                            cuenta, usuario_filtro_id
                        ),
                        "column_count": _column_count(
                            cuenta.estado, usuario_filtro_id
                        ),
                    }
                )

            return redirect("cuenta_gastos:panel_cuenta_gastos")
        else:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                html = render_to_string(
                    _detalle_template_name(layout),
                    _detalle_contexto(
                        cuenta,
                        form=form,
                        comentario_form=CuentaGastosComentarioForm(),
                        etiquetas_form=CuentaGastosEtiquetasSectionForm(instance=cuenta),
                        etiqueta_create_form=CuentaGastosEtiquetaCreateForm(),
                        opciones_form=CuentaGastosOpcionesSectionForm(instance=cuenta),
                        opcion_create_form=CuentaGastosOpcionCreateForm(),
                        archivos_form=CuentaGastosArchivosForm(),
                        enlace_form=CuentaGastosEnlaceForm(),
                        layout=layout,
                    ),
                    request=request,
                )
                return JsonResponse({"success": False, "html": html})

    return render(
        request,
        "cuenta_gastos/crear_cuenta_gastos.html",
        {
            "form": form,
            "current": "editar_cuenta_gastos"
        }
    )


@login_required
def detalle_cuenta_gastos(
    request,
    pk
):
    layout = (request.GET.get("layout") or "modal").strip()

    cuenta=get_object_or_404(
        _cuenta_queryset(),
        pk=pk
    )


    html = render_to_string(
        _detalle_template_name(layout),
        _detalle_contexto(cuenta, layout=layout),
        request=request,
    )
    return JsonResponse({
        "html": html
    })


@login_required
def crear_opcion(request):
    if request.method == "POST":
        form = CuentaGastosOpcionForm(request.POST)
        if form.is_valid():
            opcion = form.save()
            return JsonResponse({"success": True, "id": opcion.id, "nombre": opcion.nombre})
    return JsonResponse({"success": False, "error": "No se pudo crear la opción."})


@login_required
def crear_etiqueta(request):
    if request.method == "POST":
        form = CuentaGastosEtiquetaForm(request.POST)
        if form.is_valid():
            etiqueta = form.save()
            return JsonResponse({"success": True, "id": etiqueta.id, "nombre": etiqueta.nombre, "color": etiqueta.color})
    return JsonResponse({"success": False, "error": "No se pudo crear la etiqueta."})


@login_required
@require_POST
def eliminar_etiqueta(request, etiqueta_id):
    etiqueta = get_object_or_404(CuentaGastosEtiqueta, id=etiqueta_id)
    etiqueta.delete()
    obj_id = request.POST.get("obj_id")
    layout = (request.POST.get("layout") or "modal").strip()
    if request.headers.get("x-requested-with") == "XMLHttpRequest" and obj_id:
        try:
            cuenta = get_object_or_404(_cuenta_queryset(), pk=int(obj_id))
            html = render_to_string(
                _detalle_template_name(layout),
                _detalle_contexto(cuenta, layout=layout),
                request=request,
            )
            card_html = render_to_string(
                "cuenta_gastos/_card.html",
                {"cuenta": cuenta, "estados_ui": COLUMNAS},
                request=request,
            )
            return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})
        except Exception:
            pass
    return JsonResponse({"success": True})


@login_required
@require_POST
def actualizar_etiquetas_cuenta(request, pk):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosEtiquetasSectionForm(request.POST, instance=cuenta)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "html": _render_etiquetas_section(request, cuenta, etiquetas_form=form, layout=layout),
                "id": cuenta.pk,
            },
            status=400,
        )
    cuenta.etiquetas.set(form.cleaned_data.get("etiquetas"))
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_etiquetas_section(request, cuenta, layout=layout),
            "card_html": render_to_string(
                "cuenta_gastos/_card.html",
                {"cuenta": cuenta, "estados_ui": COLUMNAS},
                request=request,
            ),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def crear_etiqueta_cuenta(request, pk):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosEtiquetaCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "html": _render_etiquetas_section(request, cuenta, etiqueta_create_form=form, layout=layout),
                "id": cuenta.pk,
            },
            status=400,
        )
    etiqueta = form.save()
    cuenta.etiquetas.add(etiqueta)
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_etiquetas_section(request, cuenta, layout=layout),
            "card_html": render_to_string(
                "cuenta_gastos/_card.html",
                {"cuenta": cuenta, "estados_ui": COLUMNAS},
                request=request,
            ),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def quitar_etiqueta_cuenta(request, pk, etiqueta_id):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las etiquetas de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    etiqueta = get_object_or_404(CuentaGastosEtiqueta, pk=etiqueta_id)
    cuenta.etiquetas.remove(etiqueta)
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_etiquetas_section(request, cuenta, layout=layout),
            "card_html": render_to_string(
                "cuenta_gastos/_card.html",
                {"cuenta": cuenta, "estados_ui": COLUMNAS},
                request=request,
            ),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def actualizar_opciones_cuenta(request, pk):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosOpcionesSectionForm(request.POST, instance=cuenta)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "html": _render_opciones_section(request, cuenta, opciones_form=form, layout=layout),
                "id": cuenta.pk,
            },
            status=400,
        )
    cuenta.opciones.set(form.cleaned_data.get("opciones"))
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_opciones_section(request, cuenta, layout=layout),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def crear_opcion_cuenta(request, pk):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosOpcionCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "html": _render_opciones_section(request, cuenta, opcion_create_form=form, layout=layout),
                "id": cuenta.pk,
            },
            status=400,
        )
    opcion = form.save()
    cuenta.opciones.add(opcion)
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_opciones_section(request, cuenta, layout=layout),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def quitar_opcion_cuenta(request, pk, opcion_id):
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar las opciones de esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    opcion = get_object_or_404(CuentaGastosOpcion, pk=opcion_id)
    cuenta.opciones.remove(opcion)
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_opciones_section(request, cuenta, layout=layout),
            "id": cuenta.pk,
        }
    )


@login_required
def agregar_comentario(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para comentar esta cuenta de gastos.")
    if request.method == "POST":
        form = CuentaGastosComentarioForm(request.POST)
        layout = (request.POST.get("layout") or "modal").strip()
        if form.is_valid():
            CuentaGastosComentario.objects.create(
                cuenta_gasto=cuenta,
                usuario=request.user,
                comentario=form.cleaned_data["comentario"]
            )
            cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
            return JsonResponse(
                {
                    "success": True,
                    "comments_html": _render_comentarios_section(request, cuenta, layout=layout),
                    "comments_count": cuenta.comentarios.count(),
                    "id": cuenta.pk,
                }
            )
        if _es_ajax(request):
            return JsonResponse(
                {
                    "success": False,
                    "comments_html": _render_comentarios_section(request, cuenta, comentario_form=form, layout=layout),
                    "comments_count": cuenta.comentarios.count(),
                    "id": cuenta.pk,
                },
                status=400,
            )
    return JsonResponse({"success": False, "error": "No se pudo guardar el comentario."}, status=400)


@login_required
@require_POST
def agregar_archivo(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosArchivosForm(request.POST, request.FILES)
    if form.is_valid():
        for archivo in form.cleaned_data["archivos"]:
            CuentaGastosArchivo.objects.create(
                cuenta_gasto=cuenta,
                archivo=archivo,
                subido_por=request.user
            )
        cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
        return JsonResponse(
            {
                "ok": True,
                "html": _render_archivos_section(request, cuenta, layout=layout),
                "files_count": cuenta.archivos.count(),
                "id": cuenta.pk,
            }
        )
    return JsonResponse(
        {
            "ok": False,
            "html": _render_archivos_section(request, cuenta, archivos_form=form, layout=layout),
            "files_count": cuenta.archivos.count(),
            "id": cuenta.pk,
        },
        status=400,
    )


@login_required
@require_POST
def eliminar_archivo(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para eliminar archivos de esta cuenta de gastos.")
    archivo_id = request.POST.get("archivo_id")
    layout = (request.POST.get("layout") or "modal").strip()
    archivo = get_object_or_404(CuentaGastosArchivo, id=archivo_id, cuenta_gasto=cuenta)
    archivo.delete()
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_archivos_section(request, cuenta, layout=layout),
            "files_count": cuenta.archivos.count(),
            "id": cuenta.pk,
        }
    )


@login_required
@require_POST
def agregar_enlace(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")
    layout = (request.POST.get("layout") or "modal").strip()
    form = CuentaGastosEnlaceForm(request.POST)
    if form.is_valid():
        enlace = form.save(commit=False)
        enlace.cuenta_gasto = cuenta
        enlace.creado_por = request.user
        enlace.save()
        cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
        return JsonResponse(
            {
                "ok": True,
                "html": _render_enlaces_section(request, cuenta, layout=layout),
                "links_count": cuenta.enlaces.count(),
                "id": cuenta.pk,
            }
        )
    return JsonResponse(
        {
            "ok": False,
            "html": _render_enlaces_section(request, cuenta, enlace_form=form, layout=layout),
            "links_count": cuenta.enlaces.count(),
            "id": cuenta.pk,
        },
        status=400,
    )


@login_required
@require_POST
def eliminar_enlace(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para eliminar enlaces de esta cuenta de gastos.")
    enlace_id = request.POST.get("enlace_id")
    layout = (request.POST.get("layout") or "modal").strip()
    enlace = get_object_or_404(CuentaGastosEnlace, id=enlace_id, cuenta_gasto=cuenta)
    enlace.delete()
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "html": _render_enlaces_section(request, cuenta, layout=layout),
            "links_count": cuenta.enlaces.count(),
            "id": cuenta.pk,
        }
    )


@login_required
def eliminar_cuenta(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para eliminar esta cuenta de gastos.")
    if request.method == "POST":
        cuenta.delete()
        if request.headers.get("x-requested-with") == "XMLHttpRequest":
            return JsonResponse({"success": True, "redirect": True, "id": pk})
        return redirect("cuenta_gastos:panel_cuenta_gastos")
    return JsonResponse({"success": False, "error": "Método no permitido."})


@require_POST
@login_required
def mover_cuenta_gastos(
    request,
    pk
):

    cuenta=get_object_or_404(
        CuentaGastos,
        pk=pk
    )
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para mover esta cuenta de gastos.")

    estado=request.POST.get(
        "estado"
    )


    estados_validos=[

        e[0]
        for e in COLUMNAS

    ]


    if estado not in estados_validos:

        return JsonResponse({

            "ok":False

        })


    cuenta.estado=estado

    cuenta.save()


    return JsonResponse({

        "ok":True,
        "id": cuenta.pk,
        "estado": cuenta.estado,
        "estado_label": cuenta.get_estado_display(),

    })
