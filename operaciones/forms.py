import re
from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model

from clientes.models import Cliente

from .models import Operacion, OperacionEnlace, OperacionEtiqueta, OperacionOpcion


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", MultipleFileInput(attrs={"class": "form-control", "multiple": True}))
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if data is None:
            return []
        if isinstance(data, (list, tuple)):
            return [super().clean(d, initial) for d in data]
        return [super().clean(data, initial)]


class OperacionForm(forms.ModelForm):
    class Meta:
        model = Operacion
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cliente": forms.Select(attrs={"class": "form-select"}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "asignados": forms.SelectMultiple(attrs={"class": "form-select rounded garantia-asignados-select", "data-operacion-tags-select": "1"}),
            "etiquetas": forms.SelectMultiple(attrs={"class": "form-select rounded", "id": "id_etiquetas", "data-operacion-tags-select": "1"}),
            "opciones": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.all().order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre


class OperacionInlineCreateForm(forms.ModelForm):
    """Campos minimos para crear una operacion desde una columna del tablero."""

    class Meta:
        model = Operacion
        fields = ["titulo", "cliente", "prioridad"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Nombre de la operacion",
                }
            ),
            "cliente": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        self.fields["cliente"].required = False
        self.fields["prioridad"].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")


class OperacionQuickEditForm(forms.ModelForm):
    """Campos seguros para la edicion rapida dentro de una tarjeta."""

    class Meta:
        model = Operacion
        fields = ["titulo", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "cliente": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "fecha_vencimiento": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            ),
            "asignados": forms.SelectMultiple(
                attrs={
                    "class": "form-select form-select-sm garantia-asignados-select",
                    "data-operacion-tags-select": "1",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        self.fields["cliente"].required = False
        self.fields["prioridad"].required = False
        self.fields["fecha_vencimiento"].required = False
        self.fields["asignados"].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.all().order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name or obj.username

class OperacionEditarForm(forms.ModelForm):
    class Meta:
        model = Operacion
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cliente": forms.Select(attrs={"class": "form-select"}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "asignados": forms.SelectMultiple(attrs={"class": "form-select rounded garantia-asignados-select", "data-operacion-tags-select": "1"}),
            "etiquetas": forms.SelectMultiple(attrs={"class": "form-select rounded", "id": "id_etiquetas", "data-operacion-tags-select": "1"}),
            "opciones": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.all().order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre


class OperacionComentarioForm(forms.Form):
    comentario = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Escribe un comentario..."}),
    )


class OperacionArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


class OperacionArchivoUploadForm(forms.Form):
    """Valida adjuntos enviados desde la seccion AJAX de archivos."""

    max_archivos = 5
    max_tamano_archivo = 10 * 1024 * 1024
    extensiones_permitidas = {
        ".pdf", ".csv", ".txt", ".doc", ".docx", ".xls", ".xlsx",
        ".png", ".jpg", ".jpeg", ".webp", ".zip",
    }

    archivos = MultipleFileField(required=True)

    def clean_archivos(self):
        archivos = self.cleaned_data["archivos"]
        if not archivos:
            raise forms.ValidationError("Selecciona al menos un archivo.")
        if len(archivos) > self.max_archivos:
            raise forms.ValidationError(f"Puedes subir hasta {self.max_archivos} archivos a la vez.")

        for archivo in archivos:
            if archivo.size > self.max_tamano_archivo:
                raise forms.ValidationError(
                    f"{archivo.name} supera el limite de 10 MB por archivo."
                )
            if Path(archivo.name).suffix.lower() not in self.extensiones_permitidas:
                raise forms.ValidationError(
                    f"{archivo.name} tiene un formato no permitido."
                )
        return archivos


class OperacionEnlaceForm(forms.ModelForm):
    class Meta:
        model = OperacionEnlace
        fields = ["titulo", "url"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Factura"}),
            "url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "url"]:
            if name in self.fields:
                self.fields[name].required = False


class OperacionEnlaceCreateForm(forms.ModelForm):
    """Valida enlaces agregados desde la seccion AJAX del detalle."""

    class Meta:
        model = OperacionEnlace
        fields = ["titulo", "url"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control", "placeholder": "Ej. Factura"}),
            "url": forms.URLInput(attrs={"class": "form-control", "placeholder": "https://..."}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        self.fields["url"].required = True

    def clean_url(self):
        url = self.cleaned_data["url"]
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise forms.ValidationError("Ingresa una URL HTTP o HTTPS valida.")
        if parsed.username or parsed.password:
            raise forms.ValidationError("La URL no puede incluir credenciales.")
        return url


class OperacionEtiquetaAssignForm(forms.Form):
    etiqueta = forms.ModelChoiceField(
        queryset=OperacionEtiqueta.objects.none(),
        empty_label="Selecciona una etiqueta",
        widget=forms.Select(attrs={"class": "form-select"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["etiqueta"].queryset = OperacionEtiqueta.objects.order_by("nombre", "id")
        self.fields["etiqueta"].label_from_instance = lambda etiqueta: etiqueta.nombre


class OperacionEtiquetaCreateForm(forms.Form):
    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nueva etiqueta"}),
    )
    color = forms.CharField(
        max_length=7,
        widget=forms.TextInput(attrs={"class": "form-control form-control-color", "type": "color"}),
    )

    def clean_nombre(self):
        return self.cleaned_data["nombre"].strip()
    def clean_color(self):
        color = self.cleaned_data["color"].strip()
        if not re.fullmatch(r"#[0-9A-Fa-f]{6}", color):
            raise forms.ValidationError("Selecciona un color hexadecimal valido.")
        return color.upper()


class OperacionOpcionesSectionForm(forms.ModelForm):
    """Actualiza solo las opciones asociadas a una operacion."""

    class Meta:
        model = Operacion
        fields = ["opciones"]
        widgets = {
            "opciones": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["opciones"].required = False
        self.fields["opciones"].queryset = OperacionOpcion.objects.order_by("nombre", "id")


class OperacionOpcionCreateForm(forms.Form):
    """Valida una opcion nueva antes de asociarla a una operacion."""

    nombre = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={"class": "form-control", "placeholder": "Nueva opcion"}),
    )

    def clean_nombre(self):
        return self.cleaned_data["nombre"].strip()
