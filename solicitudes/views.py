from datetime import datetime
from io import BytesIO
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font
from .forms import CotizacionForm, CrearUsuarioForm, ReferenciaForm, SolicitudForm
from .models import Cotizacion, Referencia, Solicitud

ESTADOS_SIGUIENTES = {
    "Pendiente": "Cumplido",
    "Cumplido": "Pendiente",
    "No cumplido": "Fuera de plazo",
    "Fuera de plazo": "No cumplido",
}

TIPOS_TRANSPORTE = {"aereo", "maritimo", "terrestre"}
MAX_ADMIN_USERS = 3


def _es_admin(user):
    return user.is_superuser


def _requiere_admin(user):
    if not _es_admin(user):
        raise PermissionDenied("No tienes permisos para esta acción.")


def _asignar_estados_por_transporte(solicitud):
    solicitud.estado_aereo = "Pendiente" if solicitud.aerea else None
    solicitud.estado_maritimo = "Pendiente" if solicitud.maritima else None
    solicitud.estado_terrestre = "Pendiente" if solicitud.terrestre else None


def _valor_excel(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Sí" if value else "No"
    return str(value)


def _respuesta_excel(nombre_archivo, headers, rows):
    timestamp = timezone.now().strftime("%Y%m%d_%H%M")

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Resumen"

    worksheet.append(headers)
    for cell in worksheet[1]:
        cell.font = Font(bold=True)

    for row in rows:
        worksheet.append([_valor_excel(value) for value in row])

    for column_cells in worksheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column_cells)
        worksheet.column_dimensions[column_cells[0].column_letter].width = min(max_length + 2, 60)

    output = BytesIO()
    workbook.save(output)
    output.seek(0)

    response = HttpResponse(
        output.getvalue(),
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}_{timestamp}.xlsx"'
    return response


@login_required
def inicio(request):
    anio_actual = datetime.now().year
    solicitudes_anio = Solicitud.objects.filter(anio=anio_actual)

    total_solicitudes = solicitudes_anio.count()
    cumplidas = solicitudes_anio.filter(
        Q(estado_aereo="Cumplido")
        | Q(estado_maritimo="Cumplido")
        | Q(estado_terrestre="Cumplido")
    ).distinct().count()
    pendientes = solicitudes_anio.filter(
        Q(estado_aereo="Pendiente")
        | Q(estado_maritimo="Pendiente")
        | Q(estado_terrestre="Pendiente")
    ).distinct().count()
    vencidas = solicitudes_anio.filter(
        Q(estado_aereo__in=["No cumplido", "Fuera de plazo"])
        | Q(estado_maritimo__in=["No cumplido", "Fuera de plazo"])
        | Q(estado_terrestre__in=["No cumplido", "Fuera de plazo"])
    ).distinct().count()

    return render(
        request,
        "inicio.html",
        {
            "anio": anio_actual,
            "total_solicitudes": total_solicitudes,
            "cumplidas": cumplidas,
            "pendientes": pendientes,
            "vencidas": vencidas,
        },
    )


@login_required
def lista_solicitudes(request):
    anios = list(
        Solicitud.objects.values_list("anio", flat=True).distinct().order_by("anio")
    )
    anio_param = request.GET.get("anio")
    anio = (
        int(anio_param)
        if anio_param and anio_param.isdigit()
        else (anios[-1] if anios else None)
    )
    solicitudes = (
        Solicitud.objects.filter(anio=anio).order_by("-fecha_recepcion")
        if anio
        else Solicitud.objects.none()
    )

    return render(
        request,
        "solicitudes/lista_solicitudes.html",
        {
            "solicitudes": solicitudes,
            "anios": anios,
            "anio_seleccionado": anio,
            "usuarios": User.objects.all().order_by("username"),
        },
    )


@login_required
def exportar_solicitudes_excel(request):
    anios = list(
        Solicitud.objects.values_list("anio", flat=True).distinct().order_by("anio")
    )
    anio_param = request.GET.get("anio")
    anio = (
        int(anio_param)
        if anio_param and anio_param.isdigit()
        else (anios[-1] if anios else None)
    )
    solicitudes = (
        Solicitud.objects.filter(anio=anio).order_by("-fecha_recepcion")
        if anio
        else Solicitud.objects.none()
    )
    headers = [
        "Año",
        "SG",
        "Cliente",
        "Fecha recepción",
        "Fecha entrega",
        "Tipo",
        "Ejecutivo",
        "Aérea",
        "Estado aéreo",
        "Marítima",
        "Estado marítimo",
        "Terrestre",
        "Estado terrestre",
        "Días restantes",
    ]
    rows = [
        [
            s.anio,
            s.sg,
            s.cliente,
            s.fecha_recepcion,
            s.fecha_entrega,
            s.tipo,
            s.ejecutivo.username if s.ejecutivo else "",
            s.aerea,
            s.estado_aereo,
            s.maritima,
            s.estado_maritimo,
            s.terrestre,
            s.estado_terrestre,
            s.dias_restantes,
        ]
        for s in solicitudes
    ]
    return _respuesta_excel("resumen_solicitudes", headers, rows)


