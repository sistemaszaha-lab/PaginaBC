from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage

from clientes.models import Cliente


operaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


class OperacionColumna(models.Model):
    nombre = models.CharField(max_length=120)
    codigo = models.CharField(max_length=60, unique=True)
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="operaciones_columnas_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Columna de operaciones"
        verbose_name_plural = "Columnas de operaciones"

    def __str__(self):
        return self.nombre


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
    columna = models.ForeignKey(
        "OperacionColumna",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="operaciones",
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
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True)
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="operaciones_operacion_eliminadas",
    )

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
        if self.columna_id:
            if self.estado != self.columna.codigo:
                columna = (
                    OperacionColumna.objects.filter(codigo=self.estado)
                    .only("id")
                    .first()
                )
                if columna is not None:
                    self.columna_id = columna.pk
                    if update_fields is not None:
                        update_fields.add("columna")
                else:
                    self.estado = self.columna.codigo
                    if update_fields is not None:
                        update_fields.add("estado")
        elif self.estado:
            columna = (
                OperacionColumna.objects.filter(codigo=self.estado)
                .only("id")
                .first()
            )
            if columna is not None:
                self.columna_id = columna.pk
                if update_fields is not None:
                    update_fields.add("columna")
        if update_fields is not None:
            kwargs["update_fields"] = list(update_fields)
        return super().save(*args, **kwargs)

    def __str__(self):
        return self.titulo

    @property
    def esta_eliminada(self):
        return self.eliminado_en is not None
    
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
