from django.contrib import admin
from .models import Solicitud


@admin.register(Solicitud)
class SolicitudAdmin(admin.ModelAdmin):
    list_display = (
        "sg",
        "anio",
        "cliente",
        "tipo",
        "fecha_recepcion",
        "estado_aereo",
        "estado_maritimo",
        "estado_terrestre",
    )

    list_filter = (
        "anio",
        "tipo",
        "ejecutivo",
        "estado_aereo",
        "estado_maritimo",
        "estado_terrestre",
    )

    search_fields = ("sg", "cliente")

    ordering = ("-anio", "-fecha_recepcion")