@login_required
def crear_solicitud(request):
    if request.method == "POST":
        form = SolicitudForm(request.POST)
        if form.is_valid():
            solicitud = form.save(commit=False)
            _asignar_estados_por_transporte(solicitud)
            solicitud.save()
            return redirect("lista_solicitudes")
    else:
        form = SolicitudForm()

    return render(request, "solicitudes/crear_solicitud.html", {"form": form})


@login_required
def editar_solicitud(request, pk):
    solicitud = get_object_or_404(Solicitud, pk=pk)

    if request.method == "POST":
        form = SolicitudForm(request.POST, instance=solicitud)
        if form.is_valid():
            solicitud = form.save(commit=False)
            _asignar_estados_por_transporte(solicitud)
            solicitud.save()
            return redirect("lista_solicitudes")
    else:
        form = SolicitudForm(instance=solicitud)

    return render(
        request,
        "solicitudes/crear_solicitud.html",
        {"form": form, "modo_edicion": True},
    )


@login_required
def eliminar_solicitud(request, pk):
    solicitud = get_object_or_404(Solicitud, pk=pk)
    _requiere_admin(request.user)

    if request.method == "POST":
        solicitud.delete()
        return redirect("lista_solicitudes")

    return render(
        request,
        "solicitudes/eliminar_solicitud.html",
        {"solicitud": solicitud},
    )


@login_required
@require_POST
def cambiar_estado(request, pk, tipo):
    if tipo not in TIPOS_TRANSPORTE:
        raise PermissionDenied("Tipo de transporte no permitido.")

    solicitud = get_object_or_404(Solicitud, pk=pk)
    if not (_es_admin(request.user) or solicitud.ejecutivo_id == request.user.id):
        raise PermissionDenied("No tienes permisos para cambiar este estado.")

    campo = f"estado_{tipo}"
    setattr(solicitud, campo, ESTADOS_SIGUIENTES.get(getattr(solicitud, campo), "Pendiente"))

    if tipo != "aereo":
        solicitud.estado_aereo = None
    if tipo != "maritimo":
        solicitud.estado_maritimo = None
    if tipo != "terrestre":
        solicitud.estado_terrestre = None

    solicitud.save()
    return redirect("lista_solicitudes")


@login_required
@require_POST
def cambiar_ejecutivo(request, pk):
    _requiere_admin(request.user)
    solicitud = get_object_or_404(Solicitud, pk=pk)

    user_id = request.POST.get("ejecutivo")
    solicitud.ejecutivo = get_object_or_404(User, id=user_id) if user_id else None
    solicitud.save()

    return redirect("lista_solicitudes")


@login_required
def lista_usuarios(request):
    _requiere_admin(request.user)
    usuarios = User.objects.all().order_by("username")
    return render(request, "usuarios/lista_usuarios.html", {"usuarios": usuarios})


@login_required
def crear_usuario(request):
    _requiere_admin(request.user)

    if request.method == "POST":
        form = CrearUsuarioForm(request.POST)
        if form.is_valid():
            rol = form.cleaned_data["rol"]

            if rol == "admin" and User.objects.filter(is_superuser=True).count() >= MAX_ADMIN_USERS:
                form.add_error("rol", f"Solo se permiten {MAX_ADMIN_USERS} usuarios con rol Administrador.")
            else:
                user = form.save(commit=False)
                user.is_superuser = rol == "admin"
                user.is_staff = rol == "admin"
                user.save()
                return redirect("lista_usuarios")
    else:
        form = CrearUsuarioForm()

    return render(request, "usuarios/crear_usuario.html", {"form": form})


@login_required
@require_POST
def eliminar_usuario(request, pk):
    _requiere_admin(request.user)
    usuario = get_object_or_404(User, pk=pk)

    if usuario != request.user:
        usuario.delete()
    return redirect("lista_usuarios")


