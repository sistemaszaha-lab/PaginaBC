from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage

from clientes.models import Cliente


operaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class Operacion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendientes"
        SEGUROS = "SEGUROS", "Seguros"
        PRUEBA_VALOR = "PRUEBA_VALOR", "Prueba de valor"
        EN_ADUANA = "EN_ADUANA", "En aduana"
        TRANSITO_NACIONAL = "TRANSITO_NACIONAL", "Tránsito nacional"
        COORDINAR_PICKUP = "COORDINAR_PICKUP", "Pick up"
        TRANSITO_INTERNACIONAL = "TRANSITO_INTERNACIONAL", "Tránsito internacional"
        EXPEDIENTE_CG = "EXPEDIENTE_CG", "Expediente CG"
        SOLICITUD_CUENTA_GASTOS = "SOLICITUD_CUENTA_GASTOS", "Solicitud de cuenta gastos"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    titulo = models.CharField(max_length=255, blank=True, default="")
    descripcion = models.TextField(blank=True, default="")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="operaciones", null=True, blank=True)
    estado = models.CharField(
        max_length=30,
        choices=Estado.choices,
        default=Estado.PENDIENTE,
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
        related_name="operaciones_asignadas",
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="operaciones_creadas",
    )
    fecha_vencimiento = models.DateField(null=True, blank=True)
    fecha_creacion = models.DateTimeField(default=timezone.now)
    etiquetas = models.ManyToManyField("OperacionEtiqueta", blank=True, related_name="operaciones")
    opciones = models.ManyToManyField("OperacionOpcion", blank=True, related_name="operaciones")
    referencia_origen = models.OneToOneField(
        "solicitudes.Referencia",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operacion_generada",
        editable=False,
    )

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def __str__(self):
        return self.titulo
    
    def get_prioridad_color(self):
        """Retorna el color Bootstrap para la prioridad."""
        colors = {
            self.Prioridad.BAJA: "success",
            self.Prioridad.MEDIA: "warning",
            self.Prioridad.ALTA: "danger",
        }
        return colors.get(self.prioridad, "secondary")



class OperacionEtiqueta(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    color = models.CharField(
        max_length=7,
        default="#3E9FA2",
        help_text="Color en formato hexadecimal (ej: #3E9FA2)"
    )
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class OperacionOpcion(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class OperacionComentario(models.Model):
    operacion = models.ForeignKey(Operacion, on_delete=models.CASCADE, related_name="comentarios")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    comentario = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha", "id"]


class OperacionArchivo(models.Model):
    operacion = models.ForeignKey(Operacion, on_delete=models.CASCADE, related_name="archivos")
    archivo = models.FileField(storage=operaciones_upload_storage, upload_to="operaciones/archivos/%Y/%m/")
    subido_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return self.archivo.name


class OperacionEnlace(models.Model):
    operacion = models.ForeignKey(Operacion, on_delete=models.CASCADE, related_name="enlaces")
    titulo = models.CharField(max_length=255)
    url = models.URLField(max_length=1000)
    creado_por = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha", "-id"]

    def __str__(self):
        return self.titulo
