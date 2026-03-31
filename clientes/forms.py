from django import forms
from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "nombre",
            "empresa",
            "representante_legal",
            "contacto",
            "correo",
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
        nombre = (cleaned_data.get("nombre") or "").strip()
        empresa = (cleaned_data.get("empresa") or "").strip()
        cleaned_data["nombre"] = nombre
        cleaned_data["empresa"] = empresa
        if nombre:
            duplicado = Cliente.objects.filter(nombre__iexact=nombre, empresa__iexact=empresa)
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                raise forms.ValidationError(
                    "Este cliente ya existe con el mismo nombre y empresa."
                )
        return cleaned_data
