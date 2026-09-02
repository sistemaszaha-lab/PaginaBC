# Generated manually
from django.db import migrations

def copy_fecha_vencimiento_to_etd(apps, schema_editor):
    Operacion = apps.get_model('operaciones', 'Operacion')
    for operacion in Operacion.objects.filter(fecha_vencimiento__isnull=False):
        if operacion.etd is None:
            operacion.etd = operacion.fecha_vencimiento
            operacion.save(update_fields=['etd'])

def reverse_copy(apps, schema_editor):
    pass

class Migration(migrations.Migration):

    dependencies = [
        ('operaciones', '0008_alter_operacion_options_operacion_carga_lista_and_more'),
    ]

    operations = [
        migrations.RunPython(copy_fecha_vencimiento_to_etd, reverse_copy),
        migrations.RemoveField(
            model_name='operacion',
            name='carga_lista',
        ),
        migrations.RemoveField(
            model_name='operacion',
            name='fecha_vencimiento',
        ),
    ]
