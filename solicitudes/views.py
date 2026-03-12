import csv
import re
from datetime import date, datetime
from io import BytesIO
from unicodedata import normalize

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError
from django.db.models import IntegerField, Q
from django.db.models.functions import Cast, Length, Substr
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST
from openpyxl import Workbook
from openpyxl.styles import Font
from urllib.parse import urlencode
from clientes.models import Cliente
from .forms import CotizacionForm, CrearUsuarioForm, EditarUsuarioForm, ReferenciaForm, SolicitudForm
from .models import Cotizacion, Referencia, Solicitud

ESTADOS_SIGUIENTES = {
    "Pendiente": "Cumplido",
    "Cumplido": "Pendiente",
    "No cumplido": "Fuera de plazo",
    "Fuera de plazo": "No cumplido",
}

TIPOS_TRANSPORTE = {"aereo", "maritimo", "terrestre"}
MAX_ADMIN_USERS = 4


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


def _contexto_clientes(request):
    clientes = Cliente.objects.order_by("nombre", "empresa")
    cliente_nuevo_url = f"{reverse('cliente_crear')}?{urlencode({'next': request.path})}"
    return {"clientes": clientes, "cliente_nuevo_url": cliente_nuevo_url}
def _normalizar_texto(valor):
    texto = normalize("NFKD", str(valor or "")).encode("ascii", "ignore").decode("ascii")
    return " ".join(texto.strip().lower().split())


def _detectar_delimitador(contenido):
    muestra = contenido[:4096]
    try:
        return csv.Sniffer().sniff(muestra, delimiters=",;|	").delimiter
    except csv.Error:
        return ";"


def _leer_csv_subido(archivo):
    bruto = archivo.read()
    for encoding in ("utf-8-sig", "latin-1"):
        try:
            contenido = bruto.decode(encoding)
            break
        except UnicodeDecodeError:
            contenido = None
    if contenido is None:
        raise ValueError("No se pudo leer el archivo CSV con codificaciones soportadas.")

    delimitador = _detectar_delimitador(contenido)
    filas = list(csv.reader(contenido.splitlines(), delimiter=delimitador))
    if not filas:
        raise ValueError("El CSV está vacío.")
    return filas


def _fila_parece_encabezado(row, claves):
    if not row:
        return False
    celdas = [_normalizar_texto(celda) for celda in row if str(celda).strip()]
    if not celdas:
        return False
    coincidencias = 0
    for celda in celdas:
        for clave in claves:
            if celda == clave or celda.startswith(clave):
                coincidencias += 1
                break
    return coincidencias >= 2


def _obtener_filas_datos(filas, claves_encabezado):
    if not filas:
        return []
    return filas[1:] if _fila_parece_encabezado(filas[0], claves_encabezado) else filas


def _extraer_consecutivo(texto):
    match = re.search(r"(\d+)$", str(texto or "").strip())
    return int(match.group(1)) if match else 0


def _normalizar_consecutivo(texto):
    return re.sub(r"[^A-Za-z0-9]", "", str(texto or "").upper())


def _buscar_indice(headers, aliases, default=None):
    encabezados = [_normalizar_texto(h) for h in headers]
    aliases_norm = [_normalizar_texto(alias) for alias in aliases]
    for idx, encabezado in enumerate(encabezados):
        if any(alias in encabezado for alias in aliases_norm):
            return idx
    return default


def _valor_columna(row, index):
    if index is None:
        return ""
    return row[index].strip() if index < len(row) else ""


def _parse_fecha(valor):
    texto = str(valor or "").strip()
    if not texto:
        return None
    for formato in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%m-%y", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def _parse_anio(valor):
    texto = str(valor or "").strip()
    if texto.isdigit() and len(texto) == 4:
        return int(texto)
    return None


