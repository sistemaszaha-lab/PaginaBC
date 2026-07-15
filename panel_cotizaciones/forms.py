from pathlib import Path

from django import forms
from django.conf import settings
from django.contrib.auth import get_user_model

from clientes.models import Cliente, normalizar_texto_cliente

from .models import PanelCotizacion, PanelCotizacionComentario

User = get_user_model()


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class MultipleFileField(forms.FileField):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault(
            "widget",
            MultipleFileInput(attrs={"class": "form-control", "multiple": True}),
        )
        super().__init__(*args, **kwargs)

    def clean(self, data, initial=None):
        if data is None:
            return []
        if isinstance(data, (list, tuple)):
            cleaned_files = [super().clean(d, initial) for d in data]
        else:
            cleaned_files = [super().clean(data, initial)]

        allowed_extensions = {
            ext.lower().lstrip(".")
            for ext in getattr(
                settings, "PANEL_COTIZACIONES_ALLOWED_EXTENSIONS", []
            )
        }
        max_size = getattr(settings, "PANEL_COTIZACIONES_MAX_FILE_SIZE", None)

        for uploaded_file in cleaned_files:
            extension = Path(uploaded_file.name).suffix.lower().lstrip(".")
            if allowed_extensions and extension not in allowed_extensions:
                raise forms.ValidationError(
                    "La extension del archivo no esta permitida."
                )
            if max_size and uploaded_file.size > max_size:
                raise forms.ValidationError(
                    "El archivo excede el tamano maximo permitido."
                )

        return cleaned_files


class FirstNameUserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or str(obj.pk)


class FirstNameUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or str(obj.pk)


class ClienteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre or str(obj.pk)


class PanelCotizacionCreateForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by(
            "nombre"
        ),
        required=False,
        empty_label="Seleccione un cliente",
        widget=forms.Select(attrs={"class": "form-select rounded"}),
        label="Cliente",
    )

    class Meta:
        model = PanelCotizacion
        fields = (
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
        )
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control rounded",
                    "placeholder": "Titulo de la cotizacion",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control rounded",
                    "rows": 4,
                    "placeholder": "Describe el alcance o contexto...",
                }
            ),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(
                attrs={"type": "date", "class": "form-control rounded"}
            ),
        }

    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in [
            "titulo",
            "cliente",
            "descripcion",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
        ]:
            if field_name in self.fields:
                self.fields[field_name].required = False

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return normalizar_texto_cliente(cliente.nombre if cliente else "")


class PanelCotizacionInlineCreateForm(PanelCotizacionCreateForm):
    class Meta(PanelCotizacionCreateForm.Meta):
        fields = ("titulo", "cliente", "prioridad")
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control rounded",
                    "placeholder": "Titulo o referencia",
                }
            ),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if "cliente" in self.fields:
            self.fields["cliente"].widget.attrs.update(
                {"class": "form-select rounded"}
            )


class PanelCotizacionInlineTituloForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("titulo",)
        widgets = {
            "titulo": forms.TextInput(
                attrs={"class": "form-control form-control-sm rounded"}
            )
        }


class PanelCotizacionInlinePrioridadForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("prioridad",)
        widgets = {
            "prioridad": forms.Select(
                attrs={"class": "form-select form-select-sm rounded"}
            )
        }


class PanelCotizacionInlineVencimientoForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("fecha_vencimiento",)
        widgets = {
            "fecha_vencimiento": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm rounded",
                }
            )
        }


class PanelCotizacionInlineClienteForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by(
            "nombre"
        ),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select form-select-sm rounded"}),
        label="Cliente",
    )

    class Meta:
        model = PanelCotizacion
        fields = ("cliente",)

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return normalizar_texto_cliente(cliente.nombre if cliente else "")


class PanelCotizacionInlineAsignadosForm(forms.ModelForm):
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select form-select-sm rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = PanelCotizacion
        fields = ("asignados",)


class PanelCotizacionArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


class PanelCotizacionEnlaceForm(forms.Form):
    titulo = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control rounded", "placeholder": "Ej. Propuesta"}
        ),
    )
    url = forms.URLField(
        required=False,
        max_length=1000,
        widget=forms.URLInput(
            attrs={"class": "form-control rounded", "placeholder": "https://..."}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "url"]:
            if name in self.fields:
                self.fields[name].required = False


class PanelCotizacionUpdateForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("titulo", "descripcion", "prioridad", "fecha_vencimiento", "asignados")
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control rounded"}),
            "descripcion": forms.Textarea(
                attrs={"class": "form-control rounded", "rows": 4}
            ),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(
                attrs={"type": "date", "class": "form-control rounded"}
            ),
        }

    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in list(self.fields.keys()):
            self.fields[field_name].required = False


class PanelCotizacionComentarioForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacionComentario
        fields = ("texto",)
        widgets = {
            "texto": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Escribe un comentario..."}
            )
        }


class PanelCotizacionUserFilterForm(forms.Form):
    usuario = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "id": "panelCotizacionesUserFilter",
                "data-garantia-tags-select": "1",
            }
        ),
    )
