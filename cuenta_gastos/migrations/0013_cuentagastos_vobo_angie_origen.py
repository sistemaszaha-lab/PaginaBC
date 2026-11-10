import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("cuenta_gastos", "0012_cuentagastos_operacion_flete_origen"),
    ]

    operations = [
        migrations.AddField(
            model_name="cuentagastos",
            name="vobo_angie_origen",
            field=models.OneToOneField(
                blank=True,
                editable=False,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cuenta_gastos_solicitud_geo",
                to="cuenta_gastos.cuentagastos",
            ),
        ),
    ]
