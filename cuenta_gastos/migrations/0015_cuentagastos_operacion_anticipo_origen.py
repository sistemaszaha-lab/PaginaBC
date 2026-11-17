from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("cuenta_gastos", "0014_columnas_automatizaciones")]

    operations = [
        migrations.AddField(
            model_name="cuentagastos",
            name="operacion_anticipo_origen",
            field=models.OneToOneField(
                blank=True, editable=False, null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="cuenta_gastos_anticipo",
                to="operaciones.operacion",
            ),
        ),
        migrations.AddField(
            model_name="cuentagastos",
            name="referencia_anticipo_codigo",
            field=models.CharField(blank=True, default="", db_default="", editable=False, max_length=50),
        ),
    ]
