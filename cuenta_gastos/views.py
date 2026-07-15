from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
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
    CuentaGastosComentarioForm,
    CuentaGastosArchivosForm,
    CuentaGastosEnlaceForm,
    CuentaGastosEtiquetaForm,
    CuentaGastosOpcionForm,
)


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
            "comentarios",
            "archivos",
            "enlaces",
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


@login_required
def panel_cuenta_gastos(request):
    usuario = _get_usuario_filter(request)
    cuentas = _cuenta_queryset()
    if usuario:
        cuentas = cuentas.filter(asignados__id=usuario.id).distinct()


    columnas=[]

    for estado,nombre in COLUMNAS:

        columnas.append({

            "titulo":nombre,

            "estado":estado,

            "items":
            cuentas.filter(
                estado=estado
            )

        })
    return render(

        request,

        "cuenta_gastos/panel_cuenta_gastos.html",

        {
            "columnas":columnas,
            "usuarios_filtro": _usuarios_filtro(usuario.id if usuario else None),
            "current":"panel_cuenta_gastos"
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
def editar_cuenta(request, pk):
    cuenta = get_object_or_404(
        CuentaGastos,
        pk=pk
    )
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")

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
                    "cuenta_gastos/_detalle_modal_content.html",
                    {
                        "cuenta": cuenta,
                        "form": CuentaGastosForm(instance=cuenta),
                        "comentario_form": CuentaGastosComentarioForm(),
                        "archivos_form": CuentaGastosArchivosForm(),
                        "enlace_form": CuentaGastosEnlaceForm(),
                    },
                    request=request,
                )
                card_html = render_to_string("cuenta_gastos/_card.html", {"cuenta": cuenta}, request=request)
                return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})

            return redirect("cuenta_gastos:panel_cuenta_gastos")
        else:
            if request.headers.get("x-requested-with") == "XMLHttpRequest":
                html = render_to_string(
                    "cuenta_gastos/_detalle_modal_content.html",
                    {
                        "cuenta": cuenta,
                        "form": form,
                        "comentario_form": CuentaGastosComentarioForm(),
                        "archivos_form": CuentaGastosArchivosForm(),
                        "enlace_form": CuentaGastosEnlaceForm(),
                    },
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

    cuenta=get_object_or_404(
        _cuenta_queryset(),
        pk=pk
    )


    html = render_to_string(
        "cuenta_gastos/_detalle_modal_content.html",
        {
            "cuenta": cuenta,
            "form": CuentaGastosForm(instance=cuenta),
            "comentario_form": CuentaGastosComentarioForm(),
            "archivos_form": CuentaGastosArchivosForm(),
            "enlace_form": CuentaGastosEnlaceForm(),
        },
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
    if request.headers.get("x-requested-with") == "XMLHttpRequest" and obj_id:
        try:
            cuenta = get_object_or_404(_cuenta_queryset(), pk=int(obj_id))
            html = render_to_string(
                "cuenta_gastos/_detalle_modal_content.html",
                {
                    "cuenta": cuenta,
                    "form": CuentaGastosForm(instance=cuenta),
                    "comentario_form": CuentaGastosComentarioForm(),
                    "archivos_form": CuentaGastosArchivosForm(),
                    "enlace_form": CuentaGastosEnlaceForm(),
                },
                request=request,
            )
            card_html = render_to_string("cuenta_gastos/_card.html", {"cuenta": cuenta}, request=request)
            return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})
        except Exception:
            pass
    return JsonResponse({"success": True})


@login_required
def agregar_comentario(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para comentar esta cuenta de gastos.")
    if request.method == "POST":
        form = CuentaGastosComentarioForm(request.POST)
        if form.is_valid():
            CuentaGastosComentario.objects.create(
                cuenta_gasto=cuenta,
                usuario=request.user,
                comentario=form.cleaned_data["comentario"]
            )
            return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "No se pudo guardar el comentario."})


@login_required
def agregar_archivo(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")
    if request.method == "POST":
        archivos = request.FILES.getlist("archivos")
        if archivos:
            for archivo in archivos:
                CuentaGastosArchivo.objects.create(
                    cuenta_gasto=cuenta,
                    archivo=archivo,
                    subido_por=request.user
                )
            return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "No se pudo subir el archivo."})


@login_required
@require_POST
def eliminar_archivo(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para eliminar archivos de esta cuenta de gastos.")
    archivo_id = request.POST.get("archivo_id")
    archivo = get_object_or_404(CuentaGastosArchivo, id=archivo_id, cuenta_gasto=cuenta)
    archivo.delete()
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    html = render_to_string(
        "cuenta_gastos/_detalle_modal_content.html",
        {
            "cuenta": cuenta,
            "form": CuentaGastosForm(instance=cuenta),
            "comentario_form": CuentaGastosComentarioForm(),
            "archivos_form": CuentaGastosArchivosForm(),
            "enlace_form": CuentaGastosEnlaceForm(),
        },
        request=request,
    )
    card_html = render_to_string("cuenta_gastos/_card.html", {"cuenta": cuenta}, request=request)
    return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})


@login_required
def agregar_enlace(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para modificar esta cuenta de gastos.")
    if request.method == "POST":
        form = CuentaGastosEnlaceForm(request.POST)
        if form.is_valid():
            enlace = form.save(commit=False)
            enlace.cuenta_gasto = cuenta
            enlace.creado_por = request.user
            enlace.save()
            return JsonResponse({"success": True})
    return JsonResponse({"success": False, "error": "No se pudo agregar el enlace."})


@login_required
@require_POST
def eliminar_enlace(request, pk):
    cuenta = get_object_or_404(CuentaGastos, pk=pk)
    if not _puede_modificar_cuenta(request.user, cuenta):
        raise PermissionDenied("No tienes permisos para eliminar enlaces de esta cuenta de gastos.")
    enlace_id = request.POST.get("enlace_id")
    enlace = get_object_or_404(CuentaGastosEnlace, id=enlace_id, cuenta_gasto=cuenta)
    enlace.delete()
    cuenta = get_object_or_404(_cuenta_queryset(), pk=pk)
    html = render_to_string(
        "cuenta_gastos/_detalle_modal_content.html",
        {
            "cuenta": cuenta,
            "form": CuentaGastosForm(instance=cuenta),
            "comentario_form": CuentaGastosComentarioForm(),
            "archivos_form": CuentaGastosArchivosForm(),
            "enlace_form": CuentaGastosEnlaceForm(),
        },
        request=request,
    )
    card_html = render_to_string("cuenta_gastos/_card.html", {"cuenta": cuenta}, request=request)
    return JsonResponse({"success": True, "html": html, "card_html": card_html, "id": cuenta.pk})


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

        "ok":True

    })
