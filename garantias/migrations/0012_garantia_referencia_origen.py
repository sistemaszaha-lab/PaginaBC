# Generated manually on 2026-09-18

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("garantias", "0011_garantia_fecha_pago"),
        ("solicitudes", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="garantia",
            name="referencia_origen",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="garantia_generada",
                to="solicitudes.referencia",
            ),
        ),
    ]
