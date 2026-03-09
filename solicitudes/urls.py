from django.urls import path

from . import views

urlpatterns = [
    path("", views.inicio, name="inicio"),
    path("solicitudes/", views.lista_solicitudes, name="lista_solicitudes"),
    path("solicitudes/importar-csv/", views.importar_solicitudes_csv, name="importar_solicitudes_csv"),
    path("solicitudes/exportar-excel/", views.exportar_solicitudes_excel, name="exportar_solicitudes_excel"),
    path("solicitudes/nueva/", views.crear_solicitud, name="crear_solicitud"),
    path("solicitudes/editar/<int:pk>/", views.editar_solicitud, name="editar_solicitud"),
    path("solicitudes/eliminar/<int:pk>/", views.eliminar_solicitud, name="eliminar_solicitud"),
    path("cambiar-estado/<int:pk>/<str:tipo>/", views.cambiar_estado, name="cambiar_estado"),
    path("cambiar-ejecutivo/<int:pk>/", views.cambiar_ejecutivo, name="cambiar_ejecutivo"),
    path("usuarios/", views.lista_usuarios, name="lista_usuarios"),
    path("usuarios/nuevo/", views.crear_usuario, name="crear_usuario"),
    path("usuarios/editar/<int:pk>/", views.editar_usuario, name="editar_usuario"),
    path("usuarios/eliminar/<int:pk>/", views.eliminar_usuario, name="eliminar_usuario"),
    path("cotizaciones/", views.lista_cotizaciones, name="lista_cotizaciones"),
    path("cotizaciones/importar-csv/", views.importar_cotizaciones_csv, name="importar_cotizaciones_csv"),
    path("cotizaciones/exportar-excel/", views.exportar_cotizaciones_excel, name="exportar_cotizaciones_excel"),
    path("cotizaciones/nueva/", views.crear_cotizacion, name="crear_cotizacion"),
    path("cotizaciones/editar/<int:pk>/", views.editar_cotizacion, name="editar_cotizacion"),
    path("cotizaciones/eliminar/<int:pk>/", views.eliminar_cotizacion, name="eliminar_cotizacion"),
    path("cotizaciones/cambiar-ejecutivo/<int:pk>/", views.cambiar_ejecutivo_cotizacion, name="cambiar_ejecutivo_cotizacion"),
    path("referencias/", views.lista_referencias, name="lista_referencias"),
    path("referencias/importar-csv/", views.importar_referencias_csv, name="importar_referencias_csv"),
    path("referencias/exportar-excel/", views.exportar_referencias_excel, name="exportar_referencias_excel"),
    path("referencias/nueva/", views.crear_referencia, name="crear_referencia"),
    path("referencias/editar/<int:pk>/", views.editar_referencia, name="editar_referencia"),
    path("referencias/eliminar/<int:pk>/", views.eliminar_referencia, name="eliminar_referencia"),
    path("referencias/cambiar-ejecutivo/<int:pk>/", views.cambiar_ejecutivo_referencia, name="cambiar_ejecutivo_referencia"),
]

