from django import forms
from .models import Cliente
from .models import normalizar_texto_cliente


MENSAJE_CLIENTE_DUPLICADO = "Ya existe un cliente con el mismo nombre y empresa."


class ClienteForm(forms.ModelForm):
    def __init__(self, *args, requerir_datos_alta=False, **kwargs):
        super().__init__(*args, **kwargs)
        if requerir_datos_alta:
            self.fields["nombre"].required = True
            self.fields["correo"].required = True
            self.fields["contacto"].required = True

    class Meta:
        model = Cliente
        fields = [
            "nombre",
            "empresa",
            "representante_legal",
            "contacto",
            "correo",
            "cuentas_por_cobrar",
            "telefono",
            "celular",
            "estado",
        ]
        labels = {
            "nombre": "Cliente",
            "empresa": "Razón social",
            "representante_legal": "Representante legal",
            "contacto": "Contacto",
            "correo": "Correo",
            "cuentas_por_cobrar": "Cuentas por cobrar",
            "telefono": "Teléfono",
            "celular": "Celular",
            "estado": "Status",
        }
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "empresa": forms.TextInput(attrs={"class": "form-control"}),
            "representante_legal": forms.TextInput(attrs={"class": "form-control"}),
            "contacto": forms.TextInput(attrs={"class": "form-control"}),
            "correo": forms.EmailInput(
                attrs={"class": "form-control", "autocomplete": "email"}
            ),
            "cuentas_por_cobrar": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(
                attrs={"class": "form-control", "inputmode": "tel", "autocomplete": "tel"}
            ),
            "celular": forms.TextInput(
                attrs={"class": "form-control", "inputmode": "tel", "autocomplete": "tel"}
            ),
            "estado": forms.Select(attrs={"class": "form-select"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        nombre = normalizar_texto_cliente(cleaned_data.get("nombre"))
        empresa = normalizar_texto_cliente(cleaned_data.get("empresa"))
        cleaned_data["nombre"] = nombre
        cleaned_data["empresa"] = empresa
        if nombre:
            duplicado = Cliente.objects.filter(nombre__iexact=nombre, empresa__iexact=empresa)
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                raise forms.ValidationError(MENSAJE_CLIENTE_DUPLICADO)
        return cleaned_data
