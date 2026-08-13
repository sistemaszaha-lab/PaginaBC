from pathlib import Path

from django import forms
from django.contrib.auth import get_user_model
from django.core.validators import URLValidator

from clientes.models import Cliente, normalizar_texto_cliente

from .models import (
    PanelCotizacion,
    PanelCotizacionComentario,
    PanelCotizacionColumna,
    PanelCotizacionElementoAccion,
    PanelCotizacionEtiqueta,
)

User = get_user_model()
MAX_PANEL_ARCHIVO_SIZE = 10 * 1024 * 1024
PANEL_ARCHIVO_EXTENSIONS = {
    ".csv",
    ".doc",
    ".docx",
    ".jpeg",
    ".jpg",
    ".pdf",
    ".png",
    ".txt",
    ".xls",
    ".xlsx",
}


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
            cleaned_files = [super().clean(d, initial) for d in data]
        else:
            cleaned_files = [super().clean(data, initial)]

        for uploaded_file in cleaned_files:
            filename = Path(uploaded_file.name or "").name.strip()
            extension = Path(filename).suffix.lower()
            if not filename:
                raise forms.ValidationError(
                    "Cada archivo debe conservar un nombre valido."
                )
            if extension not in PANEL_ARCHIVO_EXTENSIONS:
                raise forms.ValidationError(
                    "Solo se permiten archivos PDF, Excel, Word, imagen, CSV o TXT."
                )
            if uploaded_file.size > MAX_PANEL_ARCHIVO_SIZE:
                raise forms.ValidationError(
                    "Cada archivo debe pesar como maximo 10 MB."
                )
            uploaded_file.name = filename

        return cleaned_files


class FirstNameUserMultipleChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or str(obj.pk)


class FirstNameUserChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return (obj.first_name or "").strip() or str(obj.pk)


class ClienteChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre or str(obj.pk)


class EtiquetaChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, obj):
        return obj.nombre or str(obj.pk)


class PanelCotizacionBaseForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by(
            "nombre"
        ),
        required=False,
        empty_label="Seleccione un cliente",
        widget=forms.Select(attrs={"class": "form-select rounded"}),
        label="Cliente",
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )
    etiquetas = EtiquetaChoiceField(
        queryset=PanelCotizacionEtiqueta.objects.all().order_by("nombre", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded",
                "data-panel-cotizacion-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = PanelCotizacion
        fields = (
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
        )
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control rounded",
                    "placeholder": "Titulo de la cotizacion",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control rounded",
                    "rows": 4,
                    "placeholder": "Describe el alcance o contexto...",
                }
            ),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(
                attrs={"type": "date", "class": "form-control rounded"}
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["titulo"].required = True
        for field_name in (
            "cliente",
            "descripcion",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
        ):
            self.fields[field_name].required = False
        self.fields["etiquetas"].label = "Etiquetas"

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return normalizar_texto_cliente(cliente.nombre if cliente else "")

    def clean_titulo(self):
        titulo = (self.cleaned_data.get("titulo") or "").strip()
        if not titulo:
            raise forms.ValidationError("Este campo es obligatorio.")
        return titulo


class PanelCotizacionCreateForm(PanelCotizacionBaseForm):
    pass


class PanelCotizacionInlineCreateForm(PanelCotizacionBaseForm):
    archivos = MultipleFileField(required=False)
    enlaces = forms.CharField(required=False, widget=forms.HiddenInput())

    class Meta(PanelCotizacionBaseForm.Meta):
        fields = (
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
        )
        widgets = {
            "titulo": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm rounded",
                    "placeholder": "Titulo de la cotizacion",
                }
            ),
            "descripcion": forms.Textarea(
                attrs={
                    "class": "form-control form-control-sm rounded",
                    "rows": 2,
                    "placeholder": "Describe el alcance o contexto...",
                }
            ),
            "prioridad": forms.Select(
                attrs={"class": "form-select form-select-sm rounded"}
            ),
            "fecha_vencimiento": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm rounded",
                }
            ),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].queryset = (
            Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO)
            .only("id", "nombre")
            .order_by("nombre")
        )
        self.fields["cliente"].widget.attrs.update(
            {"class": "form-select form-select-sm rounded"}
        )
        self.fields["asignados"].widget.attrs.update(
            {"class": "form-select form-select-sm rounded garantia-asignados-select"}
        )
        self.fields["etiquetas"].widget.attrs.update(
            {
                "class": "form-select form-select-sm rounded",
                "data-panel-cotizacion-tags-select": "1",
            }
        )
        self.fields["archivos"].widget.attrs.update(
            {
                "class": "form-control form-control-sm",
                "accept": ",".join(sorted(PANEL_ARCHIVO_EXTENSIONS)),
            }
        )
        self.link_rows = self._build_link_rows()

    def _build_link_rows(self):
        if not self.is_bound:
            return [{"titulo": "", "url": ""}]
        titulos = self.data.getlist("enlace_titulo")
        urls = self.data.getlist("enlace_url")
        total = max(len(titulos), len(urls), 1)
        return [
            {
                "titulo": titulos[index] if index < len(titulos) else "",
                "url": urls[index] if index < len(urls) else "",
            }
            for index in range(total)
        ]

    def clean_archivos(self):
        return self.cleaned_data.get("archivos") or []

    def clean(self):
        cleaned_data = super().clean()
        titulos = self.data.getlist("enlace_titulo")
        urls = self.data.getlist("enlace_url")
        total = max(len(titulos), len(urls))
        validator = URLValidator()
        enlaces = []
        errores = []

        for index in range(total):
            titulo = (titulos[index] if index < len(titulos) else "").strip()
            url = (urls[index] if index < len(urls) else "").strip()
            if not titulo and not url:
                continue
            if not url:
                errores.append(f"Enlace {index + 1}: captura una URL.")
                continue
            try:
                validator(url)
            except forms.ValidationError:
                errores.append(f"Enlace {index + 1}: captura una URL valida.")
                continue
            enlaces.append({"titulo": titulo, "url": url})

        if errores:
            self.add_error("enlaces", errores)

        cleaned_data["enlaces_payload"] = enlaces
        return cleaned_data


class PanelCotizacionInlineTituloForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("titulo",)
        widgets = {
            "titulo": forms.TextInput(
                attrs={"class": "form-control form-control-sm rounded"}
            )
        }


class PanelCotizacionInlinePrioridadForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("prioridad",)
        widgets = {
            "prioridad": forms.Select(
                attrs={"class": "form-select form-select-sm rounded"}
            )
        }


class PanelCotizacionInlineVencimientoForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacion
        fields = ("fecha_vencimiento",)
        widgets = {
            "fecha_vencimiento": forms.DateInput(
                attrs={
                    "type": "date",
                    "class": "form-control form-control-sm rounded",
                }
            )
        }


class PanelCotizacionInlineClienteForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by(
            "nombre"
        ),
        required=False,
        empty_label="Sin cliente",
        widget=forms.Select(attrs={"class": "form-select form-select-sm rounded"}),
        label="Cliente",
    )

    class Meta:
        model = PanelCotizacion
        fields = ("cliente",)

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return normalizar_texto_cliente(cliente.nombre if cliente else "")


class PanelCotizacionInlineAsignadosForm(forms.ModelForm):
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select form-select-sm rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = PanelCotizacion
        fields = ("asignados",)


class PanelCotizacionArchivosForm(forms.Form):
    archivos = MultipleFileField(required=False)


