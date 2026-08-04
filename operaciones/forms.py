import re
from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator

from clientes.models import Cliente

from .models import (
    Operacion,
    OperacionColumna,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)


MAX_OPERACION_ARCHIVO_SIZE = 10 * 1024 * 1024
OPERACION_ARCHIVO_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".txt",
    ".webp",
    ".xls",
    ".xlsx",
    ".zip",
}


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
    """Formulario inline completo para crear una operacion en el tablero."""

    archivos = MultipleFileField(required=False)
    enlaces = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta:
        model = Operacion
        fields = [
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
        ]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Nombre de la operacion",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Descripcion",
                    "rows": 2,
                }
            ),
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
            "etiquetas": forms.SelectMultiple(
                attrs={
                    "class": "form-select form-select-sm",
                    "data-operacion-tags-select": "1",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        for field_name in [
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
            "archivos",
            "enlaces",
        ]:
            self.fields[field_name].required = False

        self.fields["cliente"].queryset = Cliente.objects.only(
            "id", "nombre", "empresa"
        ).order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.only(
            "id", "first_name", "last_name", "username"
        ).order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name or obj.username
        self.fields["etiquetas"].queryset = OperacionEtiqueta.objects.only(
            "id", "nombre"
        ).order_by("nombre", "id")
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre
        self.fields["archivos"].widget.attrs.update(
            {
                "class": "form-control form-control-sm",
                "accept": ",".join(sorted(OPERACION_ARCHIVO_EXTENSIONS)),
            }
        )
        self.link_rows = self._build_link_rows()

    def _build_link_rows(self):
        if not self.is_bound:
            return [{"titulo": "", "url": ""}]

        titles = self.data.getlist("enlace_titulo")
        urls = self.data.getlist("enlace_url")
        total = max(len(titles), len(urls), 1)
        return [
            {
                "titulo": titles[index] if index < len(titles) else "",
                "url": urls[index] if index < len(urls) else "",
            }
            for index in range(total)
        ]

    def clean_titulo(self):
        titulo = (self.cleaned_data.get("titulo") or "").strip()
        if not titulo:
            raise forms.ValidationError("Este campo es obligatorio.")
        return titulo

    def clean_archivos(self):
        archivos = self.files.getlist("archivos")
        archivos_limpios = []
        for archivo in archivos:
            nombre = Path(archivo.name or "").name.strip()
            extension = Path(nombre).suffix.lower()
            if not nombre:
                raise forms.ValidationError("Cada archivo debe conservar un nombre valido.")
            if extension not in OPERACION_ARCHIVO_EXTENSIONS:
                raise forms.ValidationError(
                    "Solo se permiten archivos PDF, Excel, Word, imagen, CSV, TXT, WEBP o ZIP."
                )
            if archivo.size > MAX_OPERACION_ARCHIVO_SIZE:
                raise forms.ValidationError(
                    "Cada archivo debe pesar como maximo 10 MB."
                )
            archivo.name = nombre
            archivos_limpios.append(archivo)
        return archivos_limpios

    def clean(self):
        cleaned_data = super().clean()

        titles = self.data.getlist("enlace_titulo")
        urls = self.data.getlist("enlace_url")
        total = max(len(titles), len(urls))
        validator = URLValidator()
        enlaces = []
        errores = []

        for index in range(total):
            titulo = (titles[index] if index < len(titles) else "").strip()
            url = (urls[index] if index < len(urls) else "").strip()

            if not titulo and not url:
                continue
            if not titulo:
                errores.append(f"Enlace {index + 1}: captura un titulo.")
                continue
            if not url:
                errores.append(f"Enlace {index + 1}: captura una URL.")
                continue

            try:
                validator(url)
            except forms.ValidationError:
                errores.append(f"Enlace {index + 1}: captura una URL valida.")
                continue

            enlaces.append({"titulo": titulo, "url": url})

        if errores:
            self.add_error("enlaces", errores)

        cleaned_data["enlaces_payload"] = enlaces
        return cleaned_data


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


class OperacionColumnaCreateForm(forms.ModelForm):
    class Meta:
        model = OperacionColumna
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Debes capturar un nombre.")
        return nombre


class OperacionColumnaUpdateForm(OperacionColumnaCreateForm):
    pass
