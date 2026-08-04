from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from django.apps import apps
from django.db import transaction
from django.db.models import ProtectedError, QuerySet, RestrictedError
from django.utils import timezone


TRASH_RETENTION_DAYS = 30


class TrashOperationError(Exception):
    pass


@dataclass(frozen=True)
class TrashModelConfig:
    tipo: str
    app_label: str
    model_name: str
    modulo_label: str
    titulo_attr: str
    cliente_attr: str | None = None
    estado_attr: str | None = None
    columna_attr: str | None = None
    fecha_attr: str | None = None
    responsable_attr: str | None = None
    archivo_related_name: str | None = None
    select_related: tuple[str, ...] = ()
    prefetch_related: tuple[str, ...] = ()

    @property
    def model(self):
        return apps.get_model(self.app_label, self.model_name)


TRASH_MODELS: dict[str, TrashModelConfig] = {
    "operacion": TrashModelConfig(
        tipo="operacion",
        app_label="operaciones",
        model_name="Operacion",
        modulo_label="Operaciones",
        titulo_attr="titulo",
        cliente_attr="cliente",
        estado_attr="estado",
        columna_attr="columna",
        fecha_attr="fecha_vencimiento",
        responsable_attr="creado_por",
        archivo_related_name="archivos",
        select_related=("cliente", "creado_por", "columna", "eliminado_por"),
        prefetch_related=("asignados", "etiquetas", "opciones"),
    ),
    "garantia": TrashModelConfig(
        tipo="garantia",
        app_label="garantias",
        model_name="Garantia",
        modulo_label="Garantías",
        titulo_attr="titulo",
        cliente_attr="cliente",
        estado_attr="estado",
        columna_attr="columna",
        fecha_attr="fecha_vencimiento",
        responsable_attr="creado_por",
        archivo_related_name="archivos",
        select_related=("cliente", "creado_por", "columna", "eliminado_por"),
        prefetch_related=("asignados", "etiquetas"),
    ),
    "cotizacion": TrashModelConfig(
        tipo="cotizacion",
        app_label="panel_cotizaciones",
        model_name="PanelCotizacion",
        modulo_label="Panel de cotizaciones",
        titulo_attr="titulo",
        cliente_attr="cliente",
        estado_attr="estado",
        columna_attr="columna",
        fecha_attr="fecha_vencimiento",
        responsable_attr="creado_por",
        archivo_related_name="archivos",
        select_related=("creado_por", "columna", "eliminado_por"),
        prefetch_related=("asignados", "etiquetas"),
    ),
    "cuenta_gastos": TrashModelConfig(
        tipo="cuenta_gastos",
        app_label="cuenta_gastos",
        model_name="CuentaGastos",
        modulo_label="Cuenta de gastos",
        titulo_attr="titulo",
        cliente_attr="cliente",
        estado_attr="estado",
        columna_attr="columna",
        fecha_attr="fecha_vencimiento",
        responsable_attr="creado_por",
        archivo_related_name="archivos",
        select_related=("cliente", "creado_por", "columna", "eliminado_por"),
        prefetch_related=("asignados", "etiquetas", "opciones"),
    ),
    "solicitud": TrashModelConfig(
        tipo="solicitud",
        app_label="solicitudes",
        model_name="Solicitud",
        modulo_label="Solicitudes",
        titulo_attr="sg",
        cliente_attr="cliente",
        fecha_attr="fecha_recepcion",
        responsable_attr="ejecutivo",
        select_related=("ejecutivo", "eliminado_por", "referencia_generada"),
    ),
    "cotizacion_ref": TrashModelConfig(
        tipo="cotizacion_ref",
        app_label="solicitudes",
        model_name="Cotizacion",
        modulo_label="Cotizaciones-ref",
        titulo_attr="consecutivo",
        cliente_attr="cliente",
        estado_attr="estado",
        fecha_attr="fecha_solicitud",
        responsable_attr="ejecutivo",
        select_related=("ejecutivo", "eliminado_por"),
    ),
    "referencia": TrashModelConfig(
        tipo="referencia",
        app_label="solicitudes",
        model_name="Referencia",
        modulo_label="Referencias",
        titulo_attr="referencia",
        cliente_attr="cliente",
        fecha_attr="fecha",
        responsable_attr="ejecutivo",
        select_related=("ejecutivo", "eliminado_por", "solicitud_origen", "operacion_generada"),
    ),
}

MODEL_TO_TIPO = {
    (config.app_label, config.model_name.lower()): tipo
    for tipo, config in TRASH_MODELS.items()
}


def get_trash_config(tipo: str) -> TrashModelConfig:
    config = TRASH_MODELS.get(tipo)
    if config is None:
        raise TrashOperationError("Tipo de elemento no permitido.")
    return config


def get_active_queryset(model) -> QuerySet:
    return model.objects.filter(eliminado_en__isnull=True)


def get_deleted_queryset(model) -> QuerySet:
    return model.objects.filter(eliminado_en__isnull=False)


def get_trash_queryset(tipo: str, *, deleted_only: bool = True) -> QuerySet:
    config = get_trash_config(tipo)
    queryset = config.model.objects.all()
    if config.select_related:
        queryset = queryset.select_related(*config.select_related)
    if config.prefetch_related:
        queryset = queryset.prefetch_related(*config.prefetch_related)
    if deleted_only:
        queryset = queryset.filter(eliminado_en__isnull=False)
    return queryset


def obtener_elemento_papelera(tipo: str, objeto_id: int, *, require_deleted: bool = True):
    config = get_trash_config(tipo)
    queryset = config.model.objects.all()
    if config.select_related:
        queryset = queryset.select_related(*config.select_related)
    if config.prefetch_related:
        queryset = queryset.prefetch_related(*config.prefetch_related)
    queryset = queryset.filter(pk=objeto_id)
    if require_deleted:
        queryset = queryset.filter(eliminado_en__isnull=False)
    return queryset.first()


