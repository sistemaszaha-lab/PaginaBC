from django.contrib import admin

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ("nombre", "empresa", "correo", "cuentas_por_cobrar", "telefono", "rfc", "estado", "fecha_alta")
    search_fields = ("nombre", "empresa", "correo", "cuentas_por_cobrar", "telefono", "direccion", "rfc")
    list_filter = ("estado", "fecha_alta")
