from django import forms
from django.contrib.auth import get_user_model

from clientes.models import Cliente

from .models import CuentaGastos, CuentaGastosEnlace, CuentaGastosEtiqueta, CuentaGastosOpcion


class FirstNameUserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or obj.get_full_name() or obj.username


class ClienteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre or obj.empresa or str(obj.pk)


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


class CuentaGastosForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=get_user_model().objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-cuenta-tags-select": "1",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = CuentaGastos
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "etiquetas": forms.SelectMultiple(attrs={"class": "form-select rounded", "id": "id_etiquetas", "data-cuenta-tags-select": "1", "data-garantia-tags-select": "1"}),
            "opciones": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre


class CuentaGastosInlineCreateForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    class Meta:
        model = CuentaGastos
        fields = ["titulo", "cliente", "prioridad"]
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Nombre de la cuenta",
                }
            ),
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        self.fields["cliente"].required = False
        self.fields["prioridad"].required = False


class CuentaGastosEditarForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select"}),
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=get_user_model().objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-cuenta-tags-select": "1",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = CuentaGastos
        fields = ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control"}),
            "descripcion": forms.Textarea(attrs={"class": "form-control", "rows": 3}),
            "prioridad": forms.Select(attrs={"class": "form-select"}),
            "fecha_vencimiento": forms.DateInput(attrs={"class": "form-control", "type": "date"}),
            "etiquetas": forms.SelectMultiple(attrs={"class": "form-select rounded", "id": "id_etiquetas", "data-cuenta-tags-select": "1", "data-garantia-tags-select": "1"}),
            "opciones": forms.CheckboxSelectMultiple(attrs={"class": "form-check-input"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "descripcion", "cliente", "prioridad", "fecha_vencimiento", "asignados", "etiquetas", "opciones"]:
            if name in self.fields:
                self.fields[name].required = False
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre


class CuentaGastosTituloInlineForm(forms.ModelForm):
    class Meta:
        model = CuentaGastos
        fields = ["titulo"]
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control form-control-sm"})
        }


class CuentaGastosPrioridadInlineForm(forms.ModelForm):
    class Meta:
        model = CuentaGastos
        fields = ["prioridad"]
        widgets = {
            "prioridad": forms.Select(attrs={"class": "form-select form-select-sm"})
        }


class CuentaGastosVencimientoInlineForm(forms.ModelForm):
    class Meta:
        model = CuentaGastos
        fields = ["fecha_vencimiento"]
        widgets = {
            "fecha_vencimiento": forms.DateInput(
                attrs={"class": "form-control form-control-sm", "type": "date"}
            )
        }


class CuentaGastosClienteInlineForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.all().order_by("nombre", "empresa", "id"),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select form-select-sm"}),
    )

    class Meta:
        model = CuentaGastos
        fields = ["cliente"]


class CuentaGastosAsignadosInlineForm(forms.ModelForm):
    asignados = FirstNameUserMultipleChoiceField(
        queryset=get_user_model().objects.all().order_by("first_name", "last_name", "username", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select form-select-sm garantia-asignados-select",
                "data-cuenta-tags-select": "1",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = CuentaGastos
        fields = ["asignados"]


class CuentaGastosComentarioForm(forms.Form):
    comentario = forms.CharField(
        required=True,
        widget=forms.Textarea(attrs={"class": "form-control", "rows": 2, "placeholder": "Escribe un comentario..."}),
    )


class CuentaGastosEtiquetasSectionForm(forms.ModelForm):
    class Meta:
        model = CuentaGastos
        fields = ["etiquetas"]
        widgets = {
            "etiquetas": forms.SelectMultiple(
                attrs={
                    "class": "form-select rounded",
                    "data-cuenta-tags-select": "1",
                    "data-garantia-tags-select": "1",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["etiquetas"].required = False
        self.fields["etiquetas"].label_from_instance = lambda obj: obj.nombre


class CuentaGastosOpcionesSectionForm(forms.ModelForm):
    class Meta:
        model = CuentaGastos
        fields = ["opciones"]
        widgets = {
            "opciones": forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["opciones"].required = False


class CuentaGastosEtiquetaCreateForm(forms.ModelForm):
    class Meta:
        model = CuentaGastosEtiqueta
        fields = ["nombre", "color"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la etiqueta"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
        self.fields["color"].required = True


class CuentaGastosOpcionCreateForm(forms.ModelForm):
    class Meta:
        model = CuentaGastosOpcion
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la opción"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True


class CuentaGastosArchivosForm(forms.Form):
    archivos = MultipleFileField(required=True)

    def clean_archivos(self):
        archivos = self.cleaned_data.get("archivos") or []
        if not archivos:
            raise forms.ValidationError("Selecciona al menos un archivo.")
        return archivos


class CuentaGastosEnlaceForm(forms.ModelForm):
    class Meta:
        model = CuentaGastosEnlace
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


class CuentaGastosEtiquetaForm(forms.ModelForm):
    class Meta:
        model = CuentaGastosEtiqueta
        fields = ["nombre", "color"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la etiqueta"}),
            "color": forms.TextInput(attrs={"class": "form-control", "type": "color"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
        self.fields["color"].required = True


class CuentaGastosOpcionForm(forms.ModelForm):
    class Meta:
        model = CuentaGastosOpcion
        fields = ["nombre"]
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control", "placeholder": "Nombre de la opción"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
