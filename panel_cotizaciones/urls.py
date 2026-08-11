from django.urls import path

from . import views

app_name = "panel_cotizaciones"

urlpatterns = [
    path("", views.panel_cotizaciones, name="panel_cotizaciones"),
    path("crear/", views.crear_panel_cotizacion, name="crear"),
    path("columnas/crear/", views.columna_crear, name="columna_crear"),
    path("columnas/reordenar/", views.columna_reordenar, name="columna_reordenar"),
    path("columnas/<int:pk>/editar/", views.columna_editar, name="columna_editar"),
    path("columnas/<int:pk>/eliminar/", views.columna_eliminar, name="columna_eliminar"),
    path("columnas/<int:columna_id>/pegar/", views.columna_pegar, name="columna_pegar"),
    path("crear-inline/formulario/", views.formulario_inline, name="formulario_inline"),
    path("crear-inline/", views.crear_inline, name="crear_inline"),
    path("<int:pk>/inline-editor/", views.inline_editor, name="inline_editor"),
    path("<int:pk>/inline-update/", views.inline_update, name="inline_update"),
    path("tablero/", views.tablero_partial, name="tablero_partial"),
    path(
        "columna/<str:codigo>/tarjetas/",
        views.tarjetas_columna,
        name="tarjetas_columna",
    ),
    path("estado/update/", views.estado_update, name="estado_update"),
    path("<int:pk>/modal/", views.detalle_modal, name="detalle_modal"),
    path("<int:pk>/modal/update/", views.detalle_modal_update, name="detalle_modal_update"),
    path("<int:pk>/archivos/", views.archivo_agregar, name="archivo_agregar"),
    path("<int:pk>/archivos/<int:archivo_id>/eliminar/", views.archivo_eliminar, name="archivo_eliminar"),
    path("<int:pk>/enlaces/", views.enlace_agregar, name="enlace_agregar"),
    path("<int:pk>/enlaces/<int:enlace_id>/eliminar/", views.enlace_eliminar, name="enlace_eliminar"),
    path("<int:pk>/eliminar/", views.eliminar_panel_cotizacion, name="eliminar"),
    path("<int:pk>/comentario/", views.comentario_create, name="comentario_create"),
    path("<int:pk>/checklist/", views.checklist_item_create, name="checklist_item_create"),
    path("<int:pk>/checklist/<int:item_id>/update/", views.checklist_item_update, name="checklist_item_update"),
    path("<int:pk>/checklist/<int:item_id>/toggle/", views.checklist_item_toggle, name="checklist_item_toggle"),
    path("<int:pk>/checklist/<int:item_id>/delete/", views.checklist_item_delete, name="checklist_item_delete"),
    path("<int:panel_id>/etiquetas/agregar/", views.agregar_etiqueta_cotizacion, name="agregar_etiqueta_cotizacion"),
    path("<int:panel_id>/etiquetas/crear/", views.crear_etiqueta_cotizacion, name="crear_etiqueta_cotizacion"),
    path("<int:panel_id>/etiquetas/<int:etiqueta_id>/quitar/", views.quitar_etiqueta_cotizacion, name="quitar_etiqueta_cotizacion"),
]
