from django.db import migrations


def poblar_columnas_iniciales(apps, schema_editor):
    PanelCotizacion = apps.get_model("panel_cotizaciones", "PanelCotizacion")
    PanelCotizacionColumna = apps.get_model(
        "panel_cotizaciones",
        "PanelCotizacionColumna",
    )

    columnas_iniciales = (
        ("REQUERIMIENTO", "Requerimiento", 1),
        ("EN_PROGRESO", "En progreso", 2),
        ("ENVIADA", "Enviada", 3),
    )

    columnas_por_codigo = {}
    for codigo, nombre, orden in columnas_iniciales:
        columna, _created = PanelCotizacionColumna.objects.update_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "orden": orden,
                "activa": True,
            },
        )
        columnas_por_codigo[codigo] = columna

    for codigo, _nombre, _orden in columnas_iniciales:
        PanelCotizacion.objects.filter(estado=codigo).update(
            columna=columnas_por_codigo[codigo],
        )


def revertir_columnas_iniciales(apps, schema_editor):
    PanelCotizacion = apps.get_model("panel_cotizaciones", "PanelCotizacion")
    PanelCotizacionColumna = apps.get_model(
        "panel_cotizaciones",
        "PanelCotizacionColumna",
    )
    PanelCotizacion.objects.update(columna=None)
    PanelCotizacionColumna.objects.filter(
        codigo__in=["REQUERIMIENTO", "EN_PROGRESO", "ENVIADA"]
    ).delete()


class Migration(migrations.Migration):
    dependencies = [
        (
            "panel_cotizaciones",
            "0005_panelcotizacioncolumna_panelcotizacion_columna",
        ),
    ]

    operations = [
        migrations.RunPython(
            poblar_columnas_iniciales,
            revertir_columnas_iniciales,
        ),
    ]
