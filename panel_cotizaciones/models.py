from django.conf import settings
from django.core.files.storage import FileSystemStorage
from django.db import models
from django.utils import timezone
from clientes.models import normalizar_texto_cliente

panelcotizaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class PanelCotizacionColumna(models.Model):
    nombre = models.CharField(max_length=120)
    codigo = models.CharField(max_length=60, unique=True)
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="panel_cotizaciones_columnas_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Columna de panel de cotizaciones"
        verbose_name_plural = "Columnas de panel de cotizaciones"

    def __str__(self) -> str:
        return self.nombre


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
    columna = models.ForeignKey(
        "PanelCotizacionColumna",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cotizaciones",
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
    etiquetas = models.ManyToManyField(
        "PanelCotizacionEtiqueta",
        blank=True,
        related_name="cotizaciones",
    )
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True)
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="panel_cotizaciones_panelcotizacion_eliminadas",
    )

    class Meta:
        ordering = ["-fecha_creacion"]

    def save(self, *args, **kwargs):
        self.cliente = normalizar_texto_cliente(self.cliente)
        if self.columna_id:
            if self.estado != self.columna.codigo:
                self.estado = self.columna.codigo
        elif self.estado:
            columna = (
                PanelCotizacionColumna.objects.filter(codigo=self.estado)
                .only("id")
                .first()
            )
            if columna is not None:
                self.columna_id = columna.pk
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return f"{self.titulo} ({self.cliente})"

    @property
    def esta_eliminada(self) -> bool:
        return self.eliminado_en is not None

    @property
    def columna_codigo(self) -> str:
        if self.columna_id:
            return self.columna.codigo
        return self.estado

    @property
    def columna_nombre(self) -> str:
        if self.columna_id:
            return self.columna.nombre
        try:
            return self.get_estado_display()
        except Exception:
            return self.estado


class PanelCotizacionEtiqueta(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    color = models.CharField(max_length=7, default="#3E9FA2")

    class Meta:
        ordering = ["nombre", "id"]

    def __str__(self) -> str:
        return self.nombre


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
