import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('garantias', '0012_garantia_referencia_origen'),
        ('operaciones', '0014_operacioncolumna_usuarios_visibles_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='garantia',
            name='operacion_origen',
            field=models.OneToOneField(blank=True, editable=False, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='garantia_generada', to='operaciones.operacion'),
        ),
    ]
