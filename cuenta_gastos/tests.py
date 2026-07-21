from datetime import timedelta

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from . import views
from .models import CuentaGastos, CuentaGastosArchivo, CuentaGastosComentario, CuentaGastosEnlace, CuentaGastosEtiqueta, CuentaGastosOpcion


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class CuentaGastosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.asignado = User.objects.create_user(username="asignado", password="pass", first_name="Asignado")
        
        self.cliente = Cliente.objects.create(nombre="Cliente Test", empresa="Empresa Test")
        self.etiqueta = CuentaGastosEtiqueta.objects.create(nombre="Urgente", color="#FF0000")
        self.opcion = CuentaGastosOpcion.objects.create(nombre="Opción Especial")

        self.cuenta = CuentaGastos.objects.create(
            titulo="Laptop HP",
            descripcion="Laptop para desarrollo",
            cliente=self.cliente,
            prioridad="ALTA",
            fecha_vencimiento="2026-05-22",
            creado_por=self.user,
        )
        self.cuenta.asignados.add(self.asignado)
        self.cuenta.etiquetas.add(self.etiqueta)
        self.cuenta.opciones.add(self.opcion)

        self.client = Client()
        self.client.force_login(self.user)

    def test_panel_cuenta_gastos_view(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"))
        self.assertEqual(resp.status_code, 200)

    def test_panel_filtra_por_usuario(self):
        resp = self.client.get(reverse("cuenta_gastos:panel_cuenta_gastos"), {"usuario": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Laptop HP")

    def test_detalle_cuenta_gastos_view(self):
        resp = self.client.get(reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 200)

    def test_detalle_cuenta_gastos_drawer_layout(self):
        resp = self.client.get(
            reverse("cuenta_gastos:detalle_cuenta_gastos", args=[self.cuenta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cuenta-drawer__panel", data["html"])
        self.assertIn('name="layout" value="drawer"', data["html"])
        self.assertIn("data-cuenta-tags-section", data["html"])
        self.assertIn("data-cuenta-options-section", data["html"])

    def test_editar_cuenta_preserva_valores(self):
        # We send a POST request with empty values for title, description, client, assignments, tags, options, etc.
        # But changing priority from ALTA to MEDIA.
        post_data = {
            "titulo": "",
            "descripcion": "",
            "cliente": "",
            "fecha_vencimiento": "",
            "prioridad": "MEDIA",
            "asignados": [],
            "etiquetas": [],
            "opciones": [],
        }

        resp = self.client.post(
            reverse("cuenta_gastos:editar_cuenta", args=[self.cuenta.id]),
            post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)

        # Refresh from database and assert values
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.prioridad, "MEDIA")
        self.assertEqual(self.cuenta.titulo, "Laptop HP")
        self.assertEqual(self.cuenta.descripcion, "Laptop para desarrollo")
        self.assertEqual(self.cuenta.cliente, self.cliente)
        self.assertEqual(str(self.cuenta.fecha_vencimiento), "2026-05-22")
        self.assertIn(self.asignado, self.cuenta.asignados.all())
        self.assertIn(self.etiqueta, self.cuenta.etiquetas.all())
        self.assertIn(self.opcion, self.cuenta.opciones.all())

    def test_editar_cuenta_ajax_drawer_devuelve_drawer_y_tarjeta(self):
        resp = self.client.post(
            reverse("cuenta_gastos:editar_cuenta", args=[self.cuenta.id]),
            {
                "layout": "drawer",
                "titulo": "Laptop HP Drawer",
                "descripcion": "Laptop para desarrollo",
                "cliente": str(self.cliente.id),
                "fecha_vencimiento": "2026-05-22",
                "prioridad": "MEDIA",
                "asignados": [str(self.asignado.id)],
                "etiquetas": [str(self.etiqueta.id)],
                "opciones": [str(self.opcion.id)],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertIn("cuenta-drawer__panel", data["html"])
        self.assertIn('id="cuenta-%s"' % self.cuenta.id, data["card_html"])

    def test_agregar_comentario_ajax_devuelve_solo_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "Comentario desde drawer", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["comments_count"], 1)
        self.assertIn("data-cuenta-comments-section", data["comments_html"])
        self.assertIn("Comentario desde drawer", data["comments_html"])
        self.assertNotIn("cuenta-drawer__panel", data["comments_html"])

    def test_agregar_comentario_ajax_preserva_texto_en_error(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_comentario", args=[self.cuenta.id]),
            {"comentario": "", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["success"])
        self.assertIn("data-cuenta-comments-section", data["comments_html"])
        self.assertIn('name="comentario"', data["comments_html"])

    def test_queryset_comentarios_muestra_mas_recientes_primero(self):
        viejo = CuentaGastosComentario.objects.create(
            cuenta_gasto=self.cuenta,
            usuario=self.user,
            comentario="Comentario viejo",
            fecha=timezone.now() - timedelta(days=1),
        )
        nuevo = CuentaGastosComentario.objects.create(
            cuenta_gasto=self.cuenta,
            usuario=self.user,
            comentario="Comentario nuevo",
            fecha=timezone.now(),
        )
        comentarios = list(views._comentarios_queryset(self.cuenta))
        self.assertEqual([comentarios[0].id, comentarios[1].id], [nuevo.id, viejo.id])

    def test_actualizar_etiquetas_cuenta_ajax_devuelve_seccion_y_tarjeta(self):
        otra = CuentaGastosEtiqueta.objects.create(nombre="Seguimiento", color="#00AAFF")
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "etiquetas": [str(self.etiqueta.id), str(otra.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("data-cuenta-tags-section", data["html"])
        self.assertIn("Seguimiento", data["html"])
        self.assertIn('id="cuenta-%s"' % self.cuenta.id, data["card_html"])

    def test_crear_etiqueta_cuenta_ajax_la_asigna_sin_borrar_catalogo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:crear_etiqueta_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "nombre": "Finanzas", "color": "#123456"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(CuentaGastosEtiqueta.objects.filter(nombre="Finanzas", color="#123456").exists())
        self.assertIn("Finanzas", data["html"])

    def test_quitar_etiqueta_cuenta_solo_desasocia(self):
        resp = self.client.post(
            reverse("cuenta_gastos:quitar_etiqueta_cuenta", args=[self.cuenta.id, self.etiqueta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertNotIn(self.etiqueta, self.cuenta.etiquetas.all())
        self.assertTrue(CuentaGastosEtiqueta.objects.filter(id=self.etiqueta.id).exists())

    def test_actualizar_opciones_cuenta_ajax_devuelve_seccion(self):
        otra = CuentaGastosOpcion.objects.create(nombre="Pago parcial")
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "opciones": [str(self.opcion.id), str(otra.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertIn("data-cuenta-options-section", data["html"])
        self.assertIn("Pago parcial", data["html"])

    def test_crear_opcion_cuenta_ajax_la_asigna(self):
        resp = self.client.post(
            reverse("cuenta_gastos:crear_opcion_cuenta", args=[self.cuenta.id]),
            {"layout": "drawer", "nombre": "Transferencia"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertTrue(CuentaGastosOpcion.objects.filter(nombre="Transferencia").exists())
        self.assertIn("Transferencia", data["html"])

    def test_quitar_opcion_cuenta_solo_desasocia(self):
        resp = self.client.post(
            reverse("cuenta_gastos:quitar_opcion_cuenta", args=[self.cuenta.id, self.opcion.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertNotIn(self.opcion, self.cuenta.opciones.all())
        self.assertTrue(CuentaGastosOpcion.objects.filter(id=self.opcion.id).exists())

    def test_agregar_archivo_ajax_valido_devuelve_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer", "archivos": SimpleUploadedFile("factura.txt", b"contenido")},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["files_count"], 1)
        self.assertIn("data-cuenta-files-section", data["html"])
        self.assertIn("factura", data["html"])

    def test_agregar_archivo_ajax_invalido_devuelve_error_y_conteo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn("data-cuenta-files-section", data["html"])

    def test_eliminar_archivo_ajax_devuelve_seccion_y_conteo(self):
        archivo = CuentaGastosArchivo.objects.create(
            cuenta_gasto=self.cuenta,
            archivo=SimpleUploadedFile("factura_eliminar.txt", b"contenido"),
            subido_por=self.user,
        )
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"layout": "drawer", "archivo_id": archivo.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn("data-cuenta-files-section", data["html"])
        self.assertFalse(CuentaGastosArchivo.objects.filter(id=archivo.id).exists())

    def test_agregar_enlace_ajax_valido_devuelve_seccion_y_contador(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "titulo": "Portal", "url": "https://example.com"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["links_count"], 1)
        self.assertIn("data-cuenta-links-section", data["html"])
        self.assertIn("https://example.com", data["html"])

    def test_agregar_enlace_ajax_invalido_devuelve_error_y_conteo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "titulo": "Portal", "url": "nota-url"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 400)
        data = resp.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn("data-cuenta-links-section", data["html"])

    def test_eliminar_enlace_ajax_devuelve_seccion_y_conteo(self):
        enlace = CuentaGastosEnlace.objects.create(
            cuenta_gasto=self.cuenta,
            titulo="Portal borrar",
            url="https://example.com/borrar",
            creado_por=self.user,
        )
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"layout": "drawer", "enlace_id": enlace.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn("data-cuenta-links-section", data["html"])
        self.assertFalse(CuentaGastosEnlace.objects.filter(id=enlace.id).exists())

    def test_inline_update_titulo_only_updates_titulo(self):
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_cuenta_inline", args=[self.cuenta.id]),
            {"field": "titulo", "titulo": "Nuevo titulo inline"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertEqual(self.cuenta.titulo, "Nuevo titulo inline")
        self.assertEqual(self.cuenta.prioridad, "ALTA")
        self.assertEqual(self.cuenta.cliente, self.cliente)

    def test_inline_update_asignados_only_updates_asignados(self):
        User = get_user_model()
        nuevo = User.objects.create_user(username="nuevo_inline", password="pass", first_name="Nuevo")

        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_cuenta_inline", args=[self.cuenta.id]),
            {"field": "asignados", "asignados": [str(nuevo.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 200)
        self.cuenta.refresh_from_db()
        self.assertIn(nuevo, self.cuenta.asignados.all())
        self.assertNotIn(self.asignado, self.cuenta.asignados.all())
        self.assertEqual(self.cuenta.titulo, "Laptop HP")

    def test_usuario_sin_permiso_no_puede_eliminar_archivo(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_archivo_cg", password="pass")
        archivo = CuentaGastosArchivo.objects.create(
            cuenta_gasto=self.cuenta,
            archivo=SimpleUploadedFile("factura.txt", b"contenido"),
            subido_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"archivo_id": archivo.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(CuentaGastosArchivo.objects.filter(id=archivo.id).exists())

    def test_eliminar_archivo_inexistente_devuelve_404(self):
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]),
            {"archivo_id": 999999},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 404)

    def test_agregar_archivo_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_eliminar_archivo_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:eliminar_archivo", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_usuario_anonimo_no_puede_agregar_archivo(self):
        self.client.logout()
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_archivo", args=[self.cuenta.id]),
            {"archivos": SimpleUploadedFile("anonimo.txt", b"contenido")},
        )
        self.assertEqual(resp.status_code, 302)

    def test_usuario_sin_permiso_no_puede_eliminar_enlace(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_enlace_cg", password="pass")
        enlace = CuentaGastosEnlace.objects.create(
            cuenta_gasto=self.cuenta,
            titulo="Portal",
            url="https://example.com/portal",
            creado_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"enlace_id": enlace.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(CuentaGastosEnlace.objects.filter(id=enlace.id).exists())

    def test_usuario_sin_permiso_no_puede_actualizar_etiquetas_cuenta(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_tags_cg", password="pass")
        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]),
            {"etiquetas": [str(self.etiqueta.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 403)

    def test_usuario_sin_permiso_no_puede_actualizar_opciones_cuenta(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_opts_cg", password="pass")
        self.client.force_login(otro)
        resp = self.client.post(
            reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]),
            {"opciones": [str(self.opcion.id)]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 403)

    def test_eliminar_enlace_inexistente_devuelve_404(self):
        resp = self.client.post(
            reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]),
            {"enlace_id": 999999},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(resp.status_code, 404)

    def test_agregar_enlace_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_eliminar_enlace_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:eliminar_enlace", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_usuario_anonimo_no_puede_agregar_enlace(self):
        self.client.logout()
        resp = self.client.post(
            reverse("cuenta_gastos:agregar_enlace", args=[self.cuenta.id]),
            {"titulo": "Anonimo", "url": "https://example.com"},
        )
        self.assertEqual(resp.status_code, 302)

    def test_actualizar_etiquetas_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:actualizar_etiquetas_cuenta", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)

    def test_actualizar_opciones_get_no_permitido(self):
        resp = self.client.get(reverse("cuenta_gastos:actualizar_opciones_cuenta", args=[self.cuenta.id]))
        self.assertEqual(resp.status_code, 405)
