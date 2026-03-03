from datetime import date

from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Cotizacion, Referencia, Solicitud


class SolicitudForm(forms.ModelForm):
    TIPOS_SOLICITUD = (
        ("Importación aérea", "Importación aérea"),
        ("Importación maritima", "Importación maritima"),
        ("Exportación aérea", "Exportación aérea"),
        ("Exportación maritima", "Exportación maritima"),
        ("Transporte Internacional", "Transporte Internacional"),
        ("Exportación Terrestre", "Exportación Terrestre"),
        ("Importación Terrestre", "Importación Terrestre"),
        ("Transporte nacional", "Transporte nacional"),
        ("Consultoría", "Consultoría"),
    )

    tipo = forms.ChoiceField(
        choices=TIPOS_SOLICITUD,
        label="Tipo",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Solicitud
        exclude = ["estado_aereo", "estado_maritimo", "estado_terrestre", "creado"]
        labels = {
            "anio": "Año",
            "fecha_recepcion": "Fecha de inicio",
        }
        widgets = {
            "sg": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "anio": forms.NumberInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "fecha_recepcion": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "fecha_entrega": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sg"].required = False
        self.fields["sg"].disabled = True
        if self.instance.pk and self.instance.tipo and self.instance.tipo not in dict(self.TIPOS_SOLICITUD):
            self.fields["tipo"].choices = [(self.instance.tipo, self.instance.tipo)] + list(
                self.TIPOS_SOLICITUD
            )
        if not self.instance.pk:
            self.fields["anio"].initial = date.today().year
            self.fields["sg"].initial = self._generar_sg(self.fields["anio"].initial)

    def save(self, commit=True):
        solicitud = super().save(commit=False)
        if not solicitud.pk:
            solicitud.sg = self._generar_sg(solicitud.anio)
        else:
            solicitud.sg = self.instance.sg
        if commit:
            solicitud.save()
        return solicitud

    def _generar_sg(self, anio):
        prefijo = f"SG{str(anio)[-2:]}"
        consecutivos = Solicitud.objects.filter(sg__startswith=prefijo).values_list("sg", flat=True)
        ultimo = 0
        for sg in consecutivos:
            sufijo = sg[len(prefijo):]
            if sufijo.isdigit():
                ultimo = max(ultimo, int(sufijo))
        return f"{prefijo}{ultimo + 1:03d}"


class CrearUsuarioForm(UserCreationForm):
    first_name = forms.CharField(label="Nombre")
    email = forms.EmailField(label="Correo electrónico")

    ROLES = (
        ("admin", "Administrador"),
        ("usuario", "Ejecutivo"),
    )

    rol = forms.ChoiceField(
        choices=ROLES,
        label="Rol",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "email", "password1", "password2", "rol")


class EditarUsuarioForm(forms.ModelForm):
    ROLES = (
        ("admin", "Administrador"),
        ("usuario", "Ejecutivo"),
    )

    rol = forms.ChoiceField(
        choices=ROLES,
        label="Rol",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    password1 = forms.CharField(
        required=False,
        label="Nueva contraseña",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )
    password2 = forms.CharField(
        required=False,
        label="Confirmar nueva contraseña",
        widget=forms.PasswordInput(attrs={"class": "form-control"}),
    )

    class Meta:
        model = User
        fields = ("username", "first_name", "email", "rol")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["rol"].initial = "admin" if self.instance.is_superuser else "usuario"

    def clean(self):
        cleaned_data = super().clean()
        password1 = cleaned_data.get("password1")
        password2 = cleaned_data.get("password2")

        if password1 or password2:
            if password1 != password2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            elif len(password1) < 8:
                self.add_error("password1", "La contraseña debe tener al menos 8 caracteres.")
        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        rol = self.cleaned_data["rol"]
        user.is_superuser = rol == "admin"
        user.is_staff = rol == "admin"

        password1 = self.cleaned_data.get("password1")
        if password1:
            user.set_password(password1)

        if commit:
            user.save()
        return user


class CotizacionForm(forms.ModelForm):
    TIPOS_COTIZACION = (
        ("Importación aérea", "Importación aérea"),
        ("Importación maritima", "Importación maritima"),
        ("Exportación aérea", "Exportación aérea"),
        ("Exportación maritima", "Exportación maritima"),
        ("Transporte Internacional", "Transporte Internacional"),
        ("Importación Terrestre", "Importación Terrestre"),
        ("Exportación Terrestre", "Exportación Terrestre"),
        ("Transporte nacional", "Transporte nacional"),
        ("Consultoría", "Consultoría"),
    )

    tipo = forms.ChoiceField(
        choices=TIPOS_COTIZACION,
        label="Tipo",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Cotizacion
        fields = "__all__"
        labels = {
            "anio": "Año",
            "consecutivo": "Prospecto de cotización",
        }
        widgets = {
            "anio": forms.NumberInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "consecutivo": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "fecha_solicitud": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "fecha_envio": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["consecutivo"].required = False
        if not self.instance.pk:
            anio_actual = date.today().year
            self.fields["anio"].initial = anio_actual
            self.fields["consecutivo"].initial = self._generar_consecutivo(anio_actual)

    def save(self, commit=True):
        cotizacion = super().save(commit=False)
        if not cotizacion.pk:
            cotizacion.consecutivo = self._generar_consecutivo(cotizacion.anio)
        if commit:
            cotizacion.save()
        return cotizacion

    def _generar_consecutivo(self, anio):
        prefijo = f"C{str(anio)[-2:]}"
        consecutivos = Cotizacion.objects.filter(consecutivo__startswith=prefijo).values_list(
            "consecutivo",
            flat=True,
        )
        ultimo = 0
        for consecutivo in consecutivos:
            sufijo = consecutivo[len(prefijo):]
            if sufijo.isdigit():
                ultimo = max(ultimo, int(sufijo))
        return f"{prefijo}{ultimo + 1:03d}"


class ReferenciaForm(forms.ModelForm):
    OPERACIONES = (
        ("importacion", "Importación"),
        ("exportacion", "Exportación"),
        ("servicios_transporte", "Servicios de transporte"),
        ("servicios_consultoria", "Servicios de consultoría"),
        ("comercializador_importacion", "Comercializadora de importación"),
        ("comercializador_exportacion", "Comercializadora de exportación"),
    )
    CODIGOS_OPERACION = {
        "importacion": "1",
        "importación": "1",
        "exportacion": "2",
        "exportación": "2",
        "servicios_transporte": "3",
        "servicios_consultoria": "4",
        "comercializador_importacion": "5",
        "comercializador_exportacion": "6",
        "comercializadora_importacion": "5",
        "comercializadora_exportacion": "6",
    }
    PREFIJO_EMPRESA = "BC"

    servicio = forms.ChoiceField(
        choices=OPERACIONES,
        label="Tipo de operación",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    class Meta:
        model = Referencia
        fields = ["ejecutivo", "cliente", "servicio", "agencia_aduanal", "fecha"]
        widgets = {
            "fecha": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            self.fields["fecha"].initial = date.today()
        elif self.instance.servicio and self.instance.servicio not in self.CODIGOS_OPERACION:
            self.fields["servicio"].choices = (
                [(self.instance.servicio, self.instance.servicio)]
                + list(self.OPERACIONES)
            )

    def save(self, commit=True):
        referencia = super().save(commit=False)
        debe_regenerar = (not referencia.pk) or any(
            campo in self.changed_data for campo in ("servicio", "fecha")
        )
        if debe_regenerar and referencia.servicio in self.CODIGOS_OPERACION:
            referencia.referencia = self._generar_referencia(
                fecha=referencia.fecha,
                operacion=referencia.servicio,
                excluir_pk=referencia.pk,
            )
        if commit:
            referencia.save()
        return referencia

    def _generar_referencia(self, fecha, operacion, excluir_pk=None):
        codigo_operacion = self.CODIGOS_OPERACION[operacion]
        anio_corto = fecha.strftime("%y")
        prefijo = f"{self.PREFIJO_EMPRESA}{anio_corto}{codigo_operacion}"
        consecutivo = self._siguiente_consecutivo(prefijo, excluir_pk=excluir_pk)
        return f"{prefijo}{consecutivo:03d}"

    def _siguiente_consecutivo(self, prefijo, excluir_pk=None):
        referencias_existentes = Referencia.objects.filter(
            referencia__startswith=prefijo
        )
        if excluir_pk:
            referencias_existentes = referencias_existentes.exclude(pk=excluir_pk)
        referencias_existentes = referencias_existentes.values_list("referencia", flat=True)
        ultimo = 0
        for referencia in referencias_existentes:
            sufijo = referencia[len(prefijo):]
            if sufijo.isdigit():
                ultimo = max(ultimo, int(sufijo))
        return ultimo + 1
