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

    def __init__(self, *args, **kwargs):
        instance = kwargs.get("instance")
        self._titulo_original = getattr(instance, "titulo", "")
        super().__init__(*args, **kwargs)
        if "titulo" in self.fields:
            self.fields["titulo"].required = False

    def save(self, commit=True):
        titulo_omitido = self.instance.pk and "titulo" not in self.data
        incidencia = super().save(commit=False)
        if titulo_omitido:
            incidencia.titulo = self._titulo_original
        elif not incidencia.titulo:
            incidencia.titulo = self.instance.titulo or incidencia.codigo
        if commit:
            incidencia.save()
            self.save_m2m()
        return incidencia


class IncidenciaCreateForm(IncidenciaForm):
    class Meta(IncidenciaForm.Meta):
        fields = [
            "codigo",
            "descripcion",
            "responsable",
            "estado",
            "prioridad",
            "fecha_limite",
        ]

    def save(self, commit=True):
        incidencia = super().save(commit=False)
        if not incidencia.titulo:
            incidencia.titulo = incidencia.codigo
        if commit:
            incidencia.save()
            self.save_m2m()
        return incidencia
