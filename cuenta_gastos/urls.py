from django.urls import path
from . import views

app_name = "cuenta_gastos"

urlpatterns = [

    path(
        "",
        views.panel_cuenta_gastos,
        name="panel_cuenta_gastos"
    ),

    path(
        "crear/",
        views.crear_cuenta_gastos,
        name="crear_cuenta_gastos"
    ),

    path(
        "detalle/<int:pk>/",
        views.detalle_cuenta_gastos,
        name="detalle_cuenta_gastos"
    ),

    path(
        "<int:pk>/mover/",
        views.mover_cuenta_gastos,
        name="mover_cuenta_gastos"
    ),

    path(
        "editar/<int:pk>/",
        views.editar_cuenta,
        name="editar_cuenta"
    ),
    path(
        "opcion/crear/",
        views.crear_opcion,
        name="crear_opcion"
    ),
    path(
        "etiqueta/crear/",
        views.crear_etiqueta,
        name="crear_etiqueta"
    ),
    path(
        "etiqueta/<int:etiqueta_id>/eliminar/",
        views.eliminar_etiqueta,
        name="eliminar_etiqueta"
    ),
    path(
        "<int:pk>/comentario/",
        views.agregar_comentario,
        name="agregar_comentario"
    ),
    path(
        "<int:pk>/archivo/",
        views.agregar_archivo,
        name="agregar_archivo"
    ),
    path(
        "<int:pk>/enlace/",
        views.agregar_enlace,
        name="agregar_enlace"
    ),
    path(
        "<int:pk>/eliminar/",
        views.eliminar_cuenta,
        name="eliminar_cuenta"
    ),
    path(
        "etiqueta/<int:id>/eliminar/",
        views.eliminar_etiqueta,
        name="eliminar_etiqueta"
    ),
]
