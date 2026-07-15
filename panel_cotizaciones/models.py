from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone
from clientes.models import normalizar_texto_cliente

panelcotizaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class PanelCotizacion(models.Model):
    class Estado(models.TextChoices):
        REQUERIMIENTO = "REQUERIMIENTO", "Requerimiento"
        EN_PROGRESO = "EN_PROGRESO", "En progreso"
        ENVIADA = "ENVIADA", "Enviada"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    titulo = models.CharField(max_length=255, blank=True)
    descripcion = models.TextField(blank=True)
    cliente = models.CharField(max_length=255, blank=True)
    prioridad = models.CharField(
        max_length=10, choices=Prioridad.choices, default=Prioridad.MEDIA, blank=True
    )
    estado = models.CharField(
        max_length=20, choices=Estado.choices, default=Estado.REQUERIMIENTO
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_vencimiento = models.DateField(null=True, blank=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="panel_cotizaciones_creadas",
    )
    asignados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="panel_cotizaciones_asignadas",
    )

    class Meta:
        ordering = ["-fecha_creacion"]

    def save(self, *args, **kwargs):
        self.cliente = normalizar_texto_cliente(self.cliente)
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.titulo} ({self.cliente})"


class PanelCotizacionArchivo(models.Model):
    cotizacion = models.ForeignKey(
        PanelCotizacion,
        on_delete=models.CASCADE,
        related_name="archivos",
    )
    archivo = models.FileField(
        storage=panelcotizaciones_upload_storage,
        upload_to="panel_cotizaciones/archivos/%Y/%m/",
    )
    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="panel_cotizacion_archivos_subidos",
    )
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self) -> str:
        return self.archivo.name

    @property
    def nombre_archivo(self) -> str:
        return self.archivo.name.rsplit("/", 1)[-1]


class PanelCotizacionEnlace(models.Model):
    cotizacion = models.ForeignKey(
        PanelCotizacion,
        on_delete=models.CASCADE,
        related_name="enlaces",
    )
    titulo = models.CharField(max_length=255, blank=True, default="")
    url = models.URLField(max_length=1000, blank=True, default="")
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="panel_cotizacion_enlaces_creados",
    )
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self) -> str:
        return self.titulo or self.url


class PanelCotizacionComentario(models.Model):
    cotizacion = models.ForeignKey(
        PanelCotizacion, on_delete=models.CASCADE, related_name="comentarios"
    )
    texto = models.TextField()
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="panel_cotizacion_comentarios",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha_creacion"]

    def __str__(self) -> str:
        return f"Comentario #{self.pk} - {self.cotizacion_id}"
