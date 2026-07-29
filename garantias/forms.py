from pathlib import Path
from urllib.parse import urlsplit

from django import forms
from django.contrib.auth import get_user_model

from clientes.models import Cliente

from .models import Garantia, GarantiaEnlace

User = get_user_model()


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

    class Meta:
        model = Garantia
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]:
            if name in self.fields:
                self.fields[name].required = False


class GarantiaInlineCreateForm(GarantiaForm):
    class Meta(GarantiaForm.Meta):
        fields = ["titulo", "cliente", "prioridad"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Titulo o referencia",
                }
            ),
            "cliente": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "cliente" in self.fields:
            self.fields["cliente"].queryset = (
                Cliente.objects.only("id", "nombre", "empresa")
                .order_by("nombre", "empresa", "id")
            )


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
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]:
            if name in self.fields:
                self.fields[name].required = False


class GarantiaQuickEditForm(GarantiaEditarForm):
    """Formulario completo y limitado para la edicion rapida de una tarjeta."""

    class Meta(GarantiaEditarForm.Meta):
        fields = ["titulo", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control form-control-sm"}),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control form-control-sm", "type": "date"}),
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
