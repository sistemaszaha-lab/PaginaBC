from django.db import migrations, models
INICIALES = ["DEL BRAVO", "GADI", "ZARAGOZA", "HANO", "ESCALANTE", "RIOJA", "ESTRATEGIA"]
def crear_catalogo(apps, schema_editor):
    Agencia = apps.get_model("cuenta_gastos", "AgenciaAduanal")
    for nombre in INICIALES:
        Agencia.objects.get_or_create(clave_normalizada=nombre.casefold(), defaults={"nombre": nombre})
class Migration(migrations.Migration):
    dependencies = [("cuenta_gastos", "0010_cuentagastos_agencia_aduanal_and_more")]
    operations = [migrations.CreateModel(name="AgenciaAduanal", fields=[("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")), ("nombre", models.CharField(max_length=255)), ("clave_normalizada", models.CharField(editable=False, max_length=255, unique=True))], options={"ordering": ["nombre", "id"]}), migrations.RunPython(crear_catalogo, migrations.RunPython.noop)]
