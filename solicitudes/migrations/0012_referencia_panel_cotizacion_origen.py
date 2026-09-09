from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("panel_cotizaciones", "0009_panelcotizacion_solicitud_origen"),
        ("solicitudes", "0011_cotizacion_eliminado_en_cotizacion_eliminado_por_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="referencia",
            name="panel_cotizacion_origen",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="referencia_generada",
                to="panel_cotizaciones.panelcotizacion",
            ),
        ),
    ]
