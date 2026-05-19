from django.urls import path

from . import views

app_name = "operaciones"

urlpatterns = [
    path("", views.panel_operaciones, name="panel_operaciones"),
    path("crear/", views.crear_operacion, name="crear_operacion"),
    path("opcion/crear/", views.crear_opcion, name="crear_opcion"),
    path("etiqueta/crear/", views.crear_etiqueta, name="crear_etiqueta"),
    path("etiqueta/<int:etiqueta_id>/editar/", views.editar_etiqueta, name="editar_etiqueta"),
    path("etiqueta/<int:etiqueta_id>/eliminar/", views.eliminar_etiqueta, name="eliminar_etiqueta"),
    path("detalle/<int:operacion_id>/", views.detalle_operacion, name="detalle_operacion"),
    path("<int:operacion_id>/modal/", views.detalle_operacion_modal, name="detalle_operacion_modal"),
    path("<int:operacion_id>/editar/", views.editar_operacion, name="editar_operacion"),
    path("<int:operacion_id>/comentario/", views.agregar_comentario, name="agregar_comentario"),
    path("<int:operacion_id>/archivo/", views.agregar_archivo, name="agregar_archivo"),
    path("<int:operacion_id>/mover/", views.mover_operacion, name="mover_operacion"),
    path("<int:operacion_id>/eliminar/", views.eliminar_operacion, name="eliminar_operacion"),
]
