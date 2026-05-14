from django.urls import path

from . import views

app_name = "garantias"

urlpatterns = [
    path("", views.panel_garantias, name="panel_garantias"),
    path("nueva/", views.crear_garantia, name="crear_garantia"),
    path("actualizar-estado/", views.actualizar_estado_garantia, name="actualizar_estado_garantia"),
    path("<int:pk>/detalle/", views.detalle_garantia_parcial, name="detalle_garantia_parcial"),
    path("<int:pk>/", views.detalle_garantia, name="detalle_garantia"),
    path("<int:pk>/editar/", views.editar_garantia, name="editar_garantia"),
    path("<int:pk>/eliminar/", views.eliminar_garantia, name="eliminar_garantia"),
    path("<int:pk>/estado/", views.cambiar_estado_garantia, name="cambiar_estado_garantia"),
    path("<int:pk>/comentario/", views.agregar_comentario, name="agregar_comentario"),
    path("<int:pk>/archivos/<int:archivo_id>/descargar/", views.descargar_archivo, name="descargar_archivo"),
    path("<int:pk>/archivos/<int:archivo_id>/eliminar/", views.eliminar_archivo, name="eliminar_archivo"),
    path("<int:pk>/enlaces/<int:enlace_id>/eliminar/", views.eliminar_enlace, name="eliminar_enlace"),
]
