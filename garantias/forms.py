from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator

from clientes.models import Cliente

from .models import Garantia, GarantiaColumna, GarantiaEnlace, GarantiaEtiqueta

User = get_user_model()
MAX_GARANTIA_ARCHIVO_SIZE = 10 * 1024 * 1024
GARANTIA_ARCHIVO_EXTENSIONS = {
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


class FirstNameUserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or obj.get_full_name() or obj.username


class ClienteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre or obj.empresa or str(obj.pk)


class GarantiaForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )
    etiquetas = forms.ModelMultipleChoiceField(
        queryset=GarantiaEtiqueta.objects.all().order_by("nombre", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select garantia-etiquetas-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = Garantia
        fields = [
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "fecha_pago",
            "asignados",
            "etiquetas",
        ]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control", "type": "date"},
            ),
            "fecha_pago": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "fecha_pago", "asignados", "etiquetas"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre

    def clean_titulo(self):
        titulo = (self.cleaned_data.get("titulo") or "").strip()
        if not titulo:
            raise forms.ValidationError("El titulo es obligatorio.")
        return titulo


class GarantiaInlineCreateForm(GarantiaForm):
    archivos = MultipleFileField(required=False)
    enlaces = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta(GarantiaForm.Meta):
        fields = [
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "fecha_pago",
            "asignados",
            "etiquetas",
        ]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Titulo o referencia",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm",
                    "rows": 2,
                    "placeholder": "Descripcion",
                }
            ),
            "cliente": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "fecha_vencimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control form-control-sm", "type": "date"},
            ),
            "fecha_pago": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control form-control-sm", "type": "date"},
            ),
            "etiquetas": forms.SelectMultiple(
                attrs={
                    "class": "form-select form-select-sm",
                    "data-garantia-tags-select": "1",
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
            "fecha_pago",
            "asignados",
            "etiquetas",
            "archivos",
            "enlaces",
        ]:
            self.fields[field_name].required = False
        self.fields["cliente"].queryset = (
            Cliente.objects.only("id", "nombre", "empresa").order_by("nombre", "empresa", "id")
        )
        self.fields["asignados"].queryset = User.objects.only(
            "id", "first_name", "last_name", "username"
        ).order_by("first_name", "last_name", "username", "id")
        self.fields["etiquetas"].queryset = GarantiaEtiqueta.objects.only(
            "id", "nombre"
        ).order_by("nombre", "id")
        self.fields["archivos"].widget.attrs.update(
            {
                "class": "form-control form-control-sm",
                "accept": ",".join(sorted(GARANTIA_ARCHIVO_EXTENSIONS)),
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

    def clean_archivos(self):
        archivos = self.files.getlist("archivos")
        archivos_limpios = []
        for archivo in archivos:
            nombre = Path(archivo.name or "").name.strip()
            extension = Path(nombre).suffix.lower()
            if not nombre:
                raise forms.ValidationError("Cada archivo debe conservar un nombre valido.")
            if extension not in GARANTIA_ARCHIVO_EXTENSIONS:
                raise forms.ValidationError(
                    "Solo se permiten archivos PDF, Excel, Word, imagen, CSV, TXT, WEBP o ZIP."
                )
            if archivo.size > MAX_GARANTIA_ARCHIVO_SIZE:
                raise forms.ValidationError("Cada archivo debe pesar como maximo 10 MB.")
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


class GarantiaEditarForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )
    class Meta:
        model = Garantia
        fields = [
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "fecha_pago",
            "asignados",
        ]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control", "type": "date"},
            ),
            "fecha_pago": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control", "type": "date"},
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "fecha_pago", "asignados"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["cliente"].queryset = (
            Cliente.objects.only("id", "nombre", "empresa").order_by("nombre", "empresa", "id")
        )
        self.fields["asignados"].queryset = User.objects.only(
            "id", "first_name", "last_name", "username"
        ).order_by("first_name", "last_name", "username", "id")


class GarantiaQuickEditForm(GarantiaEditarForm):
    """Formulario completo y limitado para la edicion rapida de una tarjeta."""

    class Meta(GarantiaEditarForm.Meta):
        fields = ["titulo", "cliente", "prioridad", "fecha_vencimiento", "fecha_pago", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "fecha_vencimiento": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control form-control-sm", "type": "date"},
            ),
            "fecha_pago": forms.DateInput(
                format="%Y-%m-%d",
                attrs={"class": "form-control form-control-sm", "type": "date"},
            ),
        }


class GarantiaComentarioForm(forms.Form):
    comentario = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Escribe un comentario..."}),
    )


class GarantiaArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


class GarantiaArchivoUploadForm(forms.Form):
    """Valida los adjuntos de la seccion AJAX de una garantia."""

    max_archivos = 5
    max_tamano_archivo = MAX_GARANTIA_ARCHIVO_SIZE
    extensiones_permitidas = GARANTIA_ARCHIVO_EXTENSIONS

    archivos = MultipleFileField(required=True)

    def clean_archivos(self):
        archivos = self.cleaned_data["archivos"]
        if not archivos:
            raise forms.ValidationError("Selecciona al menos un archivo.")
        if len(archivos) > self.max_archivos:
            raise forms.ValidationError(
                f"Puedes subir hasta {self.max_archivos} archivos a la vez."
            )
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


class GarantiaEnlaceForm(forms.ModelForm):
    class Meta:
        model = GarantiaEnlace
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


class GarantiaEnlaceCreateForm(GarantiaEnlaceForm):
    """Valida enlaces creados desde la seccion AJAX del detalle."""

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


class GarantiaColumnaCreateForm(forms.ModelForm):
    class Meta:
        model = GarantiaColumna
        fields = ("nombre",)
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre de la columna",
                }
            )
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Este campo es obligatorio.")
        if len(nombre) > 120:
            raise forms.ValidationError("El nombre es demasiado largo.")
        return nombre


class GarantiaColumnaUpdateForm(GarantiaColumnaCreateForm):
    pass

class GarantiaEtiquetaAssignForm(forms.Form):
    etiquetas = forms.ModelMultipleChoiceField(
        queryset=GarantiaEtiqueta.objects.all().order_by("nombre", "id"),
        required=True,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )

class GarantiaEtiquetaCreateForm(forms.ModelForm):
    class Meta:
        model = GarantiaEtiqueta
        fields = ["nombre", "color"]
