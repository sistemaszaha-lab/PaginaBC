from django.db import models
from django.utils import timezone


class Cliente(models.Model):
    ESTADO_ACTIVO = "activo"
    ESTADO_INACTIVO = "inactivo"
    ESTADO_CHOICES = [
        (ESTADO_ACTIVO, "Activo"),
        (ESTADO_INACTIVO, "Inactivo"),
    ]

    nombre = models.CharField(max_length=150)
    empresa = models.CharField(max_length=150, blank=True)
    representante_legal = models.CharField(max_length=150, blank=True, default="")
    contacto = models.CharField(max_length=150, blank=True, default="")
    telefono = models.CharField(max_length=20)
    celular = models.CharField(max_length=20, blank=True, default="")
    correo = models.CharField(max_length=255, blank=True, default="")
    direccion = models.CharField(max_length=255, blank=True)
    rfc = models.CharField(max_length=20, blank=True)
    estado = models.CharField(
        max_length=10,
        choices=ESTADO_CHOICES,
        default=ESTADO_ACTIVO,
    )
    fecha_alta = models.DateField(default=timezone.now)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_alta", "nombre"]

    def __str__(self):
        return f"{self.nombre} ({self.empresa})" if self.empresa else self.nombre