@login_required
def lista_cotizaciones(request):
    anios = list(
        Cotizacion.objects.values_list("anio", flat=True).distinct().order_by("anio")
    )
    anio_param = request.GET.get("anio")
    anio = (
        int(anio_param)
        if anio_param and anio_param.isdigit()
        else (anios[-1] if anios else None)
    )
    cotizaciones = Cotizacion.objects.filter(anio=anio) if anio else Cotizacion.objects.none()

    return render(
        request,
        "cotizaciones/lista_cotizaciones.html",
        {
            "cotizaciones": cotizaciones,
            "anios": anios,
            "anio_seleccionado": anio,
        },
    )


@login_required
def exportar_cotizaciones_excel(request):
    anios = list(
        Cotizacion.objects.values_list("anio", flat=True).distinct().order_by("anio")
    )
    anio_param = request.GET.get("anio")
    anio = (
        int(anio_param)
        if anio_param and anio_param.isdigit()
        else (anios[-1] if anios else None)
    )
    cotizaciones = (
        Cotizacion.objects.filter(anio=anio).order_by("-fecha_solicitud")
        if anio
        else Cotizacion.objects.none()
    )
    headers = [
        "Año",
        "Consecutivo",
        "Prospecto",
        "Fecha solicitud",
        "Fecha envío",
        "Tipo",
        "Ejecutivo",
        "Tiempo entrega",
        "Aérea",
        "Marítima",
        "Terrestre",
    ]
    rows = [
        [
            c.anio,
            c.consecutivo,
            c.cliente,
            c.fecha_solicitud,
            c.fecha_envio,
            c.tipo,
            c.ejecutivo.username if c.ejecutivo else "",
            c.tiempo_entrega,
            c.aerea,
            c.maritima,
            c.terrestre,
        ]
        for c in cotizaciones
    ]
    return _respuesta_excel("resumen_cotizaciones", headers, rows)


@login_required
def crear_cotizacion(request):
    if request.method == "POST":
        form = CotizacionForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("lista_cotizaciones")
    else:
        form = CotizacionForm()

    return render(request, "cotizaciones/crear_cotizacion.html", {"form": form})


@login_required
def editar_cotizacion(request, pk):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)

    if request.method == "POST":
        form = CotizacionForm(request.POST, instance=cotizacion)
        if form.is_valid():
            form.save()
            return redirect("lista_cotizaciones")
    else:
        form = CotizacionForm(instance=cotizacion)

    return render(request, "cotizaciones/crear_cotizacion.html", {"form": form})


@login_required
@require_POST
def eliminar_cotizacion(request, pk):
    _requiere_admin(request.user)
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    cotizacion.delete()
    return redirect("lista_cotizaciones")


@login_required
def lista_referencias(request):
    referencias = Referencia.objects.all().order_by("-fecha")
    return render(request, "referencias/lista_referencias.html", {"referencias": referencias})


@login_required
def exportar_referencias_excel(request):
    referencias = Referencia.objects.select_related("ejecutivo").order_by("-fecha")
    headers = [
        "Referencia",
        "Ejecutivo",
        "Cliente",
        "Servicio",
        "Agencia aduanal",
        "Fecha",
    ]
    rows = [
        [
            r.referencia,
            r.ejecutivo.username if r.ejecutivo else "",
            r.cliente,
            r.servicio,
            r.agencia_aduanal,
            r.fecha,
        ]
        for r in referencias
    ]
    return _respuesta_excel("resumen_referencias", headers, rows)


@login_required
def crear_referencia(request):
    _requiere_admin(request.user)

    if request.method == "POST":
        form = ReferenciaForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("lista_referencias")
    else:
        form = ReferenciaForm()

    return render(request, "referencias/crear_referencia.html", {"form": form})


@login_required
def editar_referencia(request, pk):
    _requiere_admin(request.user)
    referencia = get_object_or_404(Referencia, pk=pk)

    if request.method == "POST":
        form = ReferenciaForm(request.POST, instance=referencia)
        if form.is_valid():
            form.save()
            return redirect("lista_referencias")
    else:
        form = ReferenciaForm(instance=referencia)

    return render(request, "referencias/crear_referencia.html", {"form": form})


@login_required
@require_POST
def eliminar_referencia(request, pk):
    _requiere_admin(request.user)
    referencia = get_object_or_404(Referencia, pk=pk)
    referencia.delete()
    return redirect("lista_referencias")
