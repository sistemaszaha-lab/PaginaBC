from django import forms
from django.contrib.auth import get_user_model

from .models import Incidencia


class IncidenciaForm(forms.ModelForm):
    responsable = forms.ModelChoiceField(
        queryset=get_user_model().objects.all().order_by("username"),
        required=True,
    )

    class Meta:
        model = Incidencia
        fields = [
            "codigo",
            "titulo",
            "descripcion",
            "responsable",
            "estado",
            "prioridad",
            "fecha_limite",
        ]

