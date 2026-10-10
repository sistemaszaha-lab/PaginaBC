from django.db import migrations

def crear_grupo_solo_lectura(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    Group.objects.get_or_create(name="SOLO_LECTURA")

class Migration(migrations.Migration):
    dependencies = [("solicitudes", "0013_movimientoreferencia")]
    operations = [migrations.RunPython(crear_grupo_solo_lectura, migrations.RunPython.noop)]
