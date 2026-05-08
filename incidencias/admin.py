from django.contrib import admin

from .models import Incidencia


@admin.register(Incidencia)
class IncidenciaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "titulo", "responsable", "estado", "prioridad", "fecha_creacion")
    list_filter = ("estado", "prioridad", "responsable")
    search_fields = ("codigo", "titulo", "descripcion", "responsable__username")

# Register your models here.
