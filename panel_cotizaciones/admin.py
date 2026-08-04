from django.contrib import admin

from .models import (
    PanelCotizacion,
    PanelCotizacionColumna,
    PanelCotizacionComentario,
)


class PanelCotizacionComentarioInline(admin.TabularInline):
    model = PanelCotizacionComentario
    extra = 0


@admin.register(PanelCotizacion)
class PanelCotizacionAdmin(admin.ModelAdmin):
    list_display = (
        "titulo",
        "cliente",
        "prioridad",
        "estado",
        "columna",
        "fecha_creacion",
        "fecha_vencimiento",
    )
    list_filter = ("estado", "columna", "prioridad")
    search_fields = ("titulo", "cliente", "descripcion")
    inlines = [PanelCotizacionComentarioInline]
    filter_horizontal = ("asignados",)


@admin.register(PanelCotizacionColumna)
class PanelCotizacionColumnaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden", "activa", "creada_por")
    list_filter = ("activa",)
    search_fields = ("nombre", "codigo")
    ordering = ("orden", "id")


@admin.register(PanelCotizacionComentario)
class PanelCotizacionComentarioAdmin(admin.ModelAdmin):
    list_display = ("cotizacion", "creado_por", "fecha_creacion")
    search_fields = ("texto", "cotizacion__titulo", "cotizacion__cliente")
