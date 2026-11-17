"""Consultas acotadas para el listado de la papelera.

La unión contiene únicamente ID, fecha y posición del modelo. Los objetos y
sus relaciones de presentación se cargan después de paginar esa unión.
"""

from django.core.paginator import Paginator
from django.db.models import IntegerField, Q, Value

from solicitudes.views import puede_crear

from .trash import TRASH_MODELS, obtener_resumen_papelera


PAGE_SIZE = 30


def _queryset_accesible(user, tipo, *, busqueda="", acceso_operaciones=False, puede_crear_referencia=False):
    config = TRASH_MODELS[tipo]
    queryset = config.model.objects.filter(eliminado_en__isnull=False)
    if not user.is_superuser:
        if tipo in {"operacion_etiqueta", "documento_repositorio"}:
            return queryset.none()
        if tipo == "operacion":
            if not acceso_operaciones:
                queryset = queryset.filter(Q(creado_por_id=user.pk) | Q(asignados=user)).distinct()
        elif tipo == "cuenta_gastos":
            queryset = queryset.filter(Q(creado_por_id=user.pk) | Q(asignados=user)).distinct()
        elif tipo in {"garantia", "cotizacion"}:
            if not user.is_active:
                return queryset.none()
        elif tipo in {"solicitud", "cotizacion_ref"}:
            queryset = queryset.filter(ejecutivo_id=user.pk)
        elif tipo == "referencia" and not puede_crear_referencia:
            queryset = queryset.filter(ejecutivo_id=user.pk)

    if busqueda:
        search = Q(**{f"{config.titulo_attr}__icontains": busqueda})
        if config.cliente_attr:
            field = config.model._meta.get_field(config.cliente_attr)
            client_lookup = (
                f"{config.cliente_attr}__nombre__icontains"
                if field.is_relation else f"{config.cliente_attr}__icontains"
            )
            search |= Q(**{client_lookup: busqueda})
        queryset = queryset.filter(search)
    return queryset


def _summary_relations(config):
    """Solo las relaciones que utiliza obtener_resumen_papelera."""
    names = (config.cliente_attr, config.columna_attr, config.responsable_attr, "eliminado_por")
    return tuple(
        name for name in dict.fromkeys(names)
        if name and config.model._meta.get_field(name).is_relation
    )


def consultar_papelera(user, *, tipo="", busqueda="", pagina=1):
    """Devuelve (resúmenes, página) con orden estable entre los nueve modelos."""
    acceso_operaciones = bool(
        user.is_staff or user.groups.filter(
            Q(name__icontains="admin") | Q(name__icontains="ejecutivo")
        ).exists()
    ) if not user.is_superuser else True
    puede_crear_referencia = puede_crear(user) if not user.is_superuser else True

    tipos = [tipo] if tipo else list(TRASH_MODELS)
    ramas = []
    for posicion, nombre in enumerate(TRASH_MODELS):
        if nombre not in tipos:
            continue
        queryset = _queryset_accesible(
            user, nombre, busqueda=busqueda,
            acceso_operaciones=acceso_operaciones,
            puede_crear_referencia=puede_crear_referencia,
        )
        ramas.append(
            queryset.order_by().values("pk", "eliminado_en")
            .annotate(tipo_orden=Value(posicion, output_field=IntegerField()))
            .values("pk", "eliminado_en", "tipo_orden")
        )

    # UNION ALL permite al motor ordenar y limitar sin materializar registros
    # completos de cada tabla en Python. La posición y el ID desempatan fechas.
    union = ramas[0].union(*ramas[1:], all=True) if len(ramas) > 1 else ramas[0]
    union = union.order_by("-eliminado_en", "tipo_orden", "-pk")
    page = Paginator(union, PAGE_SIZE).get_page(pagina)
    keys = list(page.object_list)
    ids_por_tipo = {}
    nombres = list(TRASH_MODELS)
    for key in keys:
        nombre = nombres[key["tipo_orden"]]
        ids_por_tipo.setdefault(nombre, []).append(key["pk"])

    objetos = {}
    for nombre, ids in ids_por_tipo.items():
        config = TRASH_MODELS[nombre]
        queryset = config.model.objects.filter(pk__in=ids, eliminado_en__isnull=False)
        relations = _summary_relations(config)
        if relations:
            queryset = queryset.select_related(*relations)
        objetos.update({(nombre, obj.pk): obj for obj in queryset})

    summaries = []
    for key in keys:
        nombre = nombres[key["tipo_orden"]]
        obj = objetos.get((nombre, key["pk"]))
        if obj is not None:
            summaries.append(obtener_resumen_papelera(obj, nombre))
    return summaries, page
