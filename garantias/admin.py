from django.contrib import admin

from .models import Garantia, GarantiaColumna, GarantiaComentario


class GarantiaComentarioInline(admin.TabularInline):
    model = GarantiaComentario
    extra = 0


@admin.register(Garantia)
class GarantiaAdmin(admin.ModelAdmin):
    list_display = (
        "titulo",
        "cliente",
        "estado",
        "columna",
        "prioridad",
        "fecha_creacion",
        "fecha_vencimiento",
    )
    list_filter = ("estado", "columna", "prioridad")
    search_fields = ("titulo", "descripcion", "cliente__nombre")
    filter_horizontal = ("asignados", "etiquetas")
    inlines = [GarantiaComentarioInline]


@admin.register(GarantiaColumna)
class GarantiaColumnaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden", "activa", "creada_por")
    list_filter = ("activa",)
    search_fields = ("nombre", "codigo")
    ordering = ("orden", "id")