def _parse_estado_transporte(valor):
    texto = _normalizar_texto(valor)
    if not texto:
        return False, None
    estados = {
        "pendiente": "Pendiente",
        "cumplido": "Cumplido",
        "no cumplido": "No cumplido",
        "fuera de plazo": "Fuera de plazo",
    }
    return True, estados.get(texto, "Pendiente")


def _resolver_usuario(valor):
    texto = str(valor or "").strip()
    if not texto:
        return None
    return (
        User.objects.filter(username__iexact=texto).first()
        or User.objects.filter(email__iexact=texto).first()
        or User.objects.filter(first_name__iexact=texto).first()
    )


def _anio_desde_codigo(codigo, prefijo):
    texto = _normalizar_texto(codigo).replace(" ", "")
    if not texto.startswith(prefijo):
        return None
    sufijo = texto[len(prefijo): len(prefijo) + 2]
    if sufijo.isdigit():
        return 2000 + int(sufijo)
    return None


def _normalizar_servicio(valor):
    limpio = _normalizar_texto(valor).replace("-", " ").replace("_", " ")
    limpio = " ".join(limpio.split())
    candidatos = {
        "importacion": "importacion",
        "exportacion": "exportacion",
        "servicios transporte": "servicios_transporte",
        "servicios y transporte": "servicios_transporte",
        "servicios consultoria": "servicios_consultoria",
        "comercializador importacion": "comercializador_importacion",
        "comercializadora importacion": "comercializador_importacion",
        "comercializador exportacion": "comercializador_exportacion",
        "comercializadora exportacion": "comercializador_exportacion",
    }
    return candidatos.get(limpio, limpio.replace(" ", "_"))


def _servicio_formulario_desde_csv(valor):
    texto = _normalizar_texto(valor)
    if "export" in texto:
        return "exportacion"
    if "consult" in texto:
        return "servicios_consultoria"
    if "transporte" in texto or "servicio" in texto:
        return "servicios_transporte"
    if "comercializador" in texto or "comercializadora" in texto:
        if "export" in texto:
            return "comercializador_exportacion"
        return "comercializador_importacion"
    return "importacion"


def _servicio_referencia_normalizado(valor):
    servicio = _normalizar_servicio(valor)
    if servicio in ReferenciaForm.CODIGOS_OPERACION:
        return servicio
    return _servicio_formulario_desde_csv(valor)


def _generar_referencia(fecha, servicio):
    codigo = ReferenciaForm.CODIGOS_OPERACION.get(servicio)
    if not codigo:
        return None
    anio_corto = fecha.strftime("%y")
    prefijo_anio = f"{ReferenciaForm.PREFIJO_EMPRESA}{anio_corto}"
    prefijo = f"{prefijo_anio}{codigo}"
    referencias = Referencia.objects.filter(referencia__startswith=prefijo_anio).values_list("referencia", flat=True)
    ultimo = 0
    patron = re.compile(rf"^{re.escape(prefijo_anio)}\d(\d{{3}})$")
    for referencia in referencias:
        match = patron.match(str(referencia).strip().upper())
        if match:
            ultimo = max(ultimo, int(match.group(1)))
    return f"{prefijo}{ultimo + 1:03d}"


