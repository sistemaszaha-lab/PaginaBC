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

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        if obj and obj.codigo == "FACTURA_FLETES_1":
            return (*fields, "codigo")
        return fields


@admin.register(Operacion)
class OperacionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "cliente", "estado", "columna", "prioridad", "creado_por", "fecha_creacion")
    list_filter = ("estado", "columna", "prioridad", "fecha_creacion")
    search_fields = ("titulo", "descripcion", "cliente__nombre")
    readonly_fields = ("fecha_creacion", "estado")
    filter_horizontal = ("asignados", "etiquetas", "opciones")

    def save_model(self, request, obj, form, change):
        anterior = (Operacion.objects.filter(pk=obj.pk)
                    .values_list("columna_id", flat=True).first()) if change else None
        obj._entrada_automatizacion = not change or anterior != obj.columna_id
        if obj.columna_id:
            obj.estado = obj.columna.codigo
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        from cuenta_gastos.services import crear_copia_flete_desde_operacion

        super().save_related(request, form, formsets, change)
        if getattr(form.instance, "_entrada_automatizacion", False):
            crear_copia_flete_desde_operacion(form.instance, creado_por=request.user)


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
