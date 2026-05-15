from django.contrib import admin

from .models import PanelCotizacion, PanelCotizacionComentario


class PanelCotizacionComentarioInline(admin.TabularInline):
    model = PanelCotizacionComentario
    extra = 0


@admin.register(PanelCotizacion)
class PanelCotizacionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "cliente", "prioridad", "estado", "fecha_creacion", "fecha_vencimiento")
    list_filter = ("estado", "prioridad")
    search_fields = ("titulo", "cliente", "descripcion")
    inlines = [PanelCotizacionComentarioInline]
    filter_horizontal = ("asignados",)


@admin.register(PanelCotizacionComentario)
class PanelCotizacionComentarioAdmin(admin.ModelAdmin):
    list_display = ("cotizacion", "creado_por", "fecha_creacion")
    search_fields = ("texto", "cotizacion__titulo", "cotizacion__cliente")

