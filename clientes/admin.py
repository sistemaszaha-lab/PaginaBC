from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "telefono", "correo", "rfc", "estado", "fecha_alta")
    search_fields = ("nombre", "empresa", "telefono", "correo", "direccion", "rfc")
    list_filter = ("estado", "fecha_alta")
