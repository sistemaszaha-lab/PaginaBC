from django import forms
from django.contrib.auth import get_user_model

from clientes.models import Cliente

from .models import Garantia, GarantiaEnlace


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


class GarantiaForm(forms.ModelForm):
    class Meta:
        model = Garantia
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cliente": forms.Select(attrs={"class": "form-select"}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "asignados": forms.SelectMultiple(attrs={"class": "form-select garantia-asignados-select", "data-garantia-tags-select": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.all().order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name


class GarantiaEditarForm(forms.ModelForm):
    class Meta:
        model = Garantia
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "cliente": forms.Select(attrs={"class": "form-select"}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "asignados": forms.SelectMultiple(attrs={"class": "form-select garantia-asignados-select", "data-garantia-tags-select": "1"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["cliente"].queryset = Cliente.objects.all().order_by("nombre", "empresa", "id")
        User = get_user_model()
        self.fields["asignados"].queryset = User.objects.all().order_by("first_name", "last_name", "username", "id")
        self.fields["asignados"].label_from_instance = lambda obj: obj.first_name


class GarantiaComentarioForm(forms.Form):
    comentario = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Escribe un comentario..."}),
    )


class GarantiaArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


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