def _importar_solicitudes_desde_filas(filas):
    headers = filas[0] if filas else []
    data_rows = _obtener_filas_datos(
        filas,
        ["sg", "cliente", "fecha", "tipo", "ejecutivo", "solicitud"],
    )
    sg_idx = _buscar_indice(headers, ["sg", "numero de solicitud", "solicitud"], default=0)
    cliente_idx = _buscar_indice(headers, ["cliente", "empresa"], default=1)
    fecha_idx = _buscar_indice(headers, ["fecha recepcion", "fecha inicio", "fecha"], default=2)
    anio_idx = _buscar_indice(headers, ["anio", "año"])
    tipo_idx = _buscar_indice(headers, ["tipo"], default=4)
    ejecutivo_idx = _buscar_indice(headers, ["ejecutivo", "usuario"], default=5)
    aerea_idx = _buscar_indice(headers, ["aerea"], default=7)
    maritima_idx = _buscar_indice(headers, ["maritima"], default=8)
    terrestre_idx = _buscar_indice(headers, ["terrestre"], default=9)

    creados = 0
    actualizados = 0
    omitidos = 0
    anios_tocados = set()
    errores = []

    for row_num, row in enumerate(data_rows, start=1):
        try:
            sg = _normalizar_consecutivo(_valor_columna(row, sg_idx))
            if not sg or "indicar" in _normalizar_texto(sg):
                omitidos += 1
                continue

            fecha_recepcion = _parse_fecha(_valor_columna(row, fecha_idx))
            anio = (
                _parse_anio(_valor_columna(row, anio_idx))
                or _anio_desde_codigo(sg, "sg")
                or (fecha_recepcion.year if fecha_recepcion else None)
                or date.today().year
            )

            aerea, estado_aereo = _parse_estado_transporte(_valor_columna(row, aerea_idx))
            maritima, estado_maritimo = _parse_estado_transporte(_valor_columna(row, maritima_idx))
            terrestre, estado_terrestre = _parse_estado_transporte(_valor_columna(row, terrestre_idx))

            _, creado = Solicitud.objects.update_or_create(
                sg=sg,
                anio=anio,
                defaults={
                    "cliente": _valor_columna(row, cliente_idx) or "Sin cliente",
                    "fecha_recepcion": fecha_recepcion or date(anio, 1, 1),
                    "tipo": _valor_columna(row, tipo_idx) or "Sin tipo",
                    "ejecutivo": _resolver_usuario(_valor_columna(row, ejecutivo_idx)),
                    "aerea": aerea,
                    "maritima": maritima,
                    "terrestre": terrestre,
                    "estado_aereo": estado_aereo,
                    "estado_maritimo": estado_maritimo,
                    "estado_terrestre": estado_terrestre,
                },
            )
            anios_tocados.add(anio)
            if creado:
                creados += 1
            else:
                actualizados += 1
        except Exception as exc:
            omitidos += 1
            errores.append(f"fila {row_num}: {exc}")
    return creados, actualizados, omitidos, anios_tocados, errores


def _importar_cotizaciones_desde_filas(filas):
    headers = filas[0] if filas else []
    data_rows = _obtener_filas_datos(
        filas,
        ["cotizacion", "cotización", "consecutivo", "prospecto", "fecha", "tipo"],
    )
    anio_idx = _buscar_indice(headers, ["anio", "año"])
    consecutivo_idx = _buscar_indice(headers, ["consecutivo", "cotizacion", "cotización"], default=0)
    cliente_idx = _buscar_indice(headers, ["cliente", "prospecto"], default=1)
    fecha_solicitud_idx = _buscar_indice(headers, ["fecha solicitud"], default=2)
    fecha_envio_idx = _buscar_indice(headers, ["fecha envio", "fecha envío"], default=3)
    tipo_idx = _buscar_indice(headers, ["tipo"], default=4)
    ejecutivo_idx = _buscar_indice(headers, ["ejecutivo", "usuario"], default=5)
    tiempo_idx = _buscar_indice(headers, ["tiempo entrega"], default=6)
    aerea_idx = _buscar_indice(headers, ["aerea"], default=7)
    maritima_idx = _buscar_indice(headers, ["maritima"], default=8)
    terrestre_idx = _buscar_indice(headers, ["terrestre"], default=9)

    creados = 0
    actualizados = 0
    omitidos = 0
    anios_tocados = set()

    for row in data_rows:
        try:
            consecutivo = _normalizar_consecutivo(_valor_columna(row, consecutivo_idx))
            if not consecutivo:
                omitidos += 1
                continue

            fecha_solicitud = _parse_fecha(_valor_columna(row, fecha_solicitud_idx))
            anio = (
                _parse_anio(_valor_columna(row, anio_idx))
                or _anio_desde_codigo(consecutivo, "c")
                or (fecha_solicitud.year if fecha_solicitud else None)
                or date.today().year
            )

            _, creado = Cotizacion.objects.update_or_create(
                anio=anio,
                consecutivo=consecutivo,
                defaults={
                    "cliente": _valor_columna(row, cliente_idx) or "Sin prospecto",
                    "fecha_solicitud": fecha_solicitud or date(anio, 1, 1),
                    "fecha_envio": _parse_fecha(_valor_columna(row, fecha_envio_idx)),
                    "tipo": _valor_columna(row, tipo_idx) or "Sin tipo",
                    "ejecutivo": _resolver_usuario(_valor_columna(row, ejecutivo_idx)),
                    "tiempo_entrega": _valor_columna(row, tiempo_idx),
                    "aerea": _valor_columna(row, aerea_idx),
                    "maritima": _valor_columna(row, maritima_idx),
                    "terrestre": _valor_columna(row, terrestre_idx),
                },
            )
            anios_tocados.add(anio)
            if creado:
                creados += 1
            else:
                actualizados += 1
        except Exception:
            omitidos += 1
    return creados, actualizados, omitidos, anios_tocados


