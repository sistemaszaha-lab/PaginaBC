from django.urls import path

from . import views

app_name = "operaciones"

urlpatterns = [
    path("", views.panel_operaciones, name="panel_operaciones"),
    path(
        "columna/<str:estado>/tarjetas/",
        views.tarjetas_columna,
        name="tarjetas_columna",
    ),
    path("nueva/", views.crear_operacion, name="crear_operacion"),
    path("referencias/<int:pk>/enviar-a-operaciones/", views.enviar_referencia_a_operaciones, name="enviar_referencia_a_operaciones"),
    path("nueva/inline/formulario/", views.formulario_operacion_inline, name="formulario_operacion_inline"),
    path("nueva/inline/", views.crear_operacion_inline, name="crear_operacion_inline"),
    path("opcion/crear/", views.crear_opcion, name="crear_opcion"),
    path("etiqueta/crear/", views.crear_etiqueta, name="crear_etiqueta"),
    path("etiqueta/<int:etiqueta_id>/editar/", views.editar_etiqueta, name="editar_etiqueta"),
    path("etiqueta/<int:etiqueta_id>/eliminar/", views.eliminar_etiqueta, name="eliminar_etiqueta"),
    path("detalle/<int:operacion_id>/", views.detalle_operacion, name="detalle_operacion"),
    path("<int:operacion_id>/modal/", views.detalle_operacion_modal, name="detalle_operacion_modal"),
    path("<int:operacion_id>/editar/", views.editar_operacion, name="editar_operacion"),
    path("<int:operacion_id>/edicion-rapida/", views.editar_operacion_rapida, name="editar_operacion_rapida"),
    path("<int:operacion_id>/comentario/", views.agregar_comentario, name="agregar_comentario"),
    path("<int:operacion_id>/archivo/", views.agregar_archivo, name="agregar_archivo"),
    path("<int:operacion_id>/archivo/eliminar/", views.eliminar_archivo, name="eliminar_archivo"),
    path("<int:operacion_id>/enlace/", views.agregar_enlace, name="agregar_enlace"),
    path("<int:operacion_id>/enlace/eliminar/", views.eliminar_enlace, name="eliminar_enlace"),
    path("<int:operacion_id>/etiqueta/agregar/", views.agregar_etiqueta_operacion, name="agregar_etiqueta_operacion"),
    path("<int:operacion_id>/etiqueta/crear/", views.crear_etiqueta_operacion, name="crear_etiqueta_operacion"),
    path("<int:operacion_id>/etiqueta/<int:etiqueta_id>/quitar/", views.quitar_etiqueta_operacion, name="quitar_etiqueta_operacion"),
    path("<int:operacion_id>/opciones/actualizar/", views.actualizar_opciones_operacion, name="actualizar_opciones_operacion"),
    path("<int:operacion_id>/opcion/crear/", views.crear_opcion_operacion, name="crear_opcion_operacion"),
    path("<int:operacion_id>/opcion/<int:opcion_id>/quitar/", views.quitar_opcion_operacion, name="quitar_opcion_operacion"),
    path("<int:operacion_id>/mover/", views.mover_operacion, name="mover_operacion"),
    path("<int:operacion_id>/eliminar/", views.eliminar_operacion, name="eliminar_operacion"),
]
