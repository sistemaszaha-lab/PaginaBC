from django.urls import path

from . import views

app_name = "garantias"

urlpatterns = [
    path("", views.panel_garantias, name="panel_garantias"),
    path("tablero/", views.tablero_partial, name="tablero_partial"),
    path(
        "columna/<str:codigo>/tarjetas/",
        views.tarjetas_columna,
        name="tarjetas_columna",
    ),
    path("columnas/crear/", views.columna_crear, name="columna_crear"),
    path("columnas/reordenar/", views.columna_reordenar, name="columna_reordenar"),
    path("columnas/<int:pk>/editar/", views.columna_editar, name="columna_editar"),
    path("columnas/<int:pk>/eliminar/", views.columna_eliminar, name="columna_eliminar"),
    path("columnas/<int:columna_id>/pegar/", views.tarjeta_pegar, name="tarjeta_pegar"),
    path("nueva/", views.crear_garantia, name="crear_garantia"),
    path("crear-inline/formulario/", views.formulario_garantia_inline, name="formulario_garantia_inline"),
    path("crear-inline/", views.crear_garantia_inline, name="crear_garantia_inline"),
    path("actualizar-estado/", views.actualizar_estado_garantia, name="actualizar_estado_garantia"),
    path("<int:pk>/actualizar-inline/", views.actualizar_garantia_inline, name="actualizar_garantia_inline"),
    path("<int:pk>/detalle/", views.detalle_garantia_parcial, name="detalle_garantia_parcial"),
    path("<int:pk>/", views.detalle_garantia, name="detalle_garantia"),
    path("<int:pk>/editar/", views.editar_garantia, name="editar_garantia"),
    path("<int:pk>/eliminar/", views.eliminar_garantia, name="eliminar_garantia"),
    path("<int:pk>/estado/", views.cambiar_estado_garantia, name="cambiar_estado_garantia"),
    path("<int:pk>/comentario/", views.agregar_comentario, name="agregar_comentario"),
    path("<int:pk>/archivos/", views.agregar_archivos, name="agregar_archivos"),
    path("<int:pk>/archivos/<int:archivo_id>/descargar/", views.descargar_archivo, name="descargar_archivo"),
    path("<int:pk>/archivos/<int:archivo_id>/eliminar/", views.eliminar_archivo, name="eliminar_archivo"),
    path("<int:pk>/enlaces/", views.agregar_enlace, name="agregar_enlace"),
    path("<int:pk>/enlaces/<int:enlace_id>/eliminar/", views.eliminar_enlace, name="eliminar_enlace"),
]
