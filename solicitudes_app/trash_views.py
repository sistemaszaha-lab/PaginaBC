from __future__ import annotations

import json

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_GET, require_POST

from cuenta_gastos.views import _puede_modificar_cuenta
from garantias.views import _puede_operar_garantias
from operaciones.views import _puede_modificar_operacion
from panel_cotizaciones.views import _puede_operar_panel
from solicitudes.views import (
    _es_admin,
    _puede_restaurar_cotizacion,
    _puede_restaurar_referencia,
    _puede_restaurar_solicitud,
)

from .trash import (
    TRASH_MODELS,
    TrashOperationError,
    eliminar_definitivamente,
    get_trash_config,
    obtener_elemento_papelera,
    obtener_elementos_eliminados,
    obtener_resumen_papelera,
    restaurar_desde_papelera,
)


FILTER_CHOICES = (
    ("", "Todos"),
    ("solicitud", "Solicitudes"),
    ("cotizacion_ref", "Cotizaciones-ref"),
    ("referencia", "Referencias"),
    ("operacion", "Operaciones"),
    ("garantia", "Garantías"),
    ("cotizacion", "Panel de cotizaciones"),
    ("cuenta_gastos", "Cuenta de gastos"),
)
FILTER_LABELS = {value: label for value, label in FILTER_CHOICES if value}

TIPO_ALIASES = {
    "panel_cotizacion": "cotizacion",
    "panel_cotizaciones": "cotizacion",
}


def _normalize_tipo(tipo: str | None) -> str:
    value = (tipo or "").strip()
    return TIPO_ALIASES.get(value, value)


def _json_error(message: str, *, status: int = 400, **extra):
    payload = {"ok": False, "message": message}
    payload.update(extra)
    return JsonResponse(payload, status=status)


def _can_access_item(user, tipo: str, obj) -> bool:
    if not user.is_authenticated:
        return False
    if _es_admin(user):
        return True
    if tipo == "operacion":
        return _puede_modificar_operacion(user, obj)
    if tipo == "garantia":
        return _puede_operar_garantias(user)
    if tipo == "cotizacion":
        return _puede_operar_panel(user)
    if tipo == "cuenta_gastos":
        return _puede_modificar_cuenta(user, obj)
    if tipo == "solicitud":
        return _puede_restaurar_solicitud(user, obj)
    if tipo == "cotizacion_ref":
        return _puede_restaurar_cotizacion(user, obj)
    if tipo == "referencia":
        return _puede_restaurar_referencia(user, obj)
    return False


def _can_delete_permanently(user, tipo: str, obj) -> bool:
    return bool(user.is_authenticated and _es_admin(user))


def _parse_items_payload(request: HttpRequest):
    try:
        payload = json.loads(request.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise TrashOperationError("El cuerpo de la solicitud debe ser JSON válido.")

    items = payload.get("items")
    if not isinstance(items, list) or not items:
        raise TrashOperationError("Debes enviar una lista no vacía de elementos.")

    normalized = []
    seen = set()
    for item in items:
        if not isinstance(item, dict):
            raise TrashOperationError("Cada elemento debe ser un objeto JSON válido.")
        tipo = _normalize_tipo(item.get("tipo"))
        if tipo not in TRASH_MODELS:
            raise TrashOperationError("Uno o más tipos de elemento no están permitidos.")
        item_id = item.get("id")
        if not isinstance(item_id, int) or item_id <= 0:
            raise TrashOperationError("Uno o más IDs son inválidos.")
        key = (tipo, item_id)
        if key in seen:
            raise TrashOperationError("No se permiten elementos duplicados en la selección.")
        seen.add(key)
        normalized.append({"tipo": tipo, "id": item_id})
    return normalized


@login_required
@require_GET
def papelera(request: HttpRequest):
    tipo = _normalize_tipo(request.GET.get("tipo"))
    if tipo and tipo not in TRASH_MODELS:
        tipo = ""

    items = []
    for item in obtener_elementos_eliminados(tipo or None):
        obj = obtener_elemento_papelera(item["tipo"], item["id"])
        if obj is None:
            continue
        if not _can_access_item(request.user, item["tipo"], obj):
            continue
        item["tipo_label"] = FILTER_LABELS.get(item["tipo"], item["tipo"])
        item["puede_restaurar"] = _can_access_item(request.user, item["tipo"], obj)
        item["puede_eliminar_definitivamente"] = _can_delete_permanently(
            request.user, item["tipo"], obj
        )
        items.append(item)

    context = {
        "current": "papelera",
        "papelera_items": items,
        "papelera_total": len(items),
        "papelera_tipo_actual": tipo,
        "papelera_filtros": [
            {
                "value": value,
                "label": label,
                "active": value == tipo,
            }
            for value, label in FILTER_CHOICES
        ],
        "papelera_can_delete": _es_admin(request.user),
    }
    return render(request, "papelera/panel.html", context)


@login_required
@require_POST
def restaurar_elemento(request: HttpRequest, tipo: str, pk: int):
    tipo = _normalize_tipo(tipo)
    try:
        get_trash_config(tipo)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=400)

    obj = obtener_elemento_papelera(tipo, pk)
    if obj is None:
        return _json_error("El elemento no existe o no está disponible.", status=404)
    if not _can_access_item(request.user, tipo, obj):
        return _json_error("No tienes permisos para restaurar este elemento.", status=403)
    try:
        restaurar_desde_papelera(obj, request.user)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=409)
    return JsonResponse(
        {
            "ok": True,
            "message": "El elemento se restauró correctamente.",
            "item": obtener_resumen_papelera(obj, tipo),
        }
    )


