from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from operaciones.models import Operacion, OperacionComentario
from .models import CuentaGastos, CuentaGastosComentario
from .services import crear_cuenta_gastos_desde_operacion_si_corresponde
from .views import _comentarios_queryset, _cuenta_queryset


@override_settings(STORAGES={
    "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
})
class ComentariosOperacionOrigenTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="autor-origen", first_name="Autor original")
        self.operacion = Operacion.objects.create(
            titulo="Origen comentarios", creado_por=self.usuario,
            estado=Operacion.Estado.SOLICITUD_CUENTA_GASTOS,
        )
        self.original = OperacionComentario.objects.create(
            operacion=self.operacion, usuario=self.usuario, comentario="Antes del envío",
            fecha=timezone.now() - timedelta(days=2),
        )
        self.cuenta, _ = crear_cuenta_gastos_desde_operacion_si_corresponde(
            self.operacion, creado_por=self.usuario,
        )
        self.client.force_login(self.usuario)

    def test_lectura_conserva_registros_autor_fecha_y_refleja_nuevos(self):
        propio = CuentaGastosComentario.objects.create(
            cuenta_gasto=self.cuenta, usuario=self.usuario, comentario="Propio de cuenta",
            fecha=timezone.now() - timedelta(days=1),
        )
        for layout in ("modal", "drawer"):
            response = self.client.get(reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.pk]), {"layout": layout})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["html"].count("Antes del envío"), 1)
        nuevo = OperacionComentario.objects.create(
            operacion=self.operacion, usuario=self.usuario, comentario="Después del envío",
        )
        for _ in range(2):
            comentarios = _comentarios_queryset(self.cuenta)
            self.assertEqual(comentarios, [nuevo, propio, self.original])
            self.assertEqual(comentarios[-1].usuario, self.usuario)
            self.assertEqual(comentarios[-1].fecha, self.original.fecha)
        self.original.refresh_from_db()
        self.assertEqual(self.operacion.comentarios.count(), 2)
        self.assertEqual(self.cuenta.comentarios.count(), 1)
        self.assertEqual(_cuenta_queryset().get(pk=self.cuenta.pk).comentarios_count, 3)
        html = self.client.get(reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.pk])).json()["html"]
        self.assertIn("Después del envío", html)
        self.assertIn("Autor original", html)
        self.assertIn(timezone.localtime(self.original.fecha).strftime("%Y-%m-%d %H:%M"), html)

    def test_ajax_conserva_originales_y_contadores_incluso_en_error(self):
        url = reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.pk])
        for texto, status in (("Nuevo propio", 200), ("", 400)):
            response = self.client.post(url, {"comentario": texto}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
            self.assertEqual(response.status_code, status)
            self.assertEqual(response.json()["comments_count"], 2)
            self.assertEqual(response.json()["comments_html"].count("Antes del envío"), 1)
            self.assertIn("Nuevo propio", response.json()["comments_html"])
        self.assertEqual(self.operacion.comentarios.count(), 1)
        self.assertEqual(self.cuenta.comentarios.count(), 1)

    def test_sin_comentarios_y_sin_operacion(self):
        self.operacion.comentarios.all().delete()
        self.assertEqual(_comentarios_queryset(self.cuenta), [])
        manual = CuentaGastos.objects.create(titulo="Manual", creado_por=self.usuario)
        self.assertEqual(_comentarios_queryset(manual), [])
        propio = CuentaGastosComentario.objects.create(cuenta_gasto=manual, usuario=self.usuario, comentario="Solo manual")
        self.assertEqual(_comentarios_queryset(manual), [propio])
        self.assertEqual(_cuenta_queryset().get(pk=manual.pk).comentarios_count, 1)

    def test_no_incluye_comentarios_de_otra_operacion(self):
        otra = Operacion.objects.create(titulo="Otra", creado_por=self.usuario)
        OperacionComentario.objects.create(operacion=otra, usuario=self.usuario, comentario="Ajeno")
        self.assertEqual(_comentarios_queryset(self.cuenta), [self.original])

    def test_restricciones_existentes(self):
        otro = get_user_model().objects.create_user(username="sin-permiso-comentar")
        self.client.force_login(otro)
        url = reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.pk])
        self.assertEqual(self.client.post(url, {"comentario": "Prohibido"}).status_code, 403)
        self.assertFalse(self.cuenta.comentarios.exists())
        self.client.logout()
        detalle = reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.pk])
        self.assertEqual(self.client.get(detalle).status_code, 302)
        self.assertEqual(self.client.post(url, {"comentario": "Prohibido"}).status_code, 302)
        self.client.force_login(self.usuario)
        self.cuenta.eliminado_en = timezone.now()
        self.cuenta.save(update_fields=["eliminado_en"])
        self.assertEqual(self.client.get(detalle).status_code, 404)
