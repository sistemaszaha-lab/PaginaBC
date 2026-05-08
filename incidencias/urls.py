from django.urls import path

from . import views

app_name = "incidencias"

urlpatterns = [
    path("", views.panel_incidencias, name="panel_incidencias"),
    path("crear/", views.crear_incidencia, name="crear_incidencia"),
    path("<int:pk>/editar/", views.editar_incidencia, name="editar_incidencia"),
    path("<int:pk>/eliminar/", views.eliminar_incidencia, name="eliminar_incidencia"),
]