def _importar_referencias_desde_filas(filas):
    headers = filas[0] if filas else []
    data_rows = _obtener_filas_datos(
        filas,
        ["referencia", "ejecutivo", "cliente", "servicio", "agencia", "fecha"],
    )
    ejecutivo_idx = _buscar_indice(headers, ["ejecutivo", "usuario"], default=1)
    cliente_idx = _buscar_indice(headers, ["cliente"], default=2)
    servicio_idx = _buscar_indice(headers, ["servicio", "tipo operacion", "tipo operación"], default=3)
    agencia_idx = _buscar_indice(headers, ["agencia aduanal", "agencia"], default=4)
    fecha_idx = _buscar_indice(headers, ["fecha"], default=5)

    creados = 0
    actualizados = 0
    omitidos = 0

    filas_sin_referencia = []

    for row in data_rows:
        try:
            if not any(str(celda or "").strip() for celda in row):
                continue
            filas_sin_referencia.append(row)
        except Exception:
            omitidos += 1

    filas_sin_referencia.sort(
        key=lambda row: (
            _parse_fecha(_valor_columna(row, fecha_idx)) or date.today(),
            _servicio_referencia_normalizado(_valor_columna(row, servicio_idx)),
            _valor_columna(row, cliente_idx),
        )
    )

    for row in filas_sin_referencia:
        try:
            fecha = _parse_fecha(_valor_columna(row, fecha_idx)) or date.today()
            servicio = _servicio_referencia_normalizado(_valor_columna(row, servicio_idx))
            ejecutivo = _resolver_usuario(_valor_columna(row, ejecutivo_idx))
            cliente = _valor_columna(row, cliente_idx) or "Sin cliente"
            agencia = _valor_columna(row, agencia_idx) or "Sin agencia"

            servicio_final = servicio if servicio in ReferenciaForm.CODIGOS_OPERACION else "importacion"
            creado = False
            for _ in range(3):
                referencia = _generar_referencia(fecha, servicio_final)
                if not referencia:
                    break
                try:
                    Referencia.objects.create(
                        referencia=referencia,
                        ejecutivo=ejecutivo,
                        cliente=cliente,
                        servicio=servicio_final,
                        agencia_aduanal=agencia,
                        fecha=fecha,
                    )
                    creado = True
                    break
                except IntegrityError:
                    continue
            if creado:
                creados += 1
            else:
                omitidos += 1
        except Exception:
            omitidos += 1

    return creados, actualizados, omitidos


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
    solicitudes_qs = Solicitud.objects.filter(anio=anio) if anio else Solicitud.objects.none()
    q = request.GET.get("q", "").strip()
    orden = request.GET.get("orden", "desc").lower()
    if orden not in {"asc", "desc"}:
        orden = "desc"

    if q:
        solicitudes_qs = solicitudes_qs.filter(
            Q(sg__icontains=q)
            | Q(cliente__icontains=q)
            | Q(tipo__icontains=q)
            | Q(fecha_recepcion__icontains=q)
            | Q(fecha_entrega__icontains=q)
            | Q(ejecutivo__username__icontains=q)
            | Q(ejecutivo__first_name__icontains=q)
            | Q(ejecutivo__last_name__icontains=q)
        )

    solicitudes = list(solicitudes_qs)
    solicitudes.sort(
        key=lambda s: (_extraer_consecutivo(s.sg), s.sg),
        reverse=orden == "desc",
    )
    ejecutivos = User.objects.all().order_by("username")

    if request.GET.get("partial") == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(
            request,
            "solicitudes/_solicitudes_rows.html",
            {"solicitudes": solicitudes, "usuarios": ejecutivos, "orden": orden},
        )

    return render(
        request,
        "solicitudes/lista_solicitudes.html",
        {
            "solicitudes": solicitudes,
            "anios": anios,
            "anio_seleccionado": anio,
            "usuarios": ejecutivos,
            "q": q,
            "orden": orden,
        },
    )