@login_required
@require_POST
def eliminar_elemento_definitivamente(request: HttpRequest, tipo: str, pk: int):
    tipo = _normalize_tipo(tipo)
    try:
        get_trash_config(tipo)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=400)

    obj = obtener_elemento_papelera(tipo, pk)
    if obj is None:
        return _json_error("El elemento no existe o no está disponible.", status=404)
    if not _can_delete_permanently(request.user, tipo, obj):
        return _json_error(
            "No tienes permisos para eliminar definitivamente este elemento.",
            status=403,
        )
    try:
        eliminar_definitivamente(obj, request.user)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=409)
    return JsonResponse(
        {
            "ok": True,
            "message": "El elemento se eliminó definitivamente.",
        }
    )


@login_required
@require_POST
def restaurar_seleccion(request: HttpRequest):
    try:
        items = _parse_items_payload(request)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=400)

    processed = 0
    errors = []
    for item in items:
        obj = obtener_elemento_papelera(item["tipo"], item["id"])
        if obj is None:
            errors.append({**item, "message": "El elemento no existe o no está disponible."})
            continue
        if not _can_access_item(request.user, item["tipo"], obj):
            errors.append({**item, "message": "No tienes permisos para restaurar este elemento."})
            continue
        try:
            restaurar_desde_papelera(obj, request.user)
        except TrashOperationError as exc:
            errors.append({**item, "message": str(exc)})
            continue
        processed += 1

    return JsonResponse(
        {
            "ok": not errors,
            "procesados": processed,
            "omitidos": len(items) - processed,
            "errores": errors,
            "message": (
                "Se restauraron los elementos seleccionados."
                if processed
                else "No se pudo restaurar la selección."
            ),
        },
        status=200 if processed else 409,
    )


@login_required
@require_POST
def eliminar_seleccion(request: HttpRequest):
    if not _es_admin(request.user):
        return _json_error(
            "No tienes permisos para eliminar definitivamente elementos.",
            status=403,
        )
    try:
        items = _parse_items_payload(request)
    except TrashOperationError as exc:
        return _json_error(str(exc), status=400)

    processed = 0
    errors = []
    for item in items:
        obj = obtener_elemento_papelera(item["tipo"], item["id"])
        if obj is None:
            errors.append({**item, "message": "El elemento no existe o no está disponible."})
            continue
        try:
            eliminar_definitivamente(obj, request.user)
        except TrashOperationError as exc:
            errors.append({**item, "message": str(exc)})
            continue
        processed += 1

    return JsonResponse(
        {
            "ok": not errors,
            "procesados": processed,
            "omitidos": len(items) - processed,
            "errores": errors,
            "message": (
                "Se eliminaron definitivamente los elementos seleccionados."
                if processed
                else "No se pudo eliminar la selección."
            ),
        },
        status=200 if processed else 409,
    )
