from django.conf import settings
from django.conf.urls.static import static
from django.contrib.auth import views as auth_views
from django.contrib.staticfiles.urls import staticfiles_urlpatterns
from django.urls import include, path
from . import trash_views

urlpatterns = [
    path(
        "login/",
        auth_views.LoginView.as_view(
            template_name="login.html",
            redirect_authenticated_user=True,
        ),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(next_page="/login/"), name="logout"),
    path("clientes/", include("clientes.urls")),
    path("incidencias/", include("incidencias.urls")),
    path("papelera/", trash_views.papelera, name="papelera"),
    path(
        "papelera/restaurar-seleccion/",
        trash_views.restaurar_seleccion,
        name="papelera_restaurar_seleccion",
    ),
    path(
        "papelera/eliminar-seleccion/",
        trash_views.eliminar_seleccion,
        name="papelera_eliminar_seleccion",
    ),
    path(
        "papelera/<str:tipo>/<int:pk>/restaurar/",
        trash_views.restaurar_elemento,
        name="papelera_restaurar",
    ),
    path(
        "papelera/<str:tipo>/<int:pk>/eliminar-definitivamente/",
        trash_views.eliminar_elemento_definitivamente,
        name="papelera_eliminar_definitivamente",
    ),
    path("garantias/", include("garantias.urls")),
    path("panel-cotizaciones/", include("panel_cotizaciones.urls")),
    path("operaciones/", include("operaciones.urls")),
    path("", include("solicitudes.urls")),
    path("cuenta-gastos/",include("cuenta_gastos.urls")),
]

if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()
    urlpatterns += static(
        settings.MEDIA_URL,
        document_root=settings.MEDIA_ROOT,
    )
