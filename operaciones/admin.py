from django.contrib import admin

from .models import (
    Operacion,
    OperacionArchivo,
    OperacionColumna,
    OperacionComentario,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)


@admin.register(OperacionColumna)
class OperacionColumnaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "orden", "activa", "creada_por")
    list_filter = ("activa",)
    search_fields = ("nombre", "codigo")
    readonly_fields = ("fecha_creacion", "fecha_actualizacion")


@admin.register(Operacion)
class OperacionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "cliente", "estado", "columna", "prioridad", "creado_por", "fecha_creacion")
    list_filter = ("estado", "columna", "prioridad", "fecha_creacion")
    search_fields = ("titulo", "descripcion", "cliente__nombre")
    readonly_fields = ("fecha_creacion",)
    filter_horizontal = ("asignados", "etiquetas", "opciones")


@admin.register(OperacionEtiqueta)
class OperacionEtiquetaAdmin(admin.ModelAdmin):
    list_display = ("nombre", "color", "fecha_creacion")
    search_fields = ("nombre",)
    readonly_fields = ("fecha_creacion",)


@admin.register(OperacionOpcion)
class OperacionOpcionAdmin(admin.ModelAdmin):
    list_display = ("nombre", "fecha_creacion")
    search_fields = ("nombre",)
    readonly_fields = ("fecha_creacion",)


@admin.register(OperacionComentario)
class OperacionComentarioAdmin(admin.ModelAdmin):
    list_display = ("operacion", "usuario", "fecha")
    list_filter = ("fecha",)
    search_fields = ("comentario",)
    readonly_fields = ("fecha",)


@admin.register(OperacionArchivo)
class OperacionArchivoAdmin(admin.ModelAdmin):
    list_display = ("operacion", "archivo", "subido_por", "fecha")
    list_filter = ("fecha",)
    readonly_fields = ("fecha",)


@admin.register(OperacionEnlace)
class OperacionEnlaceAdmin(admin.ModelAdmin):
    list_display = ("operacion", "titulo", "url", "creado_por", "fecha")
    list_filter = ("fecha",)
    readonly_fields = ("fecha",)
