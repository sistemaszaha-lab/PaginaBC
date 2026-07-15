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


class GarantiaInlineTituloForm(forms.ModelForm):
    class Meta:
        model = Garantia
        fields = ["titulo"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control form-control-sm"})
        }


class GarantiaInlinePrioridadForm(forms.ModelForm):
    class Meta:
        model = Garantia
        fields = ["prioridad"]
        widgets = {
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"})
        }


class GarantiaInlineVencimientoForm(forms.ModelForm):
    class Meta:
        model = Garantia
        fields = ["fecha_vencimiento"]
        widgets = {
            "fecha_vencimiento": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            )
        }


class GarantiaInlineClienteForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    class Meta:
        model = Garantia
        fields = ["cliente"]


class GarantiaInlineAsignadosForm(forms.ModelForm):
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select form-select-sm garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = Garantia
        fields = ["asignados"]


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
