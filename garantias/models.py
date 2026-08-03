from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage

from clientes.models import Cliente


garantias_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class Garantia(models.Model):
    class Estado(models.TextChoices):
        SOLICITUD_NAVIERA = "SOLICITUD_NAVIERA", "Solicitud a naviera"
        EN_PROCESO = "EN_PROCESO", "En proceso"
        PAGO_NAVIERA_ZAHA = "PAGO_NAVIERA_ZAHA", "Pago naviera a zaha"
        DEVOLUCION_CLIENTE = "DEVOLUCION_CLIENTE", "Devolución a cliente"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"
        URGENTE = "URGENTE", "Urgente"

    titulo = models.CharField(max_length=255, blank=True, default="")
    descripcion = models.TextField(blank=True, default="")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="garantias", null=True, blank=True)
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.SOLICITUD_NAVIERA,
    )
    prioridad = models.CharField(
        max_length=20,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
        blank=True,
    )
    asignados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="garantias_asignadas",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="garantias_creadas",
    )
    fecha_vencimiento = models.DateField(null=True, blank=True)
    fecha_creacion = models.DateTimeField(default=timezone.now)
    etiquetas = models.ManyToManyField(
        "GarantiaEtiqueta",
        blank=True,
        related_name="garantias",
    )

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def __str__(self):
        return self.titulo


class GarantiaEtiqueta(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#1D6F6F")
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["nombre", "id"]

    def __str__(self):
        return self.nombre


class GarantiaComentario(models.Model):
    garantia = models.ForeignKey(Garantia, on_delete=models.CASCADE, related_name="comentarios")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    comentario = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha", "id"]


class GarantiaArchivo(models.Model):
    garantia = models.ForeignKey(Garantia, on_delete=models.CASCADE, related_name="archivos")
    archivo = models.FileField(storage=garantias_upload_storage, upload_to="garantias/archivos/%Y/%m/")
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return self.archivo.name


class GarantiaEnlace(models.Model):
    garantia = models.ForeignKey(Garantia, on_delete=models.CASCADE, related_name="enlaces")
    titulo = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return self.titulo
