from django.urls import path

from . import views

urlpatterns = [
    path("", views.cliente_lista, name="cliente_lista"),
    path("nuevo/", views.cliente_crear, name="cliente_crear"),
    path("<int:pk>/editar/", views.cliente_editar, name="cliente_editar"),
    path("<int:pk>/eliminar/", views.cliente_eliminar, name="cliente_eliminar"),
]
