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


class OperacionEtiquetaForm(forms.ModelForm):
    class Meta:
        model = OperacionEtiqueta
        fields = ["nombre", "color"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la etiqueta"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
        self.fields["color"].required = True


class OperacionOpcionForm(forms.ModelForm):
    class Meta:
        model = OperacionOpcion
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la opción"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
