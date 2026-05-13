from django.conf import settings
from django.db import models
from django.utils import timezone

from clientes.models import Cliente


class Garantia(models.Model):
    class Estado(models.TextChoices):
        CREADA = "CREADA", "Creada"
        PRESENTADA = "PRESENTADA", "Presentada"
        RESUELTA = "RESUELTA", "Resuelta"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    titulo = models.CharField(max_length=255)
    descripcion = models.TextField(blank=True, default="")
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="garantias")
    estado = models.CharField(
        max_length=20,
        choices=Estado.choices,
        default=Estado.CREADA,
    )
    prioridad = models.CharField(
        max_length=20,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
    )
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="garantias_creadas",
    )
    fecha_creacion = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def __str__(self):
        return self.titulo


class GarantiaComentario(models.Model):
    garantia = models.ForeignKey(Garantia, on_delete=models.CASCADE, related_name="comentarios")
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    comentario = models.TextField()
    fecha = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["fecha", "id"]

# Create your models here.
