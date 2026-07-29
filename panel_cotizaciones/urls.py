from django.urls import path

from . import views

app_name = "panel_cotizaciones"

urlpatterns = [
    path("", views.panel_cotizaciones, name="panel_cotizaciones"),
    path("crear/", views.crear_panel_cotizacion, name="crear"),
    path("crear-inline/formulario/", views.formulario_inline, name="formulario_inline"),
    path("crear-inline/", views.crear_inline, name="crear_inline"),
    path("<int:pk>/inline-editor/", views.inline_editor, name="inline_editor"),
    path("<int:pk>/inline-update/", views.inline_update, name="inline_update"),
    path("tablero/", views.tablero_partial, name="tablero_partial"),
    path(
        "columna/<str:estado>/tarjetas/",
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
]
