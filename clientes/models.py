from django.core.validators import MinValueValidator
from django.db import models
from django.utils import timezone


def normalizar_texto_cliente(valor):
    texto = str(valor or "").strip()
    return " ".join(texto.split()).upper()


CLIENTE_DUPLICADO_CONSTRAINT = "cliente_nombre_empresa_unicos"


def es_integrity_error_duplicado_cliente(exc):
    cause = getattr(exc, "__cause__", None)
    diag = getattr(cause, "diag", None)
    if getattr(diag, "constraint_name", None) == CLIENTE_DUPLICADO_CONSTRAINT:
        return True

    mensajes = [str(exc)]
    if cause is not None:
        mensajes.append(str(cause))
    texto = " ".join(mensajes)
    return (
        CLIENTE_DUPLICADO_CONSTRAINT in texto
        or "UNIQUE constraint failed: clientes_cliente.nombre, clientes_cliente.empresa" in texto
    )


class Cliente(models.Model):
    TIPO_NUEVO = "nuevo"
    TIPO_EXISTENTE = "existente"
    TIPO_CHOICES = [
        (TIPO_NUEVO, "Nuevo"),
        (TIPO_EXISTENTE, "Existente"),
    ]

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
    telefono = models.CharField(max_length=20, blank=True, default="")
    celular = models.CharField(max_length=20, blank=True, default="")
    correo = models.CharField(max_length=255, blank=True, default="")
    cuentas_por_cobrar = models.CharField(max_length=255, blank=True, default="")
    ingresos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    gastos = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        validators=[MinValueValidator(0)],
    )
    direccion = models.CharField(max_length=255, blank=True)
    rfc = models.CharField(max_length=20, blank=True)
    tipo_cliente = models.CharField(
        max_length=20,
        choices=TIPO_CHOICES,
        default=TIPO_NUEVO,
    )
    numero_cliente = models.PositiveIntegerField(null=True, blank=True, unique=True)
    estado = models.CharField(
        max_length=10,
        choices=ESTADO_CHOICES,
        default=ESTADO_ACTIVO,
    )
    fecha_alta = models.DateField(default=timezone.now)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha_alta", "nombre"]
        constraints = [
            models.UniqueConstraint(
                fields=["nombre", "empresa"],
                name=CLIENTE_DUPLICADO_CONSTRAINT,
            )
        ]

    def save(self, *args, **kwargs):
        self.nombre = normalizar_texto_cliente(self.nombre)
        self.empresa = normalizar_texto_cliente(self.empresa)
        super().save(*args, **kwargs)

    @property
    def utilidad(self):
        from solicitudes.models import MovimientoReferencia
        from django.db.models import Sum, Case, When, F, DecimalField
        total = MovimientoReferencia.objects.filter(
            referencia__cliente=self.nombre,
            referencia__eliminado_en__isnull=True,
        ).aggregate(total=Sum(Case(
            When(tipo=MovimientoReferencia.INGRESO, then=F("monto")),
            When(tipo=MovimientoReferencia.GASTO, then=-F("monto")),
            output_field=DecimalField(max_digits=14, decimal_places=2),
        )))['total']
        return total or 0

    def __str__(self):
        return f"{self.nombre} ({self.empresa})" if self.empresa else self.nombre

    @property
    def numero_cliente_formateado(self):
        return f"CL-{self.numero_cliente:03d}" if self.numero_cliente else ""


class ClienteConsecutivo(models.Model):
    clave = models.CharField(max_length=30, unique=True, default="clientes")
    ultimo_numero = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = "Consecutivo de clientes"