class PanelCotizacionEnlaceForm(forms.Form):
    titulo = forms.CharField(
        required=False,
        max_length=255,
        widget=forms.TextInput(
            attrs={"class": "form-control rounded", "placeholder": "Ej. Propuesta"}
        ),
    )
    url = forms.URLField(
        required=False,
        max_length=1000,
        widget=forms.URLInput(
            attrs={"class": "form-control rounded", "placeholder": "https://..."}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for name in ["titulo", "url"]:
            if name in self.fields:
                self.fields[name].required = False


class PanelCotizacionUpdateForm(forms.ModelForm):
    cliente = ClienteChoiceField(
        queryset=Cliente.objects.filter(estado=Cliente.ESTADO_ACTIVO).order_by(
            "nombre"
        ),
        required=False,
        empty_label="Seleccione un cliente",
        widget=forms.Select(attrs={"class": "form-select rounded"}),
        label="Cliente",
    )
    asignados = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "data-garantia-tags-select": "1",
            }
        ),
    )
    etiquetas = EtiquetaChoiceField(
        queryset=PanelCotizacionEtiqueta.objects.all().order_by("nombre", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded",
                "data-panel-cotizacion-tags-select": "1",
            }
        ),
    )

    class Meta:
        model = PanelCotizacion
        fields = (
            "titulo",
            "descripcion",
            "cliente",
            "prioridad",
            "fecha_vencimiento",
            "asignados",
            "etiquetas",
        )
        widgets = {
            "titulo": forms.TextInput(attrs={"class": "form-control rounded"}),
            "descripcion": forms.Textarea(
                attrs={"class": "form-control rounded", "rows": 4}
            ),
            "prioridad": forms.Select(attrs={"class": "form-select rounded"}),
            "fecha_vencimiento": forms.DateInput(
                attrs={"type": "date", "class": "form-control rounded"}
            ),
        }
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field_name in list(self.fields.keys()):
            self.fields[field_name].required = False

    def clean_cliente(self):
        cliente = self.cleaned_data.get("cliente")
        return normalizar_texto_cliente(cliente.nombre if cliente else "")


class PanelCotizacionComentarioForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacionComentario
        fields = ("texto",)
        widgets = {
            "texto": forms.Textarea(
                attrs={"rows": 2, "placeholder": "Escribe un comentario..."}
            )
        }


class PanelCotizacionElementoAccionForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacionElementoAccion
        fields = ("texto",)
        widgets = {
            "texto": forms.TextInput(
                attrs={
                    "class": "form-control form-control-sm",
                    "placeholder": "Agregar elemento",
                    "maxlength": 255,
                }
            )
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["texto"].required = False

    def clean_texto(self):
        texto = (self.cleaned_data.get("texto") or "").strip()
        if not texto:
            raise forms.ValidationError("Escribe un elemento de accion.")
        return texto


class PanelCotizacionUserFilterForm(forms.Form):
    usuario = FirstNameUserMultipleChoiceField(
        queryset=User.objects.all().order_by("first_name", "id"),
        required=False,
        widget=forms.SelectMultiple(
            attrs={
                "class": "form-select rounded garantia-asignados-select",
                "id": "panelCotizacionesUserFilter",
                "data-garantia-tags-select": "1",
            }
        ),
    )


class PanelCotizacionColumnaCreateForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacionColumna
        fields = ("nombre",)
        widgets = {
            "nombre": forms.TextInput(
                attrs={
                    "class": "form-control",
                    "placeholder": "Nombre de la columna",
                }
            )
        }

    def clean_nombre(self):
        nombre = (self.cleaned_data.get("nombre") or "").strip()
        if not nombre:
            raise forms.ValidationError("Este campo es obligatorio.")
        return nombre


class PanelCotizacionColumnaUpdateForm(PanelCotizacionColumnaCreateForm):
    pass

class PanelCotizacionEtiquetaAssignForm(forms.Form):
    etiquetas = EtiquetaChoiceField(
        queryset=PanelCotizacionEtiqueta.objects.all().order_by("nombre"),
        required=True,
        widget=forms.SelectMultiple(attrs={"class": "form-select"}),
    )

class PanelCotizacionEtiquetaCreateForm(forms.ModelForm):
    class Meta:
        model = PanelCotizacionEtiqueta
        fields = ["nombre", "color"]
