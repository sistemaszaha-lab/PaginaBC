from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.urls import reverse

from .models import Operacion, OperacionArchivo, OperacionComentario, OperacionEnlace, OperacionEtiqueta, OperacionOpcion
from solicitudes.models import Referencia


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
)
class ReferenciaAOperacionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user(username="convertidor-op", password="pass")
        self.referencia = Referencia.objects.create(
            referencia="BC261001", consecutivo=1, ejecutivo=self.usuario,
            cliente="CLIENTE SIN ALTA", servicio="importacion",
        )
        self.client.force_login(self.usuario)

    def test_crea_operacion_pendiente_vinculada_y_no_duplica(self):
        url = reverse("operaciones:enviar_referencia_a_operaciones", args=[self.referencia.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {"titulo": "Referencia BC261001", "descripcion": "detalle"})
        self.assertRedirects(response, reverse("operaciones:panel_operaciones"))
        operacion = Operacion.objects.get(referencia_origen=self.referencia)
        self.assertEqual(operacion.estado, Operacion.Estado.PENDIENTE)
        self.assertEqual(operacion.creado_por, self.usuario)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(Operacion.objects.filter(referencia_origen=self.referencia).count(), 1)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesPanelFiltroUsuariosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.asignado = User.objects.create_user(username="asignado", password="pass", first_name="Asignado")

        self.operacion = Operacion.objects.create(
            titulo="Op 1",
            creado_por=self.user,
        )
        self.operacion.asignados.add(self.asignado)

        self.client = Client()
        self.client.force_login(self.user)

    def test_panel_sin_param_usuarios(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"))
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_param_vacio_no_explota(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": ""})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_all_no_explota(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": "all"})
        self.assertEqual(resp.status_code, 200)

    def test_panel_usuarios_ids_filtra(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"), {"usuario": str(self.asignado.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Op 1")

    def test_panel_conserva_la_estructura_del_tablero_kanban(self):
        resp = self.client.get(reverse("operaciones:panel_operaciones"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'data-operaciones-board="1"')
        self.assertContains(resp, 'data-operaciones-column="1"')
        self.assertContains(resp, 'data-panel-operacion-card="1"')
        self.assertContains(resp, 'data-estado="PENDIENTE"')
        self.assertContains(resp, 'class="btn btn-sm operaciones-column__add-btn"', count=9)
        self.assertContains(resp, 'class="operaciones-inline-form"', count=9)
        self.assertContains(resp, 'data-operacion-quick-edit-open="1"')
        self.assertContains(resp, 'id="OperacionDetalleDrawer"')
        self.assertContains(resp, 'id="OperacionDetalleDrawerContent"')


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesDetalleModalTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="tester", password="pass", first_name="Tester")
        self.operacion = Operacion.objects.create(titulo="Op 1", creado_por=self.user)

        self.client = Client()
        self.client.force_login(self.user)

    def test_detalle_operacion_endpoint(self):
        resp = self.client.get(reverse("operaciones:detalle_operacion", args=[self.operacion.id]))
        self.assertEqual(resp.status_code, 200)

    def test_drawer_y_modal_comparten_el_mismo_contenido_interno(self):
        detalle_resp = self.client.get(
            reverse("operaciones:detalle_operacion", args=[self.operacion.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        modal_resp = self.client.get(
            reverse("operaciones:detalle_operacion_modal", args=[self.operacion.id]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(detalle_resp.status_code, 200)
        self.assertEqual(modal_resp.status_code, 200)
        detalle_html = detalle_resp.json()["html"]
        modal_html = modal_resp.json()["html"]
        self.assertIn('data-operacion-modal-form="1"', detalle_html)
        self.assertIn('data-operacion-modal-form="1"', modal_html)
        self.assertIn('data-operacion-detail-close="1"', detalle_html)
        self.assertIn('data-operacion-detail-close="1"', modal_html)
        self.assertIn('for="id_titulo"', detalle_html)
        self.assertIn('for="id_asignados"', modal_html)

    def test_editar_operacion_preserva_valores(self):
        # Crear asignados y etiquetas
        User = get_user_model()
        usuario_2 = User.objects.create_user(username="tester2", password="pass")
        from operaciones.models import OperacionEtiqueta
        etiqueta = OperacionEtiqueta.objects.create(nombre="Urgente")
        
        self.operacion.titulo = "Laptop"
        self.operacion.fecha_vencimiento = "2026-05-22"
        self.operacion.prioridad = "ALTA"
        self.operacion.save()
        self.operacion.asignados.add(usuario_2)
        self.operacion.etiquetas.add(etiqueta)

        # Hacemos un POST mandando valores vacíos/None
        post_data = {
            "titulo": "",
            "fecha_vencimiento": "",
            "prioridad": "MEDIA",  # Queremos cambiar solo la prioridad
            "asignados": [],
            "etiquetas": [],
        }
        
        resp = self.client.post(
            reverse("operaciones:editar_operacion", args=[self.operacion.id]),
            post_data,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(resp.status_code, 200)
        
        self.operacion.refresh_from_db()
        # Verificar que la prioridad cambió a MEDIA
        self.assertEqual(self.operacion.prioridad, "MEDIA")
        # Verificar que el título y fecha de vencimiento se mantuvieron intactos
        self.assertEqual(self.operacion.titulo, "Laptop")
        self.assertEqual(str(self.operacion.fecha_vencimiento), "2026-05-22")
        # Verificar que los asignados y etiquetas se mantuvieron
        self.assertIn(usuario_2, self.operacion.asignados.all())
        self.assertIn(etiqueta, self.operacion.etiquetas.all())
        self.assertIn('data-panel-operacion-card="1"', resp.json()["html"])

    def test_usuario_sin_permiso_no_puede_eliminar_archivo(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_archivo", password="pass")
        archivo = OperacionArchivo.objects.create(
            operacion=self.operacion,
            archivo=SimpleUploadedFile("evidencia.txt", b"hola"),
            subido_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("operaciones:eliminar_archivo", args=[self.operacion.id]),
            {"archivo_id": archivo.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(OperacionArchivo.objects.filter(id=archivo.id).exists())

    def test_usuario_sin_permiso_no_puede_eliminar_enlace(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro_enlace", password="pass")
        enlace = OperacionEnlace.objects.create(
            operacion=self.operacion,
            titulo="Documento",
            url="https://example.com/doc",
            creado_por=self.user,
        )

        self.client.force_login(otro)
        resp = self.client.post(
            reverse("operaciones:eliminar_enlace", args=[self.operacion.id]),
            {"enlace_id": enlace.id},
        )

        self.assertEqual(resp.status_code, 403)
        self.assertTrue(OperacionEnlace.objects.filter(id=enlace.id).exists())


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesCrearOperacionTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="create_owner", password="pass")
        self.client = Client()
        self.client.force_login(self.user)
        self.url = reverse("operaciones:crear_operacion")

    def test_formulario_separa_ids_y_nombres_del_enlace_opcional(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'id="id_titulo"', count=1)
        self.assertContains(response, 'id="id_enlace-titulo"', count=1)
        self.assertContains(response, 'for="id_enlace-titulo"', count=1)

    def test_crea_operacion_y_enlace_con_titulos_independientes(self):
        response = self.client.post(
            self.url,
            {
                "titulo": "Operacion principal",
                "enlace-titulo": "Factura comercial",
                "enlace-url": "https://example.com/factura",
            },
        )

        self.assertRedirects(response, reverse("operaciones:panel_operaciones"))
        operacion = Operacion.objects.get(titulo="Operacion principal")
        enlace = OperacionEnlace.objects.get(operacion=operacion)
        self.assertEqual(enlace.titulo, "Factura comercial")
        self.assertEqual(enlace.url, "https://example.com/factura")


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesMovimientoTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="owner", password="pass")
        self.assigned_user = User.objects.create_user(username="assigned", password="pass")
        self.other_user = User.objects.create_user(username="other", password="pass")
        self.operacion = Operacion.objects.create(
            titulo="Operacion a mover",
            estado=Operacion.Estado.PENDIENTE,
            creado_por=self.owner,
        )
        self.move_url = reverse("operaciones:mover_operacion", args=[self.operacion.id])
        self.client = Client()

    def test_propietario_puede_mover_y_recibe_estado_sincronizable(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            self.move_url,
            {"estado": Operacion.Estado.SEGUROS},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {
            "status": "ok",
            "id": self.operacion.id,
            "estado": Operacion.Estado.SEGUROS,
            "estado_label": "Seguros",
        })
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.SEGUROS)

    def test_estado_invalido_no_modifica_la_operacion(self):
        self.client.force_login(self.owner)

        response = self.client.post(self.move_url, {"estado": "NO_EXISTE"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["status"], "error")
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.PENDIENTE)

    def test_usuario_asignado_puede_mover(self):
        self.operacion.asignados.add(self.assigned_user)
        self.client.force_login(self.assigned_user)

        response = self.client.post(self.move_url, {"estado": Operacion.Estado.EN_ADUANA})

        self.assertEqual(response.status_code, 200)
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.EN_ADUANA)

    def test_usuario_sin_permiso_no_puede_mover(self):
        self.client.force_login(self.other_user)

        response = self.client.post(self.move_url, {"estado": Operacion.Estado.SEGUROS})

        self.assertEqual(response.status_code, 403)
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.PENDIENTE)

    def test_mover_requiere_post(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.move_url)

        self.assertEqual(response.status_code, 405)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesInlineCreateTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="inline_owner", password="pass")
        self.client = Client()
        self.client.force_login(self.user)
        self.inline_url = reverse("operaciones:crear_operacion_inline")

    def test_crea_operacion_en_el_estado_de_la_columna(self):
        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion inline",
                "prioridad": Operacion.Prioridad.ALTA,
                "estado": Operacion.Estado.EN_ADUANA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estado"], Operacion.Estado.EN_ADUANA)
        self.assertIn('data-panel-operacion-card="1"', data["html"])
        self.assertIn('data-operacion-state-select="1"', data["html"])

        operacion = Operacion.objects.get(pk=data["id"])
        self.assertEqual(operacion.titulo, "Operacion inline")
        self.assertEqual(operacion.estado, Operacion.Estado.EN_ADUANA)
        self.assertEqual(operacion.prioridad, Operacion.Prioridad.ALTA)
        self.assertEqual(operacion.creado_por, self.user)

    def test_errores_de_formulario_devuelven_el_parcial_inline(self):
        response = self.client.post(
            self.inline_url,
            {"titulo": "", "estado": Operacion.Estado.PENDIENTE},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn('data-operacion-inline-form="1"', data["html"])
        self.assertIn("Este campo es obligatorio", data["html"])
        self.assertFalse(Operacion.objects.exists())

    def test_estado_invalido_no_crea_operacion(self):
        response = self.client.post(
            self.inline_url,
            {"titulo": "Operacion invalida", "estado": "NO_EXISTE"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["ok"])
        self.assertFalse(Operacion.objects.exists())

    def test_creacion_inline_requiere_solicitud_ajax(self):
        response = self.client.post(
            self.inline_url,
            {"titulo": "Operacion sin AJAX", "estado": Operacion.Estado.PENDIENTE},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(Operacion.objects.exists())

    def test_creacion_inline_requiere_post(self):
        response = self.client.get(self.inline_url)

        self.assertEqual(response.status_code, 405)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesQuickEditTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="quick_owner", password="pass")
        self.assigned_user = User.objects.create_user(username="quick_assigned", password="pass")
        self.other_user = User.objects.create_user(username="quick_other", password="pass")
        self.operacion = Operacion.objects.create(
            titulo="Operacion original",
            descripcion="Descripcion que no se edita rapido",
            estado=Operacion.Estado.PENDIENTE,
            prioridad=Operacion.Prioridad.MEDIA,
            fecha_vencimiento="2026-05-22",
            creado_por=self.owner,
        )
        self.edit_url = reverse("operaciones:editar_operacion_rapida", args=[self.operacion.id])
        self.client = Client()
        self.client.force_login(self.owner)

    def test_carga_formulario_rapido_con_campos_permitidos(self):
        response = self.client.get(self.edit_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn('data-operacion-quick-edit-form="1"', data["html"])
        self.assertIn('name="titulo"', data["html"])
        self.assertIn('name="asignados"', data["html"])
        self.assertNotIn('name="estado"', data["html"])
        self.assertNotIn('name="descripcion"', data["html"])

    def test_actualiza_campos_permitidos_y_m2m_sin_cambiar_estado(self):
        response = self.client.post(
            self.edit_url,
            {
                "titulo": "Operacion actualizada",
                "prioridad": Operacion.Prioridad.ALTA,
                "fecha_vencimiento": "2026-06-30",
                "asignados": [self.assigned_user.id],
                "estado": Operacion.Estado.SEGUROS,
                "descripcion": "No debe cambiar",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertIn('data-panel-operacion-card="1"', data["html"])
        self.assertIn('data-operacion-state-select="1"', data["html"])

        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.titulo, "Operacion actualizada")
        self.assertEqual(self.operacion.prioridad, Operacion.Prioridad.ALTA)
        self.assertEqual(str(self.operacion.fecha_vencimiento), "2026-06-30")
        self.assertEqual(self.operacion.estado, Operacion.Estado.PENDIENTE)
        self.assertEqual(self.operacion.descripcion, "Descripcion que no se edita rapido")
        self.assertEqual(list(self.operacion.asignados.all()), [self.assigned_user])

    def test_errores_de_formulario_devuelven_editor_inline(self):
        response = self.client.post(
            self.edit_url,
            {"titulo": "", "prioridad": Operacion.Prioridad.MEDIA},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn('data-operacion-quick-edit-form="1"', data["html"])
        self.assertIn("Este campo es obligatorio", data["html"])
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.titulo, "Operacion original")

    def test_usuario_sin_permiso_no_puede_editar_rapido(self):
        self.client.force_login(self.other_user)

        response = self.client.post(
            self.edit_url,
            {"titulo": "No permitido"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.titulo, "Operacion original")

    def test_edicion_rapida_requiere_ajax_y_metodo_permitido(self):
        response = self.client.get(self.edit_url)
        self.assertEqual(response.status_code, 400)

        response = self.client.put(self.edit_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
        self.assertEqual(response.status_code, 405)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesComentariosAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="comments_owner", password="pass", first_name="Owner")
        self.other_user = User.objects.create_user(username="comments_other", password="pass")
        self.operacion = Operacion.objects.create(titulo="Operacion con comentarios", creado_por=self.owner)
        self.url = reverse("operaciones:agregar_comentario", args=[self.operacion.id])
        self.client = Client()
        self.client.force_login(self.owner)

    def test_crea_comentario_y_devuelve_solo_la_seccion_actualizada(self):
        response = self.client.post(
            self.url,
            {"comentario": "Comentario nuevo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["id"], self.operacion.id)
        self.assertEqual(data["comments_count"], 1)
        self.assertIn('data-operacion-comments-section="1"', data["comments_html"])
        self.assertIn('data-operacion-detail-comments-count="1">1', data["comments_html"])
        self.assertNotIn('data-operacion-modal-form="1"', data["comments_html"])
        comentario = OperacionComentario.objects.get(operacion=self.operacion)
        self.assertEqual(comentario.comentario, "Comentario nuevo")
        self.assertEqual(comentario.usuario, self.owner)

    def test_error_de_validacion_devuelve_la_misma_seccion_y_el_conteo(self):
        OperacionComentario.objects.create(
            operacion=self.operacion,
            usuario=self.owner,
            comentario="Comentario existente",
        )

        response = self.client.post(
            self.url,
            {"comentario": ""},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["comments_count"], 1)
        self.assertIn('data-operacion-comments-section="1"', data["comments_html"])
        self.assertIn("Este campo es obligatorio", data["comments_html"])
        self.assertEqual(OperacionComentario.objects.filter(operacion=self.operacion).count(), 1)

    def test_usuario_sin_permiso_no_puede_comentar(self):
        self.client.force_login(self.other_user)

        response = self.client.post(
            self.url,
            {"comentario": "No permitido"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(OperacionComentario.objects.filter(operacion=self.operacion).exists())

    def test_comentario_requiere_solicitud_ajax(self):
        response = self.client.post(self.url, {"comentario": "Sin AJAX"})

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertFalse(OperacionComentario.objects.filter(operacion=self.operacion).exists())

    def test_comentario_requiere_post(self):
        response = self.client.get(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 405)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesArchivosAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="files_owner", password="pass")
        self.other_user = User.objects.create_user(username="files_other", password="pass")
        self.operacion = Operacion.objects.create(titulo="Operacion con archivos", creado_por=self.owner)
        self.upload_url = reverse("operaciones:agregar_archivo", args=[self.operacion.id])
        self.delete_url = reverse("operaciones:eliminar_archivo", args=[self.operacion.id])
        self.archivos_creados = []
        self.client = Client()
        self.client.force_login(self.owner)

    def tearDown(self):
        for archivo in self.archivos_creados:
            archivo.archivo.storage.delete(archivo.archivo.name)

    def crear_archivo(self, nombre="evidencia.txt", contenido=b"contenido"):
        archivo = OperacionArchivo.objects.create(
            operacion=self.operacion,
            archivo=SimpleUploadedFile(nombre, contenido),
            subido_por=self.owner,
        )
        self.archivos_creados.append(archivo)
        return archivo

    def test_sube_archivos_y_devuelve_solo_la_seccion_actualizada(self):
        response = self.client.post(
            self.upload_url,
            {"archivos": [SimpleUploadedFile("evidencia.txt", b"contenido")]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["id"], self.operacion.id)
        self.assertEqual(data["files_count"], 1)
        self.assertIn('data-operacion-files-section="1"', data["files_html"])
        self.assertIn('data-operacion-detail-files-count="1">1', data["files_html"])
        self.assertNotIn('data-operacion-modal-form="1"', data["files_html"])
        self.archivos_creados.extend(OperacionArchivo.objects.filter(operacion=self.operacion))

    def test_error_de_validacion_devuelve_la_seccion_y_no_crea_archivos(self):
        response = self.client.post(
            self.upload_url,
            {},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn('data-operacion-files-section="1"', data["files_html"])
        self.assertIn("Selecciona al menos un archivo", data["files_html"])
        self.assertFalse(OperacionArchivo.objects.filter(operacion=self.operacion).exists())

    def test_rechaza_mas_de_cinco_archivos(self):
        archivos = [SimpleUploadedFile(f"archivo-{indice}.txt", b"contenido") for indice in range(6)]
        response = self.client.post(
            self.upload_url,
            {"archivos": archivos},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("hasta 5 archivos", response.json()["files_html"])
        self.assertFalse(OperacionArchivo.objects.filter(operacion=self.operacion).exists())

    def test_rechaza_formatos_no_permitidos(self):
        response = self.client.post(
            self.upload_url,
            {"archivos": [SimpleUploadedFile("ejecutable.exe", b"contenido")]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("formato no permitido", response.json()["files_html"])
        self.assertFalse(OperacionArchivo.objects.filter(operacion=self.operacion).exists())

    def test_elimina_archivo_y_devuelve_solo_la_seccion_actualizada(self):
        archivo = self.crear_archivo()
        response = self.client.post(
            self.delete_url,
            {"archivo_id": archivo.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["files_count"], 0)
        self.assertIn('data-operacion-files-section="1"', data["files_html"])
        self.assertIn("Sin archivos", data["files_html"])
        self.assertNotIn("card_html", data)
        self.assertFalse(OperacionArchivo.objects.filter(id=archivo.id).exists())

    def test_usuario_sin_permiso_no_puede_subir_ni_eliminar(self):
        archivo = self.crear_archivo()
        self.client.force_login(self.other_user)

        upload_response = self.client.post(
            self.upload_url,
            {"archivos": [SimpleUploadedFile("prohibido.txt", b"contenido")]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        delete_response = self.client.post(
            self.delete_url,
            {"archivo_id": archivo.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(upload_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(OperacionArchivo.objects.filter(id=archivo.id).exists())

    def test_archivos_requieren_solicitud_ajax(self):
        upload_response = self.client.post(
            self.upload_url,
            {"archivos": [SimpleUploadedFile("sin-ajax.txt", b"contenido")]},
        )
        archivo = self.crear_archivo("eliminar-no-ajax.txt")
        delete_response = self.client.post(self.delete_url, {"archivo_id": archivo.id})

        self.assertEqual(upload_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        self.assertFalse(OperacionArchivo.objects.filter(operacion=self.operacion, archivo__icontains="sin-ajax").exists())
        self.assertTrue(OperacionArchivo.objects.filter(id=archivo.id).exists())


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesEnlacesAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="links_owner", password="pass")
        self.other_user = User.objects.create_user(username="links_other", password="pass")
        self.operacion = Operacion.objects.create(titulo="Operacion con enlaces", creado_por=self.owner)
        self.other_operacion = Operacion.objects.create(titulo="Otra operacion", creado_por=self.owner)
        self.create_url = reverse("operaciones:agregar_enlace", args=[self.operacion.id])
        self.delete_url = reverse("operaciones:eliminar_enlace", args=[self.operacion.id])
        self.client = Client()
        self.client.force_login(self.owner)

    def crear_enlace(self, operacion=None, titulo="Documento", url="https://example.com/documento"):
        return OperacionEnlace.objects.create(
            operacion=operacion or self.operacion,
            titulo=titulo,
            url=url,
            creado_por=self.owner,
        )

    def test_crea_enlace_y_devuelve_solo_la_seccion_actualizada(self):
        response = self.client.post(
            self.create_url,
            {"titulo": "Factura", "url": "https://example.com/factura"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["id"], self.operacion.id)
        self.assertEqual(data["links_count"], 1)
        self.assertIn('data-operacion-links-section="1"', data["links_html"])
        self.assertIn('data-operacion-detail-links-count="1"', data["links_html"])
        self.assertIn('aria-live="polite">1</span>', data["links_html"])
        self.assertNotIn('data-operacion-modal-form="1"', data["links_html"])
        enlace = OperacionEnlace.objects.get(operacion=self.operacion)
        self.assertEqual(enlace.titulo, "Factura")
        self.assertEqual(enlace.creado_por, self.owner)

    def test_error_de_validacion_devuelve_la_seccion_y_no_crea_enlace(self):
        response = self.client.post(
            self.create_url,
            {"titulo": "", "url": "ftp://example.com/archivo"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn('data-operacion-links-section="1"', data["links_html"])
        self.assertIn("Este campo es obligatorio", data["links_html"])
        self.assertFalse(OperacionEnlace.objects.filter(operacion=self.operacion).exists())

    def test_rechaza_url_con_credenciales_o_esquema_inseguro(self):
        for url in ("ftp://example.com/archivo", "https://usuario:secreto@example.com/archivo"):
            response = self.client.post(
                self.create_url,
                {"titulo": "Inseguro", "url": url},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )

            self.assertEqual(response.status_code, 400)
            self.assertIn('data-operacion-links-section="1"', response.json()["links_html"])
        self.assertFalse(OperacionEnlace.objects.filter(operacion=self.operacion).exists())

    def test_elimina_solo_el_enlace_de_la_operacion_actual(self):
        enlace = self.crear_enlace()
        enlace_ajeno = self.crear_enlace(self.other_operacion, "Otro", "https://example.com/otro")

        response = self.client.post(
            self.delete_url,
            {"enlace_id": enlace.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["links_count"], 0)
        self.assertIn("Sin enlaces", data["links_html"])
        self.assertNotIn("card_html", data)
        self.assertFalse(OperacionEnlace.objects.filter(id=enlace.id).exists())
        self.assertTrue(OperacionEnlace.objects.filter(id=enlace_ajeno.id).exists())

    def test_usuario_sin_permiso_no_puede_crear_ni_eliminar(self):
        enlace = self.crear_enlace()
        self.client.force_login(self.other_user)

        create_response = self.client.post(
            self.create_url,
            {"titulo": "No permitido", "url": "https://example.com/no"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        delete_response = self.client.post(
            self.delete_url,
            {"enlace_id": enlace.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(delete_response.status_code, 403)
        self.assertTrue(OperacionEnlace.objects.filter(id=enlace.id).exists())

    def test_enlaces_requieren_ajax_y_post(self):
        create_response = self.client.post(
            self.create_url,
            {"titulo": "Sin AJAX", "url": "https://example.com/sin-ajax"},
        )
        enlace = self.crear_enlace()
        delete_response = self.client.post(self.delete_url, {"enlace_id": enlace.id})
        method_response = self.client.get(self.create_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(delete_response.status_code, 400)
        self.assertEqual(method_response.status_code, 405)
        self.assertFalse(OperacionEnlace.objects.filter(operacion=self.operacion, titulo="Sin AJAX").exists())
        self.assertTrue(OperacionEnlace.objects.filter(id=enlace.id).exists())


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesEtiquetasAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="tags_owner", password="pass")
        self.other_user = User.objects.create_user(username="tags_other", password="pass")
        self.operacion = Operacion.objects.create(titulo="Operacion con etiquetas", creado_por=self.owner)
        self.other_operacion = Operacion.objects.create(titulo="Otra operacion", creado_por=self.owner)
        self.etiqueta = OperacionEtiqueta.objects.create(nombre="Urgente", color="#FF0000")
        self.assign_url = reverse("operaciones:agregar_etiqueta_operacion", args=[self.operacion.id])
        self.create_url = reverse("operaciones:crear_etiqueta_operacion", args=[self.operacion.id])
        self.client = Client()
        self.client.force_login(self.owner)

    def remove_url(self, etiqueta):
        return reverse("operaciones:quitar_etiqueta_operacion", args=[self.operacion.id, etiqueta.id])

    def test_asigna_etiqueta_existente_con_contrato_granular_e_idempotente(self):
        response = self.client.post(
            self.assign_url,
            {"etiqueta": self.etiqueta.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["tags_count"], 1)
        self.assertIn('data-operacion-tags-section="1"', data["tags_html"])
        self.assertEqual(data["tags"], [{"id": self.etiqueta.id, "nombre": "Urgente", "color": "#FF0000"}])

        repeated = self.client.post(
            self.assign_url,
            {"etiqueta": self.etiqueta.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["tags_count"], 1)
        self.assertEqual(self.operacion.etiquetas.count(), 1)

    def test_crea_etiqueta_nueva_y_la_asigna(self):
        response = self.client.post(
            self.create_url,
            {"nombre": "Finanzas", "color": "#00AA11"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        etiqueta = OperacionEtiqueta.objects.get(nombre="Finanzas")
        self.assertEqual(etiqueta.color, "#00AA11")
        self.assertIn(etiqueta, self.operacion.etiquetas.all())
        self.assertEqual(data["tags_count"], 1)

    def test_reutiliza_etiqueta_existente_sin_modificar_el_catalogo(self):
        response = self.client.post(
            self.create_url,
            {"nombre": "urgente", "color": "#00AA11"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.etiqueta.refresh_from_db()
        self.assertEqual(OperacionEtiqueta.objects.filter(nombre__iexact="urgente").count(), 1)
        self.assertEqual(self.etiqueta.color, "#FF0000")
        self.assertIn(self.etiqueta, self.operacion.etiquetas.all())

    def test_errores_de_validacion_devuelven_solo_la_seccion(self):
        response = self.client.post(
            self.create_url,
            {"nombre": "", "color": "azul"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn('data-operacion-tags-section="1"', data["tags_html"])
        self.assertEqual(data["tags_count"], 0)
        self.assertFalse(self.operacion.etiquetas.exists())

    def test_quita_solo_la_relacion_y_conserva_catalogo_y_otra_operacion(self):
        self.operacion.etiquetas.add(self.etiqueta)
        self.other_operacion.etiquetas.add(self.etiqueta)

        response = self.client.post(
            self.remove_url(self.etiqueta),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["tags_count"], 0)
        self.assertTrue(OperacionEtiqueta.objects.filter(id=self.etiqueta.id).exists())
        self.assertFalse(self.operacion.etiquetas.filter(id=self.etiqueta.id).exists())
        self.assertTrue(self.other_operacion.etiquetas.filter(id=self.etiqueta.id).exists())

    def test_usuario_sin_permiso_no_puede_administrar_etiquetas(self):
        self.operacion.etiquetas.add(self.etiqueta)
        self.client.force_login(self.other_user)

        assign_response = self.client.post(
            self.assign_url,
            {"etiqueta": self.etiqueta.id},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        remove_response = self.client.post(
            self.remove_url(self.etiqueta),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(assign_response.status_code, 403)
        self.assertEqual(remove_response.status_code, 403)
        self.assertTrue(self.operacion.etiquetas.filter(id=self.etiqueta.id).exists())

    def test_etiquetas_requieren_ajax_y_post(self):
        assign_response = self.client.post(self.assign_url, {"etiqueta": self.etiqueta.id})
        method_response = self.client.get(self.create_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(assign_response.status_code, 400)
        self.assertEqual(method_response.status_code, 405)
        self.assertFalse(self.operacion.etiquetas.exists())


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesOpcionesAjaxTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.owner = User.objects.create_user(username="options_owner", password="pass")
        self.other_user = User.objects.create_user(username="options_other", password="pass")
        self.operacion = Operacion.objects.create(titulo="Operacion con opciones", creado_por=self.owner)
        self.other_operacion = Operacion.objects.create(titulo="Otra operacion", creado_por=self.owner)
        self.opcion = OperacionOpcion.objects.create(nombre="Requiere factura")
        self.opcion_extra = OperacionOpcion.objects.create(nombre="Requiere seguro")
        self.update_url = reverse("operaciones:actualizar_opciones_operacion", args=[self.operacion.id])
        self.create_url = reverse("operaciones:crear_opcion_operacion", args=[self.operacion.id])
        self.client = Client()
        self.client.force_login(self.owner)

    def remove_url(self, opcion):
        return reverse("operaciones:quitar_opcion_operacion", args=[self.operacion.id, opcion.id])

    def test_actualiza_la_relacion_y_devuelve_solo_la_seccion(self):
        response = self.client.post(
            self.update_url,
            {"opciones": [self.opcion.id, self.opcion_extra.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["id"], self.operacion.id)
        self.assertEqual(data["options_count"], 2)
        self.assertIn('data-operacion-options-section="1"', data["options_html"])
        self.assertIn('data-operacion-detail-options-count="1"', data["options_html"])
        self.assertNotIn('data-operacion-modal-form="1"', data["options_html"])
        self.assertEqual(
            data["options"],
            [
                {"id": self.opcion.id, "nombre": "Requiere factura"},
                {"id": self.opcion_extra.id, "nombre": "Requiere seguro"},
            ],
        )

    def test_actualizacion_vacia_desasigna_sin_eliminar_catalogo(self):
        self.operacion.opciones.add(self.opcion)
        response = self.client.post(self.update_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["options_count"], 0)
        self.assertFalse(self.operacion.opciones.exists())
        self.assertTrue(OperacionOpcion.objects.filter(id=self.opcion.id).exists())

    def test_crea_y_asigna_opcion_nueva_de_forma_idempotente(self):
        response = self.client.post(
            self.create_url,
            {"nombre": "Requiere pedimento"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        opcion = OperacionOpcion.objects.get(nombre="Requiere pedimento")
        self.assertIn(opcion, self.operacion.opciones.all())
        repeated = self.client.post(
            self.create_url,
            {"nombre": "Requiere pedimento"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(repeated.status_code, 200)
        self.assertEqual(repeated.json()["options_count"], 1)
        self.assertEqual(OperacionOpcion.objects.filter(nombre="Requiere pedimento").count(), 1)

    def test_error_de_validacion_devuelve_la_seccion_y_no_crea_opcion(self):
        response = self.client.post(
            self.create_url,
            {"nombre": "   "},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["success"])
        self.assertIn('data-operacion-options-section="1"', data["options_html"])
        self.assertEqual(data["options_count"], 0)
        self.assertFalse(OperacionOpcion.objects.filter(nombre="").exists())

    def test_quita_solo_la_relacion_y_conserva_catalogo_y_otra_operacion(self):
        self.operacion.opciones.add(self.opcion)
        self.other_operacion.opciones.add(self.opcion)

        response = self.client.post(self.remove_url(self.opcion), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertEqual(response.json()["options_count"], 0)
        self.assertTrue(OperacionOpcion.objects.filter(id=self.opcion.id).exists())
        self.assertFalse(self.operacion.opciones.filter(id=self.opcion.id).exists())
        self.assertTrue(self.other_operacion.opciones.filter(id=self.opcion.id).exists())

    def test_usuario_sin_permiso_no_puede_administrar_opciones(self):
        self.operacion.opciones.add(self.opcion)
        self.client.force_login(self.other_user)

        update_response = self.client.post(
            self.update_url,
            {"opciones": [self.opcion_extra.id]},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        create_response = self.client.post(
            self.create_url,
            {"nombre": "No permitida"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        remove_response = self.client.post(self.remove_url(self.opcion), HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(update_response.status_code, 403)
        self.assertEqual(create_response.status_code, 403)
        self.assertEqual(remove_response.status_code, 403)
        self.assertTrue(self.operacion.opciones.filter(id=self.opcion.id).exists())
        self.assertFalse(OperacionOpcion.objects.filter(nombre="No permitida").exists())

    def test_opciones_requieren_ajax_y_post(self):
        update_response = self.client.post(self.update_url, {"opciones": [self.opcion.id]})
        create_response = self.client.post(self.create_url, {"nombre": "Sin AJAX"})
        method_response = self.client.get(self.create_url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(update_response.status_code, 400)
        self.assertEqual(create_response.status_code, 400)
        self.assertEqual(method_response.status_code, 405)
        self.assertFalse(self.operacion.opciones.exists())
        self.assertFalse(OperacionOpcion.objects.filter(nombre="Sin AJAX").exists())
