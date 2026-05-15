from django.urls import path

from . import views

app_name = "panel_cotizaciones"

urlpatterns = [
    path("", views.panel_cotizaciones, name="panel_cotizaciones"),
    path("crear/", views.crear_panel_cotizacion, name="crear"),
    path("tablero/", views.tablero_partial, name="tablero_partial"),
    path("estado/update/", views.estado_update, name="estado_update"),
    path("<int:pk>/modal/", views.detalle_modal, name="detalle_modal"),
    path("<int:pk>/modal/update/", views.detalle_modal_update, name="detalle_modal_update"),
    path("<int:pk>/eliminar/", views.eliminar_panel_cotizacion, name="eliminar"),
    path("<int:pk>/comentario/", views.comentario_create, name="comentario_create"),
]