@login_required
def importar_solicitudes_csv(request):
    if request.method != "POST":
        return redirect("lista_solicitudes")
    _requiere_admin(request.user)
    archivo = request.FILES.get("archivo_csv")
    if not archivo:
        messages.error(request, "Selecciona un archivo CSV para importar solicitudes.")
        return redirect("lista_solicitudes")

    try:
        filas = _leer_csv_subido(archivo)
        creados, actualizados, omitidos, anios_tocados, errores = _importar_solicitudes_desde_filas(filas)
        messages.success(
            request,
            f"Solicitudes importadas. Creadas: {creados}, actualizadas: {actualizados}, omitidas: {omitidos}.",
        )
        if errores:
            muestra = " | ".join(errores[:3])
            messages.warning(request, f"Se omitieron filas con error. Ejemplos: {muestra}")
        if anios_tocados:
            return redirect(f"{reverse('lista_solicitudes')}?anio={max(anios_tocados)}")
    except Exception as exc:
        messages.error(request, f"No se pudo importar solicitudes: {exc}")
    return redirect("lista_solicitudes")


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
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form.fields["cliente"].initial = cliente_param

    context = {"form": form}
    context.update(_contexto_clientes(request))
    return render(request, "solicitudes/crear_solicitud.html", context)


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
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form = SolicitudForm(instance=solicitud, initial={"cliente": cliente_param})
        else:
            form = SolicitudForm(instance=solicitud)

    context = {"form": form, "modo_edicion": True}
    context.update(_contexto_clientes(request))
    return render(request, "solicitudes/crear_solicitud.html", context)


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
    admin_count = User.objects.filter(is_superuser=True).count()

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

    return render(
        request,
        "usuarios/crear_usuario.html",
        {
            "form": form,
            "cancel_url": "lista_usuarios",
            "admin_count": admin_count,
            "max_admin_users": MAX_ADMIN_USERS,
        },
    )


