from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("solicitudes", "0011_cotizacion_eliminado_en_cotizacion_eliminado_por_and_more"),
        ("panel_cotizaciones", "0008_panelcotizacionelementoaccion"),
    ]

    operations = [
        migrations.AddField(
            model_name="panelcotizacion",
            name="solicitud_origen",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="panel_cotizacion_generada",
                to="solicitudes.solicitud",
            ),
        ),
    ]
