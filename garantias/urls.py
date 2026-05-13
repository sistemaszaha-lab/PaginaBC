from django.urls import path

from . import views

app_name = "garantias"

urlpatterns = [
    path("", views.panel_garantias, name="panel_garantias"),
    path("nueva/", views.crear_garantia, name="crear_garantia"),
    path("<int:pk>/", views.detalle_garantia, name="detalle_garantia"),
    path("<int:pk>/editar/", views.editar_garantia, name="editar_garantia"),
    path("<int:pk>/eliminar/", views.eliminar_garantia, name="eliminar_garantia"),
    path("<int:pk>/estado/", views.cambiar_estado_garantia, name="cambiar_estado_garantia"),
    path("<int:pk>/comentario/", views.agregar_comentario, name="agregar_comentario"),
]
