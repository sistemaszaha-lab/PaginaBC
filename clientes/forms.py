from django import forms

from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = [
            "nombre",
            "empresa",
            "telefono",
            "correo",
            "direccion",
            "rfc",
            "estado",
            "fecha_alta",
            "notas",
        ]
        labels = {
            "telefono": "Telefono",
            "direccion": "Direccion",
            "rfc": "RFC",
            "fecha_alta": "Fecha de alta",
        }
        widgets = {
            "nombre": forms.TextInput(attrs={"class": "form-control"}),
            "empresa": forms.TextInput(attrs={"class": "form-control"}),
            "telefono": forms.TextInput(attrs={"class": "form-control"}),
            "correo": forms.EmailInput(attrs={"class": "form-control"}),
            "direccion": forms.TextInput(attrs={"class": "form-control"}),
            "rfc": forms.TextInput(attrs={"class": "form-control"}),
            "estado": forms.Select(attrs={"class": "form-select"}),
            "fecha_alta": forms.DateInput(attrs={"type": "date", "class": "form-control"}),
            "notas": forms.Textarea(attrs={"rows": 4, "class": "form-control"}),
        }

    def clean(self):
        cleaned_data = super().clean()
        nombre = (cleaned_data.get("nombre") or "").strip()
        empresa = (cleaned_data.get("empresa") or "").strip()
        if nombre:
            duplicado = Cliente.objects.filter(nombre__iexact=nombre, empresa__iexact=empresa)
            if self.instance.pk:
                duplicado = duplicado.exclude(pk=self.instance.pk)
            if duplicado.exists():
                raise forms.ValidationError(
                    "Este cliente ya existe con el mismo nombre y empresa."
                )
        return cleaned_data
