from django.db import migrations


COLUMNAS_INICIALES = (
    ("SOLICITUD_PAGO", "Solicitud de pago"),
    ("SOLICITUD_FACTURAS", "Solicitud de facturas"),
    ("SOLICITUD_CUENTA_GASTOS", "Solicitud de cuenta de agencia aduanal"),
    ("FACTURA_ANTICIPO", "Factura por Anticipo"),
    ("FLETE_ESPERA_PAGO", "Flete en espera de pago"),
    ("EN_PROCESO", "En Proceso"),
    ("VOBO_ANGIE", "VoBo Angie"),
    ("APROBADAS", "Aprobadas"),
    ("SOLICITADAS_GEO", "Solicitadas a Geo"),
    ("POR_ENVIAR_CLIENTE", "Por enviar al cliente"),
    ("DEVOLUCION", "Devolución"),
    ("COBRANZA", "Cobranza"),
    ("COMPLEMENTO_PAGO", "Complemento de pago"),
    ("DEUDORES_MOROSOS", "Deudores Morosos"),
    ("COMERCIALIZADORAS", "Comercializadoras"),
)


def crear_columnas_y_sincronizar(apps, schema_editor):
    CuentaGastos = apps.get_model("cuenta_gastos", "CuentaGastos")
    CuentaGastosColumna = apps.get_model("cuenta_gastos", "CuentaGastosColumna")

    columnas = {}
    for orden, (codigo, nombre) in enumerate(COLUMNAS_INICIALES, start=1):
        columna, _created = CuentaGastosColumna.objects.update_or_create(
            codigo=codigo,
            defaults={
                "nombre": nombre,
                "orden": orden,
                "activa": True,
            },
        )
        columnas[codigo] = columna.pk

    for codigo, columna_id in columnas.items():
        CuentaGastos.objects.filter(estado=codigo, columna__isnull=True).update(
            columna_id=columna_id
        )


def revertir_columnas_iniciales(apps, schema_editor):
    CuentaGastosColumna = apps.get_model("cuenta_gastos", "CuentaGastosColumna")
    CuentaGastosColumna.objects.filter(
        codigo__in=[codigo for codigo, _nombre in COLUMNAS_INICIALES]
    ).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("cuenta_gastos", "0005_cuentagastoscolumna_cuentagastos_columna"),
    ]

    operations = [
        migrations.RunPython(
            crear_columnas_y_sincronizar,
            revertir_columnas_iniciales,
        ),
    ]
