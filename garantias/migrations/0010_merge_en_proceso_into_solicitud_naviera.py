from django.db import migrations


CODIGO_SUPERVIVIENTE = "SOLICITUD_NAVIERA"
CODIGO_ELIMINADO = "EN_PROCESO"
NOMBRE_FINAL = "En proceso"


def fusionar_columnas_en_proceso(apps, schema_editor):
    Garantia = apps.get_model("garantias", "Garantia")
    GarantiaColumna = apps.get_model("garantias", "GarantiaColumna")

    columna_superviviente = (
        GarantiaColumna.objects.filter(codigo=CODIGO_SUPERVIVIENTE).first()
    )
    columna_eliminada = (
        GarantiaColumna.objects.filter(codigo=CODIGO_ELIMINADO).first()
    )

    if columna_superviviente is None and columna_eliminada is None:
        return

    if columna_superviviente is None and columna_eliminada is not None:
        columna_eliminada.codigo = CODIGO_SUPERVIVIENTE
        columna_eliminada.nombre = NOMBRE_FINAL
        columna_eliminada.save(update_fields=["codigo", "nombre", "fecha_actualizacion"])
        Garantia.objects.filter(columna_id=columna_eliminada.pk).update(
            columna_id=columna_eliminada.pk,
            estado=CODIGO_SUPERVIVIENTE,
        )
        Garantia.objects.filter(
            estado=CODIGO_ELIMINADO,
            columna__isnull=True,
        ).update(estado=CODIGO_SUPERVIVIENTE, columna_id=columna_eliminada.pk)
        return

    columna_superviviente.nombre = NOMBRE_FINAL
    columna_superviviente.activa = True
    columna_superviviente.save(
        update_fields=["nombre", "activa", "fecha_actualizacion"]
    )

    Garantia.objects.filter(
        estado=CODIGO_SUPERVIVIENTE,
        columna__isnull=True,
    ).update(columna_id=columna_superviviente.pk)

    if columna_eliminada is not None and columna_eliminada.pk != columna_superviviente.pk:
        Garantia.objects.filter(columna_id=columna_eliminada.pk).update(
            columna_id=columna_superviviente.pk,
            estado=CODIGO_SUPERVIVIENTE,
        )
        Garantia.objects.filter(
            estado=CODIGO_ELIMINADO,
        ).update(
            estado=CODIGO_SUPERVIVIENTE,
            columna_id=columna_superviviente.pk,
        )
        columna_eliminada.delete()
    else:
        Garantia.objects.filter(estado=CODIGO_ELIMINADO).update(
            estado=CODIGO_SUPERVIVIENTE,
            columna_id=columna_superviviente.pk,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("garantias", "0009_garantia_eliminado_en_garantia_eliminado_por"),
    ]

    operations = [
        migrations.RunPython(
            fusionar_columnas_en_proceso,
            migrations.RunPython.noop,
        ),
    ]