def _get_tipo_from_object(objeto) -> str:
    key = (objeto._meta.app_label, objeto.__class__.__name__.lower())
    tipo = MODEL_TO_TIPO.get(key)
    if tipo is None:
        raise TrashOperationError("El modelo no está registrado en la papelera.")
    return tipo


def _resolver_columna_restauracion(objeto):
    if not hasattr(objeto, "columna_id") or not hasattr(objeto, "estado"):
        return None
    columna = getattr(objeto, "columna", None)
    if columna is not None and getattr(columna, "activa", True):
        return columna
    columna_field = objeto._meta.get_field("columna")
    columna_model = columna_field.related_model
    return columna_model.objects.filter(activa=True).order_by("orden", "id").first()


@transaction.atomic
def enviar_a_papelera(objeto, usuario):
    _get_tipo_from_object(objeto)
    if getattr(objeto, "eliminado_en", None) is not None:
        raise TrashOperationError("El elemento ya está en la papelera.")
    objeto.eliminado_en = timezone.now()
    objeto.eliminado_por = usuario
    objeto.save(update_fields=["eliminado_en", "eliminado_por"])
    return objeto


@transaction.atomic
def restaurar_desde_papelera(objeto, usuario=None):
    _get_tipo_from_object(objeto)
    if getattr(objeto, "eliminado_en", None) is None:
        raise TrashOperationError("El elemento no está en la papelera.")

    update_fields = ["eliminado_en", "eliminado_por"]
    columna = _resolver_columna_restauracion(objeto)
    if columna is not None:
        objeto.columna = columna
        if hasattr(objeto, "estado"):
            objeto.estado = columna.codigo
            update_fields.extend(["columna", "estado"])
        else:
            update_fields.append("columna")
    objeto.eliminado_en = None
    objeto.eliminado_por = None
    objeto.save(update_fields=update_fields)
    return objeto


def _eliminar_archivos_relacionados(objeto, related_name: str | None):
    if not related_name:
        return
    manager = getattr(objeto, related_name, None)
    if manager is None:
        return
    for archivo in manager.all():
        campo = getattr(archivo, "archivo", None)
        if campo:
            campo.delete(save=False)


@transaction.atomic
def eliminar_definitivamente(objeto, usuario=None):
    tipo = _get_tipo_from_object(objeto)
    if getattr(objeto, "eliminado_en", None) is None:
        raise TrashOperationError(
            "El elemento debe estar en la papelera antes de eliminarse definitivamente."
        )
    config = get_trash_config(tipo)
    _eliminar_archivos_relacionados(objeto, config.archivo_related_name)
    try:
        objeto.delete()
    except (ProtectedError, RestrictedError) as exc:
        raise TrashOperationError(
            "No se puede eliminar definitivamente porque existen relaciones protegidas."
        ) from exc


def obtener_resumen_papelera(objeto, tipo: str):
    config = get_trash_config(tipo)
    cliente = getattr(objeto, config.cliente_attr, None) if config.cliente_attr else None
    if hasattr(cliente, "nombre"):
        cliente = cliente.nombre
    responsable = getattr(objeto, config.responsable_attr, None) if config.responsable_attr else None
    if responsable is not None:
        responsable = getattr(responsable, "get_full_name", lambda: "")() or getattr(responsable, "username", str(responsable))
    columna = getattr(objeto, config.columna_attr, None) if config.columna_attr else None
    if columna is not None and hasattr(columna, "nombre"):
        estado = columna.nombre
    elif config.estado_attr:
        display_method = getattr(objeto, f"get_{config.estado_attr}_display", None)
        estado = display_method() if callable(display_method) else getattr(objeto, config.estado_attr, "")
    else:
        estado = ""

    eliminado_en = getattr(objeto, "eliminado_en", None)
    dias_transcurridos = None
    dias_restantes = None
    if eliminado_en is not None:
        ahora = timezone.now()
        dias_transcurridos = max(0, (ahora - eliminado_en).days)
        limite = eliminado_en + timedelta(days=TRASH_RETENTION_DAYS)
        dias_restantes = max(0, (limite - ahora).days)

    eliminado_por = getattr(objeto, "eliminado_por", None)
    if eliminado_por is not None:
        eliminado_por = eliminado_por.get_full_name() or eliminado_por.username

    return {
        "tipo": tipo,
        "id": objeto.pk,
        "modulo": config.modulo_label,
        "titulo": getattr(objeto, config.titulo_attr, ""),
        "cliente": cliente or "",
        "estado": estado or "",
        "fecha": getattr(objeto, config.fecha_attr, None) if config.fecha_attr else None,
        "responsable": responsable or "",
        "eliminado_en": eliminado_en,
        "eliminado_por": eliminado_por or "",
        "dias_transcurridos": dias_transcurridos,
        "dias_restantes": dias_restantes,
    }


def obtener_elementos_eliminados(tipo: str | None = None):
    tipos = [tipo] if tipo else list(TRASH_MODELS.keys())
    elementos = []
    for current_tipo in tipos:
        config = get_trash_config(current_tipo)
        queryset = config.model.objects.filter(eliminado_en__isnull=False)
        if config.select_related:
            queryset = queryset.select_related(*config.select_related)
        if config.prefetch_related:
            queryset = queryset.prefetch_related(*config.prefetch_related)
        for objeto in queryset.order_by("-eliminado_en", "-pk"):
            elementos.append(obtener_resumen_papelera(objeto, current_tipo))
    elementos.sort(key=lambda item: (item["eliminado_en"] is not None, item["eliminado_en"]), reverse=True)
    return elementos
