from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Count
from django.http import JsonResponse
from django.shortcuts import render, get_object_or_404, redirect
from django.template.loader import render_to_string
from django.views.decorators.http import require_POST
from django.utils.http import url_has_allowed_host_and_scheme


from .models import (
    CuentaGastos,
    CuentaGastosArchivo,
    CuentaGastosComentario,
    CuentaGastosEnlace,
    CuentaGastosEtiqueta,
    CuentaGastosOpcion,
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
    ("SOLICITUD_CUENTA_GASTOS","Solicitud de cuenta de gastos"),
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
        )


def _get_usuario_filter(request):
    usuario_id = (request.GET.get("usuario") or "").strip()
    if not usuario_id.isdigit():
        return None
    return User.objects.filter(pk=int(usuario_id)).first()


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
        {"form": form, "estado": estado},
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


@login_required
def panel_cuenta_gastos(request):
    usuario = _get_usuario_filter(request)
    cuentas = list(_cuenta_queryset())
    if usuario:
        cuentas = [
            cuenta
            for cuenta in cuentas
            if any(asignado.id == usuario.id for asignado in cuenta.asignados.all())
        ]

    cuentas_por_estado = {estado: [] for estado, _nombre in COLUMNAS}
    for cuenta in cuentas:
        cuentas_por_estado.setdefault(cuenta.estado, []).append(cuenta)

    columnas = [
        {
            "posicion": posicion,
            "titulo": nombre,
            "estado": estado,
            "items": cuentas_por_estado.get(estado, []),
            "count": len(cuentas_por_estado.get(estado, [])),
        }
        for posicion, (estado, nombre) in enumerate(COLUMNAS, start=1)
    ]
    return render(

        request,

        "cuenta_gastos/panel_cuenta_gastos.html",

        {
            "columnas":columnas,
            "estados_ui": COLUMNAS,
            "inline_form": CuentaGastosInlineCreateForm(),
            "inline_fake_cuenta": CuentaGastos(pk="__PK__"),
            "inline_titulo_form": CuentaGastosTituloInlineForm(),
            "inline_prioridad_form": CuentaGastosPrioridadInlineForm(),
            "inline_vencimiento_form": CuentaGastosVencimientoInlineForm(),
            "inline_cliente_form": CuentaGastosClienteInlineForm(),
            "inline_asignados_form": CuentaGastosAsignadosInlineForm(),
            "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
            "current":"panel_cuenta_gastos",
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

    form = CuentaGastosInlineCreateForm(request.POST)
    if not form.is_valid():
        return JsonResponse(
            {
                "ok": False,
                "errors": form.errors.get_json_data(escape_html=True),
                "html": _render_inline_create_form(request, form, estado),
            },
            status=400,
        )

    cuenta = form.save(commit=False)
    cuenta.estado = estado
    cuenta.creado_por = request.user
    cuenta.save()
    form.save_m2m()

    cuenta = get_object_or_404(_cuenta_queryset(), pk=cuenta.pk)
    return JsonResponse(
        {
            "ok": True,
            "html": render_to_string(
                "cuenta_gastos/_card.html",
                {"cuenta": cuenta, "estados_ui": COLUMNAS},
                request=request,
            ),
            "id": cuenta.pk,
            "estado": cuenta.estado,
            "column_count": CuentaGastos.objects.filter(estado=cuenta.estado).count(),
        }
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
            {"ok": False, "errors": form.errors.get_json_data(escape_html=True)},
            status=400,
        )

    if field_name == "asignados":
        cuenta.asignados.set(form.cleaned_data.get("asignados"))
    else:
        cuenta = form.save()

    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    return JsonResponse(
        {
            "ok": True,
            "field": field_name,
            "html": _render_inline_field(request, cuenta, field_name),
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
                return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})

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
