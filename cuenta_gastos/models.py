from django.conf import settings
from django.db import models
from django.utils import timezone
from django.core.files.storage import FileSystemStorage
from uuid import uuid4

from clientes.models import Cliente


operaciones_upload_storage = FileSystemStorage(
    location="uploads",
    base_url="/uploads/",
)


def documento_repositorio_upload_to(_instance, _filename):
    now = timezone.now()
    return (
        f"cuenta_gastos/repositorio/{now:%Y/%m}/"
        f"{uuid4().hex}.pdf"
    )


class CuentaGastosColumna(models.Model):
    nombre = models.CharField(max_length=120)
    codigo = models.CharField(max_length=60, unique=True)
    orden = models.PositiveIntegerField(default=0)
    activa = models.BooleanField(default=True)
    color_fondo = models.CharField(max_length=7, default="#F8F9FA", verbose_name="Color de fondo")
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="cuenta_gastos_columnas_creadas",
    )
    fecha_creacion = models.DateTimeField(auto_now_add=True)
    fecha_actualizacion = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["orden", "id"]
        verbose_name = "Columna de cuenta de gastos"
        verbose_name_plural = "Columnas de cuenta de gastos"

    def __str__(self):
        return self.nombre


class CuentaGastos(models.Model):

    class Estado(models.TextChoices):

        SOLICITUD_PAGO = "SOLICITUD_PAGO", "Solicitud de pago"
        SOLICITUD_FACTURAS = "SOLICITUD_FACTURAS", "Solicitud de facturas"
        SOLICITUD_CUENTA_GASTOS = "SOLICITUD_CUENTA_GASTOS", "Solicitud de cuenta de agencia aduanal"
        FACTURA_ANTICIPO = "FACTURA_ANTICIPO", "Factura por Anticipo"
        FLETE_ESPERA_PAGO = "FLETE_ESPERA_PAGO", "Flete en espera de pago"
        EN_PROCESO = "EN_PROCESO", "En Proceso"
        VOBO_ANGIE = "VOBO_ANGIE", "VoBo Angie"
        APROBADAS = "APROBADAS", "Aprobadas"
        SOLICITADAS_GEO = "SOLICITADAS_GEO", "Solicitadas a Geo"
        POR_ENVIAR_CLIENTE = "POR_ENVIAR_CLIENTE", "Por enviar al cliente"
        DEVOLUCION = "DEVOLUCION", "Devolución"
        COBRANZA = "COBRANZA", "Cobranza"
        COMPLEMENTO_PAGO = "COMPLEMENTO_PAGO", "Complemento de pago"
        DEUDORES_MOROSOS = "DEUDORES_MOROSOS", "Deudores Morosos"
        COMERCIALIZADORAS = "COMERCIALIZADORAS", "Comercializadoras"

    class Prioridad(models.TextChoices):
        BAJA = "BAJA", "Baja"
        MEDIA = "MEDIA", "Media"
        ALTA = "ALTA", "Alta"

    titulo = models.CharField(
        max_length=255,
        blank=True,
        default=""
    )

    descripcion = models.TextField(
        blank=True,
        default=""
    )

    cliente = models.ForeignKey(
        Cliente,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cuentas_gastos"
    )

    estado = models.CharField(
        max_length=50,
        choices=Estado.choices,
        default=Estado.SOLICITUD_PAGO
    )
    columna = models.ForeignKey(
        "CuentaGastosColumna",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="cuentas_gastos",
    )

    prioridad = models.CharField(
        max_length=20,
        choices=Prioridad.choices,
        default=Prioridad.MEDIA,
        blank=True
    )

    asignados = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        related_name="cuentas_gastos_asignadas"
    )

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="cuentas_gastos_creadas"
    )

    fecha_vencimiento = models.DateField(
        null=True,
        blank=True
    )

    fecha_creacion = models.DateTimeField(
        default=timezone.now
    )

    etiquetas = models.ManyToManyField(
        "CuentaGastosEtiqueta",
        blank=True,
        related_name="cuentas_gastos"
    )

    opciones = models.ManyToManyField(
        "CuentaGastosOpcion",
        blank=True,
        related_name="cuentas_gastos"
    )
    operacion_origen = models.OneToOneField(
        "operaciones.Operacion", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="cuenta_gastos_generada",
        editable=False,
    )
    eliminado_en = models.DateTimeField(null=True, blank=True, db_index=True)
    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="cuenta_gastos_cuentagastos_eliminadas",
    )

    class Meta:
        ordering = ["-fecha_creacion", "-id"]

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            update_fields = set(update_fields)
        if self.columna_id:
            columna = getattr(self, "columna", None)
            if columna is None or getattr(columna, "pk", None) != self.columna_id:
                columna = CuentaGastosColumna.objects.filter(
                    pk=self.columna_id
                ).only("id", "codigo").first()
                self.columna = columna
            if columna is not None and self.estado != columna.codigo:
                self.estado = columna.codigo
                if update_fields is not None:
                    update_fields.add("estado")
        elif self.estado:
            columna = CuentaGastosColumna.objects.filter(
                codigo=self.estado
            ).only("id").first()
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

        colors = {
            self.Prioridad.BAJA: "success",
            self.Prioridad.MEDIA: "warning",
            self.Prioridad.ALTA: "danger",
        }

        return colors.get(
            self.prioridad,
            "secondary"
        )


class CuentaGastosEtiqueta(models.Model):

    nombre = models.CharField(
        max_length=100,
        unique=True
    )

    color = models.CharField(
        max_length=7,
        default="#3E9FA2"
    )

    fecha_creacion = models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class CuentaGastosOpcion(models.Model):

    nombre=models.CharField(
        max_length=100,
        unique=True
    )

    fecha_creacion=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["nombre"]

    def __str__(self):
        return self.nombre


class CuentaGastosComentario(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="comentarios"
    )

    usuario=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    comentario=models.TextField()

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["fecha","id"]


class CuentaGastosArchivo(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="archivos"
    )

    archivo=models.FileField(
        storage=operaciones_upload_storage,
        upload_to="cuenta_gastos/archivos/%Y/%m/"
    )

    subido_por=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["-fecha","-id"]

    def __str__(self):
        return self.archivo.name


class CuentaGastosEnlace(models.Model):

    cuenta_gasto=models.ForeignKey(
        CuentaGastos,
        on_delete=models.CASCADE,
        related_name="enlaces"
    )

    titulo=models.CharField(
        max_length=255
    )

    url=models.URLField(
        max_length=1000
    )

    creado_por=models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT
    )

    fecha=models.DateTimeField(
        default=timezone.now
    )

    class Meta:
        ordering=["-fecha","-id"]



class DocumentoRepositorio(models.Model):

    archivo = models.FileField(
        storage=operaciones_upload_storage,
        upload_to=documento_repositorio_upload_to,
    )

    nombre_original = models.CharField(
        max_length=255
    )

    subido_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="documentos_repositorio_cuenta_gastos",
    )

    fecha_subida = models.DateTimeField(
        auto_now_add=True
    )

    eliminado_en = models.DateTimeField(
        null=True,
        blank=True,
        db_index=True,
    )

    eliminado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="documentos_repositorio_cuenta_gastos_eliminados",
    )

    class Meta:
        ordering = ["-fecha_subida", "-id"]

    def __str__(self):
        return self.nombre_original

    @property
    def esta_eliminado(self):
        return self.eliminado_en is not None

    @property
    def tamano_seguro(self):
        if not self.archivo:
            return 0
        try:
            return self.archivo.size
        except (FileNotFoundError, OSError, ValueError):
            return 0