@login_required
def editar_usuario(request, pk):
    es_admin = _es_admin(request.user)
    if not es_admin and request.user.pk != pk:
        raise PermissionDenied("No tienes permisos para esta acción.")
    usuario = get_object_or_404(User, pk=pk)
    puede_editar_rol = es_admin
    destino = "lista_usuarios" if es_admin else "inicio"

    if request.method == "POST":
        form = EditarUsuarioForm(request.POST, instance=usuario, can_edit_role=puede_editar_rol)
        if form.is_valid():
            if puede_editar_rol:
                rol = form.cleaned_data["rol"]
                promoviendo_a_admin = rol == "admin" and not usuario.is_superuser
                if promoviendo_a_admin and User.objects.filter(is_superuser=True).count() >= MAX_ADMIN_USERS:
                    form.add_error("rol", f"Solo se permiten {MAX_ADMIN_USERS} usuarios con rol Administrador.")
                else:
                    form.save()
                    return redirect(destino)
            else:
                form.save()
                return redirect(destino)
    else:
        form = EditarUsuarioForm(instance=usuario, can_edit_role=puede_editar_rol)

    return render(
        request,
        "usuarios/crear_usuario.html",
        {"form": form, "modo_edicion": True, "cancel_url": destino},
    )


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
    cotizaciones_qs = Cotizacion.objects.filter(anio=anio) if anio else Cotizacion.objects.none()
    q = request.GET.get("q", "").strip()
    orden = request.GET.get("orden", "desc").lower()
    if orden not in {"asc", "desc"}:
        orden = "desc"

    if q:
        cotizaciones_qs = cotizaciones_qs.filter(
            Q(consecutivo__icontains=q)
            | Q(cliente__icontains=q)
            | Q(tipo__icontains=q)
            | Q(fecha_solicitud__icontains=q)
            | Q(fecha_envio__icontains=q)
            | Q(ejecutivo__username__icontains=q)
            | Q(ejecutivo__first_name__icontains=q)
            | Q(ejecutivo__last_name__icontains=q)
        )

    cotizaciones = list(cotizaciones_qs)
    cotizaciones.sort(
        key=lambda c: (_extraer_consecutivo(c.consecutivo), c.consecutivo),
        reverse=orden == "desc",
    )
    ejecutivos = User.objects.all().order_by("username")

    if request.GET.get("partial") == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(
            request,
            "cotizaciones/_cotizaciones_rows.html",
            {
                "cotizaciones": cotizaciones,
                "usuarios": ejecutivos,
                "anio_seleccionado": anio,
                "orden": orden,
            },
        )

    return render(
        request,
        "cotizaciones/lista_cotizaciones.html",
        {
            "cotizaciones": cotizaciones,
            "anios": anios,
            "anio_seleccionado": anio,
            "usuarios": ejecutivos,
            "q": q,
            "orden": orden,
        },
    )


@login_required
def importar_cotizaciones_csv(request):
    if request.method != "POST":
        return redirect("lista_cotizaciones")
    _requiere_admin(request.user)
    archivo = request.FILES.get("archivo_csv")
    if not archivo:
        messages.error(request, "Selecciona un archivo CSV para importar cotizaciones.")
        return redirect("lista_cotizaciones")

    try:
        filas = _leer_csv_subido(archivo)
        creados, actualizados, omitidos, anios_tocados = _importar_cotizaciones_desde_filas(filas)
        messages.success(
            request,
            f"Cotizaciones importadas. Creadas: {creados}, actualizadas: {actualizados}, omitidas: {omitidos}.",
        )
        if anios_tocados:
            return redirect(f"{reverse('lista_cotizaciones')}?anio={max(anios_tocados)}")
    except Exception as exc:
        messages.error(request, f"No se pudo importar cotizaciones: {exc}")
    return redirect("lista_cotizaciones")


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
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form.fields["cliente"].initial = cliente_param

    context = {"form": form}
    context.update(_contexto_clientes(request))
    return render(request, "cotizaciones/crear_cotizacion.html", context)


@login_required
def editar_cotizacion(request, pk):
    cotizacion = get_object_or_404(Cotizacion, pk=pk)

    if request.method == "POST":
        form = CotizacionForm(request.POST, instance=cotizacion)
        if form.is_valid():
            form.save()
            return redirect("lista_cotizaciones")
    else:
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form = CotizacionForm(instance=cotizacion, initial={"cliente": cliente_param})
        else:
            form = CotizacionForm(instance=cotizacion)

    context = {"form": form}
    context.update(_contexto_clientes(request))
    return render(request, "cotizaciones/crear_cotizacion.html", context)


@login_required
@require_POST
def eliminar_cotizacion(request, pk):
    _requiere_admin(request.user)
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    cotizacion.delete()
    return redirect("lista_cotizaciones")


