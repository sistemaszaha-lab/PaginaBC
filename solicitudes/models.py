from django.db import models
from django.contrib.auth.models import User
from datetime import date



ESTADOS = (
    ("Pendiente", "Pendiente"),
    ("Cumplido", "Cumplido"),
    ("No cumplido", "No cumplido"),
    ("Fuera de plazo", "Fuera de plazo"),
)
#=====================
# Modelo solicitud
#=====================

class Solicitud(models.Model):

    anio = models.IntegerField()

    sg = models.CharField(max_length=20)

    cliente = models.CharField(max_length=255)

    fecha_recepcion = models.DateField(verbose_name="Fecha de inicio")

    fecha_entrega = models.DateField(null=True, blank=True)

    tipo = models.CharField(max_length=100)

    ejecutivo = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    # Transporte seleccionado
    aerea = models.BooleanField(default=False)
    maritima = models.BooleanField(default=False)
    terrestre = models.BooleanField(default=False)

    # Estados
    estado_aereo = models.CharField(max_length=50, blank=True, null=True)
    estado_maritimo = models.CharField(max_length=50, blank=True, null=True)
    estado_terrestre = models.CharField(max_length=50, blank=True, null=True)

    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.sg} - {self.cliente}"

    # ===============================
    # ESTADO ACTIVO
    # ===============================
    def estado_general(self):
        return (
            self.estado_aereo
            or self.estado_maritimo
            or self.estado_terrestre
        )

    # ===============================
    # DIAS RESTANTES (contador vivo)
    # ===============================
    
    @property
    def dias_restantes(self):
        if not self.fecha_entrega:
            return None

        hoy = date.today()

    #Si cualquier estado ya está finalizado → BLANCO
        if (
        self.estado_aereo in ["Cumplido", "Fuera de plazo"] or
        self    .estado_maritimo in ["Cumplido", "Fuera de plazo"] or
        self.estado_terrestre in ["Cumplido", "Fuera de plazo"]
    ):
            return None

        return (self.fecha_entrega - hoy).days

        return dias

    # ===============================
    # TIEMPO REAL DE ENTREGA
    # ===============================
    def tiempo_real(self):
        estado = self.estado_general()

        if estado in ["Cumplido", "Fuera de plazo"]:
            return (date.today() - self.fecha_recepcion).days

        return None

# ===============================
# MODELO COTIZACION
# ===============================
class Cotizacion(models.Model):

    anio = models.IntegerField(verbose_name="Año")

    consecutivo = models.CharField(
        max_length=20,
        verbose_name="Consecutivo"
    )

    cliente = models.CharField(
        max_length=255,
        verbose_name="Prospecto de cliente"
    )

    fecha_solicitud = models.DateField(
        verbose_name="Fecha de solicitud"
    )

    fecha_envio = models.DateField(
        null=True,
        blank=True,
        verbose_name="Fecha de envío"
    )

    tipo = models.CharField(
        max_length=150,
        verbose_name="Tipo"
    )

    ejecutivo = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    tiempo_entrega = models.CharField(
        max_length=100,
        blank=True
    )

    aerea = models.CharField(max_length=100, blank=True)
    maritima = models.CharField(max_length=100, blank=True)
    terrestre = models.CharField(max_length=100, blank=True)

    creado = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.consecutivo} - {self.cliente}"


#===================================
# MODELO REFERENCIAS
#===================================

class Referencia(models.Model):

    referencia = models.CharField(max_length=50, unique=True)
    ejecutivo = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    cliente = models.CharField(max_length=200, blank=True, null=True)
    servicio = models.CharField(max_length=200, blank=True, null=True)
    agencia_aduanal = models.CharField(max_length=200, blank=True, null=True)
    fecha = models.DateField(blank=True, null=True)

    SERVICIOS_LABELS = {
        "importacion": "Importacion",
        "exportacion": "Exportacion",
        "servicios_transporte": "Servicios y transporte",
        "servicios_consultoria": "Servicios de consultoria",
        "comercializador_importacion": "Comercializador de importacion",
        "comercializador_exportacion": "Comercializador de exportacion",
    }

    @property
    def servicio_legible(self):
        return self.SERVICIOS_LABELS.get(
            self.servicio,
            str(self.servicio).replace("_", " ").strip(),
        )

    def __str__(self):
        return self.referencia
