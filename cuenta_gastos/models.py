from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage

from clientes.models import Cliente


operaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class CuentaGastos(models.Model):

    class Estado(models.TextChoices):

        SOLICITUD_PAGO = "SOLICITUD_PAGO", "Solicitud de pago"
        SOLICITUD_FACTURAS = "SOLICITUD_FACTURAS", "Solicitud de facturas"
        SOLICITUD_CUENTA_GASTOS = "SOLICITUD_CUENTA_GASTOS", "Solicitud de cuenta de gastos"
        FACTURA_ANTICIPO = "FACTURA_ANTICIPO", "Factura por Anticipo"
        FLETE_ESPERA_PAGO = "FLETE_ESPERA_PAGO", "Flete en espera de pago"
        EN_PROCESO = "EN_PROCESO", "En Proceso"
        VOBO_ANGIE = "VOBO_ANGIE", "VoBo Angie"
        APROBADAS = "APROBADAS", "Aprobadas"
        SOLICITADAS_GEO = "SOLICITADAS_GEO", "Solicitadas a Geo"
        POR_ENVIAR_CLIENTE = "POR_ENVIAR_CLIENTE", "Por enviar al cliente"
        DEVOLUCION = "DEVOLUCION", "Devolución"
        COBRANZA = "COBRANZA", "Cobranza"
        COMPLEMENTO_PAGO = "COMPLEMENTO_PAGO", "Complemento de pago"
        DEUDORES_MOROSOS = "DEUDORES_MOROSOS", "Deudores Morosos"
        COMERCIALIZADORAS = "COMERCIALIZADORAS", "Comercializadoras"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    titulo = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    descripcion = models.TextField(
        blank=True,
        default=""
    )

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cuentas_gastos"
    )

    estado = models.CharField(
        max_length=50,
        choices=Estado.choices,
        default=Estado.SOLICITUD_PAGO
    )

    prioridad = models.CharField(
        max_length=20,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
        blank=True
    )

    asignados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="cuentas_gastos_asignadas"
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cuentas_gastos_creadas"
    )

    fecha_vencimiento = models.DateField(
        null=True,
        blank=True
    )

    fecha_creacion = models.DateTimeField(
        default=timezone.now
    )

    etiquetas = models.ManyToManyField(
        "CuentaGastosEtiqueta",
        blank=True,
        related_name="cuentas_gastos"
    )

    opciones = models.ManyToManyField(
        "CuentaGastosOpcion",
        blank=True,
        related_name="cuentas_gastos"
    )

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def __str__(self):
        return self.titulo

    def get_prioridad_color(self):

        colors = {
            self.Prioridad.BAJA: "success",
            self.Prioridad.MEDIA: "warning",
            self.Prioridad.ALTA: "danger",
        }

        return colors.get(
            self.prioridad,
            "secondary"
        )


class CuentaGastosEtiqueta(models.Model):

    nombre = models.CharField(
        max_length=100,
        unique=True
    )

    color = models.CharField(
        max_length=7,
        default="#3E9FA2"
    )

    fecha_creacion = models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class CuentaGastosOpcion(models.Model):

    nombre=models.CharField(
        max_length=100,
        unique=True
    )

    fecha_creacion=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["nombre"]

    def __str__(self):
        return self.nombre


class CuentaGastosComentario(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="comentarios"
    )

    usuario=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    comentario=models.TextField()

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["fecha","id"]


class CuentaGastosArchivo(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="archivos"
    )

    archivo=models.FileField(
        storage=operaciones_upload_storage,
        upload_to="cuenta_gastos/archivos/%Y/%m/"
    )

    subido_por=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["-fecha","-id"]

    def __str__(self):
        return self.archivo.name


class CuentaGastosEnlace(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="enlaces"
    )

    titulo=models.CharField(
        max_length=255
    )

    url=models.URLField(
        max_length=1000
    )

    creado_por=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["-fecha","-id"]

    def __str__(self):
        return self.titulo