@login_required
@require_POST
def cambiar_ejecutivo_cotizacion(request, pk):
    _requiere_admin(request.user)
    cotizacion = get_object_or_404(Cotizacion, pk=pk)
    user_id = request.POST.get("ejecutivo")
    cotizacion.ejecutivo = get_object_or_404(User, id=user_id) if user_id else None
    cotizacion.save()

    anio = request.POST.get("anio")
    if anio and anio.isdigit():
        return redirect(f"{reverse('lista_cotizaciones')}?anio={anio}")
    return redirect("lista_cotizaciones")


@login_required
def lista_referencias(request):
    consecutivo_expr = Cast(
        Substr("referencia", Length("referencia") - 2, 3),
        IntegerField(),
    )
    referencias_qs = Referencia.objects.annotate(
        consecutivo_orden=consecutivo_expr
    )
    q = request.GET.get("q", "").strip()
    orden = request.GET.get("orden", "desc").lower()
    if orden not in {"asc", "desc"}:
        orden = "desc"

    if q:
        referencias_qs = referencias_qs.filter(
            Q(referencia__icontains=q)
            | Q(cliente__icontains=q)
            | Q(servicio__icontains=q)
            | Q(agencia_aduanal__icontains=q)
            | Q(fecha__icontains=q)
            | Q(ejecutivo__username__icontains=q)
            | Q(ejecutivo__first_name__icontains=q)
            | Q(ejecutivo__last_name__icontains=q)
        )

    if orden == "desc":
        referencias = referencias_qs.order_by("-consecutivo_orden", "-referencia")
    else:
        referencias = referencias_qs.order_by("consecutivo_orden", "referencia")
    ejecutivos = User.objects.all().order_by("username")

    if request.GET.get("partial") == "1" or request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return render(
            request,
            "referencias/_referencias_rows.html",
            {"referencias": referencias, "usuarios": ejecutivos, "orden": orden},
        )
    return render(
        request,
        "referencias/lista_referencias.html",
        {
            "referencias": referencias,
            "usuarios": ejecutivos,
            "q": q,
            "orden": orden,
        },
    )


@login_required
def importar_referencias_csv(request):
    if request.method != "POST":
        return redirect("lista_referencias")
    _requiere_admin(request.user)
    archivo = request.FILES.get("archivo_csv")
    if not archivo:
        messages.error(request, "Selecciona un archivo CSV para importar referencias.")
        return redirect("lista_referencias")

    try:
        filas = _leer_csv_subido(archivo)
        creados, actualizados, omitidos = _importar_referencias_desde_filas(filas)
        messages.success(
            request,
            f"Referencias importadas. Creadas: {creados}, actualizadas: {actualizados}, omitidas: {omitidos}.",
        )
    except Exception as exc:
        messages.error(request, f"No se pudo importar referencias: {exc}")
    return redirect("lista_referencias")


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
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form.fields["cliente"].initial = cliente_param

    context = {"form": form}
    context.update(_contexto_clientes(request))
    return render(request, "referencias/crear_referencia.html", context)


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
        cliente_param = request.GET.get("cliente")
        if cliente_param:
            form = ReferenciaForm(instance=referencia, initial={"cliente": cliente_param})
        else:
            form = ReferenciaForm(instance=referencia)

    context = {"form": form}
    context.update(_contexto_clientes(request))
    return render(request, "referencias/crear_referencia.html", context)


@login_required
@require_POST
def eliminar_referencia(request, pk):
    _requiere_admin(request.user)
    referencia = get_object_or_404(Referencia, pk=pk)
    referencia.delete()
    return redirect("lista_referencias")


@login_required
@require_POST
def cambiar_ejecutivo_referencia(request, pk):
    _requiere_admin(request.user)
    referencia = get_object_or_404(Referencia, pk=pk)
    user_id = request.POST.get("ejecutivo")
    referencia.ejecutivo = get_object_or_404(User, id=user_id) if user_id else None
    referencia.save()
    return redirect("lista_referencias")
