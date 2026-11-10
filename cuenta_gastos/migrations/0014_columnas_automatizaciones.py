"""Añade columnas dedicadas sin alterar el catálogo del cliente.

VOBO_ANGIE ya fue asignado por 0006: nunca se infiere ni reasigna por nombre.
Si no coincide el catálogo real, la migración se detiene para revisión.
Los códigos NUEVOS deben estar libres: un código ocupado no prueba procedencia.
La repetición normal de migrate es idempotente por el historial de Django;
no se admite reaplicar manualmente esta operación para adoptar filas existentes.
La reversión conserva las columnas y las tarjetas que pudieran utilizarlas.
"""
import unicodedata

from django.db import migrations
from django.db.models import Max


def normalizar(nombre):
    texto = unicodedata.normalize("NFKD", nombre)
    return " ".join("".join(c for c in texto if not unicodedata.combining(c)).casefold().split())


def validar(columna_modelo, codigo, nombre, alias, *, requerida=False):
    columnas = list(columna_modelo.objects.using(alias).all())
    existente = next((c for c in columnas if c.codigo == codigo), None)
    # Solo se usa el nombre en la comprobación de conflictos inicial, nunca
    # como identidad del flujo ni para adoptar una columna del cliente.
    if any(normalizar(c.nombre) == normalizar(nombre) and c.codigo != codigo for c in columnas):
        raise RuntimeError(
            f"Catálogo ambiguo en {columna_modelo._meta.label}: '{nombre}' usa otro código. "
            "Revisar manualmente; no se modificó ninguna columna."
        )
    if requerida and existente is None:
        raise RuntimeError(f"Falta el código histórico {codigo}; no se puede identificar VoBo Angie con seguridad.")
    if existente is not None and not existente.activa:
        raise RuntimeError(f"El código reservado {codigo} está inactivo; revisar el catálogo sin reasignarlo.")
    if existente is not None and not requerida:
        raise RuntimeError(
            f"Conflicto en {columna_modelo._meta.label}: el código reservado {codigo} "
            "ya está ocupado. No se reutilizará esa columna ni se alterarán sus datos. "
            "Revisar su procedencia y el historial de migraciones antes de continuar."
        )
    return existente


def crear_columnas(apps, schema_editor):
    alias = schema_editor.connection.alias
    OperacionColumna = apps.get_model("operaciones", "OperacionColumna")
    CuentaGastosColumna = apps.get_model("cuenta_gastos", "CuentaGastosColumna")
    if schema_editor.connection.vendor == "postgresql":
        # Evita que una edición del catálogo invalide la comprobación previa.
        # El bloqueo vive solo durante esta migración atómica, no en el servicio.
        tablas = ", ".join(schema_editor.quote_name(m._meta.db_table)
                           for m in (OperacionColumna, CuentaGastosColumna))
        schema_editor.execute(f"LOCK TABLE {tablas} IN SHARE ROW EXCLUSIVE MODE")
    validar(CuentaGastosColumna, "VOBO_ANGIE", "VoBo Angie", alias, requerida=True)
    nuevas = (
        (OperacionColumna, "FACTURA_FLETES_1", "Factura de Fletes 1"),
        (CuentaGastosColumna, "FACTURA_FLETES_1", "Factura de Fletes 1"),
        (CuentaGastosColumna, "SOLICITUDES_GEO_1", "Solicitudes a Geo 1"),
    )
    for modelo, codigo, nombre in nuevas:
        validar(modelo, codigo, nombre, alias)
    # Validar TODO antes de escribir. No cambia nombres, códigos, actividad,
    # visibilidad ni orden de las filas existentes.
    for modelo, codigo, nombre in nuevas:
        qs = modelo.objects.using(alias)
        orden = (qs.aggregate(maximo=Max("orden"))["maximo"] or 0) + 1
        qs.create(codigo=codigo, nombre=nombre, orden=orden, activa=True)


class Migration(migrations.Migration):
    atomic = True
    dependencies = [
        ("cuenta_gastos", "0013_cuentagastos_vobo_angie_origen"),
        ("operaciones", "0014_operacioncolumna_usuarios_visibles_and_more"),
    ]
    operations = [migrations.RunPython(crear_columnas, migrations.RunPython.noop)]
