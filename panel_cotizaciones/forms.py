from django import forms
from django.contrib.auth import get_user_model

from clientes.models import Cliente
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
            return [super().clean(d, initial) for d in data]
        return [super().clean(data, initial)]


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
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by("nombre"),
        required=False,
        empty_label="Seleccione un cliente",
        widget=forms.Select(attrs={"class": "form-select rounded"}),
        label="Cliente",
    )

    class Meta:
        model = PanelCotizacion
        fields = ("titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados")
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control rounded", "placeholder": "Título de la cotización"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control rounded", "rows": 4, "placeholder": "Describe el alcance o contexto..."}),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date", "class": "form-control rounded"}),
        }

    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select rounded garantia-asignados-select", "data-garantia-tags-select": "1"}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in ["titulo", "cliente", "descripcion", "prioridad", "fecha_vencimiento", "asignados"]:
            if field_name in self.fields:
                self.fields[field_name].required = False

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return cliente.nombre if cliente else ""


class PanelCotizacionArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


class PanelCotizacionEnlaceForm(forms.Form):
    titulo = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(attrs={"class": "form-control rounded", "placeholder": "Ej. Propuesta"}),
    )
    url = forms.URLField(
        required=False,
        max_length=1000,
        widget=forms.URLInput(attrs={"class": "form-control rounded", "placeholder": "https://..."}),
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
            "descripcion": forms.Textarea(attrs={"class": "form-control rounded", "rows": 4}),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(attrs={"type": "date", "class": "form-control rounded"}),
        }

    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(attrs={"class": "form-select rounded garantia-asignados-select", "data-garantia-tags-select": "1"}),
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
    usuario = FirstNameUserChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        empty_label="Todos",
        widget=forms.Select(attrs={"class": "form-select", "id": "panelCotizacionesUserFilter"}),
    )

