from django.db import migrations, models


def inicializar_clientes(apps, schema_editor):
    Cliente = apps.get_model("clientes", "Cliente")
    Referencia = apps.get_model("solicitudes", "Referencia")
    Contador = apps.get_model("clientes", "ClienteConsecutivo")
    activos = Referencia.objects.filter(eliminado_en__isnull=True)
    clientes = list(Cliente.objects.order_by("nombre", "pk"))
    clientes_por_clave = {}
    for cliente in clientes:
        nombres = [cliente.nombre]
        if cliente.empresa:
            nombres.append(f"{cliente.nombre} ({cliente.empresa})")
        for nombre in nombres:
            clientes_por_clave.setdefault(nombre, []).append(cliente)

    claves_activas = set(
        activos.values_list("cliente", flat=True)
    )
    candidatos = set()
    for clave in claves_activas:
        involucrados = clientes_por_clave.get(clave, [])
        existentes = [
            cliente
            for cliente in involucrados
            if cliente.tipo_cliente == "existente"
        ]
        if len(existentes) == 1:
            candidatos.add(existentes[0].pk)
        elif len(existentes) >= 2:
            candidatos.update(cliente.pk for cliente in existentes)
        else:
            candidatos.update(cliente.pk for cliente in involucrados)

    candidatos = [
        cliente for cliente in clientes if cliente.pk in candidatos
    ]
    Cliente.objects.exclude(pk__in=[c.pk for c in candidatos]).update(
        tipo_cliente="nuevo", numero_cliente=None
    )
    for numero, cliente in enumerate(candidatos, start=1):
        Cliente.objects.filter(pk=cliente.pk).update(
            tipo_cliente="existente", numero_cliente=numero
        )
    Contador.objects.create(
        clave="clientes", ultimo_numero=len(candidatos)
    )


class Migration(migrations.Migration):
    dependencies = [
        ("clientes", "0007_cliente_gastos_cliente_ingresos"),
        ("solicitudes", "0013_movimientoreferencia"),
    ]
    operations = [
        migrations.AddField(
            model_name="cliente", name="numero_cliente",
            field=models.PositiveIntegerField(blank=True, null=True, unique=True),
        ),
        migrations.CreateModel(
            name="ClienteConsecutivo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("clave", models.CharField(default="clientes", max_length=30, unique=True)),
                ("ultimo_numero", models.PositiveIntegerField(default=0)),
            ],
        ),
        migrations.RunPython(inicializar_clientes, migrations.RunPython.noop),
    ]
