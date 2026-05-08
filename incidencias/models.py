from django.conf import settings
from django.db import models


class Incidencia(models.Model):
    class Estado(models.TextChoices):
        ABIERTO = "abierto", "Abierto"
        PROCESO = "proceso", "En proceso"
        CERRADO = "cerrado", "Cerrado"

    class Prioridad(models.TextChoices):
        ALTA = "alta", "Alta"
        MEDIA = "media", "Media"
        BAJA = "baja", "Baja"

    codigo = models.CharField(max_length=32, unique=True)
    titulo = models.CharField(max_length=200)
    descripcion = models.TextField(blank=True)
    responsable = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="incidencias_responsables",
    )
    estado = models.CharField(max_length=16, choices=Estado.choices, default=Estado.ABIERTO)
    prioridad = models.CharField(
        max_length=16, choices=Prioridad.choices, default=Prioridad.MEDIA
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_limite = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["-fecha_creacion"]
        verbose_name = "Incidencia"
        verbose_name_plural = "Incidencias"
        indexes = [
            models.Index(fields=["estado"]),
            models.Index(fields=["prioridad"]),
            models.Index(fields=["responsable"]),
            models.Index(fields=["fecha_creacion"]),
        ]

    def __str__(self) -> str:
        return f"{self.codigo} - {self.titulo}"
