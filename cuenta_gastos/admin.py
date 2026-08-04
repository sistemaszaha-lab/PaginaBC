from django.contrib import admin

from .models import (
    CuentaGastos,
    CuentaGastosArchivo,
    CuentaGastosColumna,
    CuentaGastosComentario,
    CuentaGastosEnlace,
    CuentaGastosEtiqueta,
    CuentaGastosOpcion,
    DocumentoRepositorio,
)


@admin.register(CuentaGastosColumna)
class CuentaGastosColumnaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden", "activa", "creada_por")
    list_filter = ("activa",)
    search_fields = ("nombre", "codigo")
    readonly_fields = ("fecha_creacion", "fecha_actualizacion")


@admin.register(CuentaGastos)
class CuentaGastosAdmin(admin.ModelAdmin):
    list_display = ("titulo", "cliente", "estado", "columna", "prioridad", "creado_por", "fecha_creacion")
    list_filter = ("estado", "columna", "prioridad", "fecha_creacion")
    search_fields = ("titulo", "descripcion", "cliente__nombre")
    readonly_fields = ("fecha_creacion",)
    filter_horizontal = ("asignados", "etiquetas", "opciones")


@admin.register(CuentaGastosEtiqueta)
class CuentaGastosEtiquetaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "color", "fecha_creacion")
    search_fields = ("nombre",)
    readonly_fields = ("fecha_creacion",)


@admin.register(CuentaGastosOpcion)
class CuentaGastosOpcionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha_creacion")
    search_fields = ("nombre",)
    readonly_fields = ("fecha_creacion",)


@admin.register(CuentaGastosComentario)
class CuentaGastosComentarioAdmin(admin.ModelAdmin):
    list_display = ("cuenta_gasto", "usuario", "fecha")
    list_filter = ("fecha",)
    search_fields = ("comentario",)
    readonly_fields = ("fecha",)


@admin.register(CuentaGastosArchivo)
class CuentaGastosArchivoAdmin(admin.ModelAdmin):
    list_display = ("cuenta_gasto", "archivo", "subido_por", "fecha")
    list_filter = ("fecha",)
    readonly_fields = ("fecha",)


@admin.register(CuentaGastosEnlace)
class CuentaGastosEnlaceAdmin(admin.ModelAdmin):
    list_display = ("cuenta_gasto", "titulo", "url", "creado_por", "fecha")
    list_filter = ("fecha",)
    readonly_fields = ("fecha",)


@admin.register(DocumentoRepositorio)
class DocumentoRepositorioAdmin(admin.ModelAdmin):
    list_display = ("nombre_original", "subido_por", "fecha_subida")
    list_filter = ("fecha_subida",)
    readonly_fields = ("fecha_subida",)
