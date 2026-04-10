from datetime import date
import re
import uuid
from django import forms
from django.db import IntegrityError, transaction
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist
from .models import Cotizacion, Referencia, Solicitud, UserProfile

CLIENTE_NUEVO_LABEL = "Registrar cliente nuevo"


def _validar_cliente(valor):
    if (valor or "").strip().lower() == CLIENTE_NUEVO_LABEL.lower():
        raise forms.ValidationError("Selecciona un cliente valido o registra uno nuevo.")
    return valor


def _primer_nombre_display(user):
    if not user:
        return ""
    first_name = (getattr(user, "first_name", "") or "").strip()
    if first_name:
        return first_name.split()[0]
    return (getattr(user, "username", "") or "").strip()


def _label_ejecutivo(user):
    return _primer_nombre_display(user)


def _configurar_ejecutivo_field(field):
    if not field:
        return
    field.queryset = User.objects.all().order_by("first_name", "username")
    if hasattr(field, "label_from_instance"):
        field.label_from_instance = _label_ejecutivo
    if getattr(field, "widget", None):
        field.widget.attrs.setdefault("class", "form-select")


class SolicitudForm(forms.ModelForm):
    idempotency_key = forms.UUIDField(required=False, widget=forms.HiddenInput)

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
        exclude = ["estado_aereo", "estado_maritimo", "estado_terrestre", "fecha_cumplido", "creado"]
        labels = {
            "anio": "Año",
            "fecha_recepcion": "Fecha de inicio",
        }
        widgets = {
            "sg": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "anio": forms.NumberInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "fecha_recepcion": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "fecha_entrega": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "cliente": forms.TextInput(
                attrs={"class": "form-control", "list": "clientes_datalist", "autocomplete": "off"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["sg"].required = False
        self.fields["sg"].disabled = True
        _configurar_ejecutivo_field(self.fields.get("ejecutivo"))
        if self.instance.pk and self.instance.tipo and self.instance.tipo not in dict(self.TIPOS_SOLICITUD):
            self.fields["tipo"].choices = [(self.instance.tipo, self.instance.tipo)] + list(
                self.TIPOS_SOLICITUD
            )
        if not self.instance.pk:
            self.fields["anio"].initial = date.today().year
            self.fields["sg"].initial = self._generar_sg(self.fields["anio"].initial)
            self.fields["idempotency_key"].initial = uuid.uuid4()

    def save(self, commit=True):
        solicitud = super().save(commit=False)
        if not solicitud.pk:
            solicitud.sg = self._generar_sg(solicitud.anio)
        else:
            solicitud.sg = self.instance.sg
        if commit:
            solicitud.save()
        return solicitud

    def clean_cliente(self):
        return _validar_cliente(self.cleaned_data.get("cliente"))

    def _generar_sg(self, anio):
        """
        Genera SG con formato: SG + 2 dígitos año + 3 dígitos consecutivo
        Ej: SG26001, SG26002, SG26003...
        Solo cuenta registros con formato válido: SG{YY}{###}
        Ignora datos históricos con formatos diferentes (ej: SG26-001)
        """
        prefijo = f"SG{str(anio)[-2:]}"
        consecutivos = Solicitud.objects.filter(sg__startswith=prefijo).values_list("sg", flat=True)
        ultimo = 0
        # Patrón específico: SG + 2 dígitos año + exactamente 3 dígitos consecutivo
        # Formato: SG26001, SG26002, etc.
        patron = re.compile(rf"^{re.escape(prefijo)}(\d{{3}})$")
        for sg in consecutivos:
            # Sanitizar eliminando guiones para compatibilidad con datos antiguos
            sg_limpio = str(sg).strip().replace("-", "")
            match = patron.match(sg_limpio)
            if match:
                ultimo = max(ultimo, int(match.group(1)))
        return f"{prefijo}{ultimo + 1:03d}"


class CrearUsuarioForm(UserCreationForm):
    primer_nombre = forms.CharField(
        label="Primer nombre",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    segundo_nombre = forms.CharField(
        label="Segundo nombre",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    apellidos = forms.CharField(
        label="Apellidos",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    email = forms.EmailField(
        label="Correo electrónico",
        widget=forms.EmailInput(attrs={"class": "form-control"}),
    )

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
        fields = (
            "username",
            "primer_nombre",
            "segundo_nombre",
            "apellidos",
            "email",
            "password1",
            "password2",
            "rol",
        )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "username",
                "primer_nombre",
                "segundo_nombre",
                "apellidos",
                "email",
                "password1",
                "password2",
                "rol",
            ]
        )
        if "username" in self.fields:
            self.fields["username"].widget.attrs.setdefault("class", "form-control")
        for password_field in ("password1", "password2"):
            if password_field in self.fields:
                self.fields[password_field].widget.attrs.setdefault("class", "form-control")

    def clean_primer_nombre(self):
        return (self.cleaned_data.get("primer_nombre") or "").strip()

    def clean_segundo_nombre(self):
        return (self.cleaned_data.get("segundo_nombre") or "").strip()

    def clean_apellidos(self):
        return (self.cleaned_data.get("apellidos") or "").strip()

    def save(self, commit=True):
        user = super().save(commit=False)
        user.first_name = self.cleaned_data["primer_nombre"]
        user.last_name = self.cleaned_data["apellidos"]
        user.email = self.cleaned_data.get("email", "")
        if commit:
            user.save()
            self.save_profile(user)
        return user

    def save_profile(self, user):
        segundo_nombre = (self.cleaned_data.get("segundo_nombre") or "").strip()
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"segundo_nombre": segundo_nombre},
        )


class EditarUsuarioForm(forms.ModelForm):
    primer_nombre = forms.CharField(
        label="Primer nombre",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    segundo_nombre = forms.CharField(
        label="Segundo nombre",
        required=False,
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )
    apellidos = forms.CharField(
        label="Apellidos",
        widget=forms.TextInput(attrs={"class": "form-control"}),
    )

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
        fields = ("username", "email", "rol")

    def __init__(self, *args, **kwargs):
        self.can_edit_role = kwargs.pop("can_edit_role", True)
        super().__init__(*args, **kwargs)
        self.order_fields(
            [
                "username",
                "primer_nombre",
                "segundo_nombre",
                "apellidos",
                "email",
                "rol",
                "password1",
                "password2",
            ]
        )
        if "username" in self.fields:
            self.fields["username"].widget.attrs.setdefault("class", "form-control")
        if "email" in self.fields:
            self.fields["email"].widget.attrs.setdefault("class", "form-control")
        if self.can_edit_role:
            self.fields["rol"].initial = "admin" if self.instance.is_superuser else "usuario"
        else:
            self.fields.pop("rol")

        if self.instance and self.instance.pk:
            self.fields["primer_nombre"].initial = self.instance.first_name
            self.fields["apellidos"].initial = self.instance.last_name
            try:
                perfil = self.instance.perfil
            except ObjectDoesNotExist:
                perfil = None
            except Exception:
                perfil = None
            if perfil:
                self.fields["segundo_nombre"].initial = getattr(perfil, "segundo_nombre", "")

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

    def clean_primer_nombre(self):
        return (self.cleaned_data.get("primer_nombre") or "").strip()

    def clean_segundo_nombre(self):
        return (self.cleaned_data.get("segundo_nombre") or "").strip()

    def clean_apellidos(self):
        return (self.cleaned_data.get("apellidos") or "").strip()

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.can_edit_role:
            rol = self.cleaned_data["rol"]
            user.is_superuser = rol == "admin"
            user.is_staff = rol == "admin"

        user.first_name = self.cleaned_data["primer_nombre"]
        user.last_name = self.cleaned_data["apellidos"]

        password1 = self.cleaned_data.get("password1")
        if password1:
            user.set_password(password1)

        if commit:
            user.save()
            self.save_profile(user)
        return user

    def save_profile(self, user):
        segundo_nombre = (self.cleaned_data.get("segundo_nombre") or "").strip()
        UserProfile.objects.update_or_create(
            user=user,
            defaults={"segundo_nombre": segundo_nombre},
        )


class CotizacionForm(forms.ModelForm):
    idempotency_key = forms.UUIDField(required=False, widget=forms.HiddenInput)

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
    aerea = forms.BooleanField(
        required=False,
        label="Aérea",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    maritima = forms.BooleanField(
        required=False,
        label="Marítima",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
    )
    terrestre = forms.BooleanField(
        required=False,
        label="Terrestre",
        widget=forms.CheckboxInput(attrs={"class": "form-check-input"}),
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
            "fecha_solicitud": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "fecha_envio": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "tiempo_entrega": forms.TextInput(attrs={"readonly": "readonly", "class": "form-control"}),
            "cliente": forms.TextInput(
                attrs={"class": "form-control", "list": "clientes_datalist", "autocomplete": "off"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configurar_ejecutivo_field(self.fields.get("ejecutivo"))
        self.fields["consecutivo"].required = False
        self.fields["tiempo_entrega"].required = False
        self.fields["aerea"].initial = bool(self.instance.aerea)
        self.fields["maritima"].initial = bool(self.instance.maritima)
        self.fields["terrestre"].initial = bool(self.instance.terrestre)
        if not self.instance.pk:
            anio_actual = date.today().year
            self.fields["anio"].initial = anio_actual
            self.fields["consecutivo"].initial = self._generar_consecutivo(anio_actual)
            self.fields["idempotency_key"].initial = uuid.uuid4()

    def clean(self):
        cleaned_data = super().clean()
        seleccionados = [
            nombre
            for nombre in ("aerea", "maritima", "terrestre")
            if cleaned_data.get(nombre)
        ]
        if len(seleccionados) > 1:
            self.add_error(None, "Selecciona solo un tipo de transporte.")
        elif len(seleccionados) == 0:
            self.add_error(None, "Selecciona un tipo de transporte.")

        fecha_solicitud = cleaned_data.get("fecha_solicitud")
        fecha_envio = cleaned_data.get("fecha_envio")
        if fecha_solicitud and fecha_envio:
            cleaned_data["tiempo_entrega"] = str((fecha_envio - fecha_solicitud).days)
        elif not fecha_envio:
            cleaned_data["tiempo_entrega"] = ""
        return cleaned_data

    def save(self, commit=True):
        cotizacion = super().save(commit=False)
        if not cotizacion.pk:
            cotizacion.consecutivo = self._generar_consecutivo(cotizacion.anio)
        if self.cleaned_data.get("aerea"):
            cotizacion.aerea = "Aérea"
            cotizacion.maritima = ""
            cotizacion.terrestre = ""
        elif self.cleaned_data.get("maritima"):
            cotizacion.aerea = ""
            cotizacion.maritima = "Marítima"
            cotizacion.terrestre = ""
        elif self.cleaned_data.get("terrestre"):
            cotizacion.aerea = ""
            cotizacion.maritima = ""
            cotizacion.terrestre = "Terrestre"
        else:
            cotizacion.aerea = ""
            cotizacion.maritima = ""
            cotizacion.terrestre = ""
        if commit:
            cotizacion.save()
        return cotizacion

    def clean_cliente(self):
        return _validar_cliente(self.cleaned_data.get("cliente"))

    def _generar_consecutivo(self, anio):
        prefijo = f"C{str(anio)[-2:]}"
        consecutivos = Cotizacion.objects.filter(consecutivo__startswith=prefijo).values_list(
            "consecutivo",
            flat=True,
        )
        ultimo = 0
        patron = re.compile(rf"^{re.escape(prefijo)}(\d{{3}})$")
        for consecutivo in consecutivos:
            match = patron.match(str(consecutivo).strip().upper())
            if match:
                ultimo = max(ultimo, int(match.group(1)))
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
        fields = ["ejecutivo", "cliente", "servicio", "medio_operacion", "agencia_aduanal", "fecha"]
        labels = {
            "medio_operacion": "Medio",
        }
        widgets = {
            "fecha": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date", "class": "form-control"}),
            "cliente": forms.TextInput(
                attrs={"class": "form-control", "list": "clientes_datalist", "autocomplete": "off"}
            ),
            "medio_operacion": forms.Select(attrs={"class": "form-select"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _configurar_ejecutivo_field(self.fields.get("ejecutivo"))
        if "medio_operacion" in self.fields:
            self.fields["medio_operacion"].required = False
            choices = list(self.fields["medio_operacion"].choices or [])
            if not choices or choices[0][0] != "":
                self.fields["medio_operacion"].choices = [("", "Seleccionar (opcional)")] + choices
            else:
                self.fields["medio_operacion"].choices = [("", "Seleccionar (opcional)")] + choices[1:]
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
        if commit:
            intentos = 3
            for intento in range(intentos):
                try:
                    with transaction.atomic():
                        if debe_regenerar and referencia.servicio in self.CODIGOS_OPERACION:
                            if not referencia.consecutivo:
                                referencia.consecutivo = self._siguiente_consecutivo_global(
                                    excluir_pk=referencia.pk,
                                )
                            referencia.referencia = self._generar_referencia(
                                fecha=referencia.fecha,
                                operacion=referencia.servicio,
                                consecutivo=referencia.consecutivo,
                            )
                        referencia.save()
                    break
                except IntegrityError:
                    if not debe_regenerar or intento == intentos - 1:
                        raise
        return referencia

    def clean_cliente(self):
        return _validar_cliente(self.cleaned_data.get("cliente"))

    def _generar_referencia(self, fecha, operacion, consecutivo):
        codigo_operacion = self.CODIGOS_OPERACION[operacion]
        anio_corto = (fecha or date.today()).strftime("%y")
        prefijo = f"{self.PREFIJO_EMPRESA}{anio_corto}{codigo_operacion}"
        return f"{prefijo}{int(consecutivo):03d}"

    def _siguiente_consecutivo_global(self, excluir_pk=None):
        qs = Referencia.objects.select_for_update()
        if excluir_pk:
            qs = qs.exclude(pk=excluir_pk)
        ultimo = qs.order_by("-consecutivo").values_list("consecutivo", flat=True).first()
        return (ultimo or 0) + 1
