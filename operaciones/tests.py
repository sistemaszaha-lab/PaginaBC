from pathlib import Path
import re
from datetime import timedelta
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.test.utils import override_settings
from django.test.utils import CaptureQueriesContext
from django.db import connection
from django.middleware.csrf import get_token
from django.http import HttpRequest
from django.urls import resolve, reverse
from django.utils import timezone

from .models import (
    Operacion,
    OperacionArchivo,
    OperacionColumna,
    OperacionComentario,
    OperacionEnlace,
    OperacionEtiqueta,
    OperacionOpcion,
)
from solicitudes.models import Referencia
from clientes.models import Cliente
from cuenta_gastos.models import CuentaGastos
from cuenta_gastos.services import crear_cuenta_gastos_desde_operacion_si_corresponde

PANEL_JS_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "operaciones"
    / "js"
    / "panel_operaciones.js"
)


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

    def test_crea_operacion_pickup_vinculada_y_no_duplica(self):
        url = reverse("operaciones:enviar_referencia_a_operaciones", args=[self.referencia.pk])
        self.assertEqual(self.client.get(url).status_code, 200)
        response = self.client.post(url, {
            "titulo": "Referencia BC261001",
            "descripcion": "detalle",
            "estado": Operacion.Estado.PENDIENTE,
        })
        self.assertRedirects(response, reverse("operaciones:panel_operaciones"))
        operacion = Operacion.objects.get(referencia_origen=self.referencia)
        self.assertEqual(operacion.estado, Operacion.Estado.COORDINAR_PICKUP)
        self.assertIsNotNone(operacion.columna)
        self.assertEqual(operacion.columna.codigo, Operacion.Estado.COORDINAR_PICKUP)
        self.assertNotEqual(operacion.estado, Operacion.Estado.PENDIENTE)
        self.assertEqual(operacion.creado_por, self.usuario)
        self.referencia.refresh_from_db()
        self.assertEqual(self.referencia.referencia, "BC261001")
        self.assertEqual(self.referencia.ejecutivo, self.usuario)
        self.assertEqual(self.client.get(url).status_code, 302)
        self.assertEqual(Operacion.objects.filter(referencia_origen=self.referencia).count(), 1)

    def test_administrador_y_otro_ejecutivo_pueden_abrir_referencia_ajena(self):
        User = get_user_model()
        admin = User.objects.create_user(username="admin-conv-op", password="pass", is_superuser=True)
        otro = User.objects.create_user(username="otro-conv-op", password="pass")
        url = reverse("operaciones:enviar_referencia_a_operaciones", args=[self.referencia.pk])
        self.client.force_login(admin)
        self.assertEqual(self.client.get(url).status_code, 200)
        self.client.force_login(otro)
        self.assertEqual(self.client.get(url).status_code, 200)

    def test_conversion_requiere_autenticacion(self):
        self.client.logout()
        response = self.client.get(reverse("operaciones:enviar_referencia_a_operaciones", args=[self.referencia.pk]))
        self.assertEqual(response.status_code, 302)

    def test_boton_aparece_para_ejecutivo_no_asignado(self):
        User = get_user_model()
        otro = User.objects.create_user(username="otro-boton-op", password="pass")
        self.client.force_login(otro)
        response = self.client.get(reverse("lista_referencias"))
        self.assertContains(response, "Enviar a Operaciones")


@override_settings(
    STORAGES={"staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"}}
)
class OperacionACuentaGastosTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_user(username="movedor-cg", password="pass")
        self.asignado = User.objects.create_user(username="asignado-cg", password="pass")
        self.cliente = Cliente.objects.create(nombre="CLIENTE CG")
        self.operacion = Operacion.objects.create(
            titulo="Operación origen", descripcion="Descripción origen", cliente=self.cliente,
            prioridad=Operacion.Prioridad.ALTA, fecha_vencimiento="2026-08-01",
            creado_por=self.usuario,
        )
        self.operacion.asignados.add(self.asignado)
        self.client.force_login(self.usuario)

    def test_mover_a_solicitud_cuenta_gastos_crea_tarjeta_mapeada(self):
        response = self.client.post(
            reverse("operaciones:mover_operacion", args=[self.operacion.pk]),
            {"estado": Operacion.Estado.SOLICITUD_CUENTA_GASTOS},
        )
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["cuenta_gastos_creada"])
        cuenta = CuentaGastos.objects.get(operacion_origen=self.operacion)
        self.assertEqual(cuenta.estado, CuentaGastos.Estado.SOLICITUD_CUENTA_GASTOS)
        self.assertEqual(cuenta.titulo, self.operacion.titulo)
        self.assertEqual(cuenta.descripcion, self.operacion.descripcion)
        self.assertEqual(cuenta.cliente, self.cliente)
        self.assertEqual(cuenta.prioridad, CuentaGastos.Prioridad.ALTA)
        self.assertEqual(str(cuenta.fecha_vencimiento), str(self.operacion.fecha_vencimiento))
        self.assertEqual(list(cuenta.asignados.all()), [self.asignado])
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.SOLICITUD_CUENTA_GASTOS)
        self.assertEqual(self.operacion.columna.codigo, Operacion.Estado.SOLICITUD_CUENTA_GASTOS)

    def test_servicio_es_idempotente_y_no_crea_fuera_del_estado_destino(self):
        cuenta, creada = crear_cuenta_gastos_desde_operacion_si_corresponde(
            self.operacion, creado_por=self.usuario
        )
        self.assertIsNone(cuenta)
        self.assertFalse(creada)
        self.operacion.estado = Operacion.Estado.SOLICITUD_CUENTA_GASTOS
        self.operacion.save(update_fields=["estado"])
        primera, creada = crear_cuenta_gastos_desde_operacion_si_corresponde(
            self.operacion, creado_por=self.usuario
        )
        segunda, creada_dos = crear_cuenta_gastos_desde_operacion_si_corresponde(
            self.operacion, creado_por=self.usuario
        )
        self.assertTrue(creada)
        self.assertFalse(creada_dos)
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(CuentaGastos.objects.filter(operacion_origen=self.operacion).count(), 1)


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
        self.assertNotContains(resp, 'class="operaciones-inline-form"')
        self.assertContains(resp, '<div class="px-3 pt-3 d-none" data-operacion-inline-container="1"', count=1)
        self.assertContains(resp, '<div data-operacion-inline-form-slot="1"></div>', count=1)
        self.assertContains(resp, 'data-operacion-quick-edit-open="1"')
        self.assertContains(resp, 'id="OperacionDetalleDrawer"')
        self.assertContains(resp, 'id="OperacionDetalleDrawerContent"')
        self.assertContains(resp, "Pick up")

    def test_panel_no_crea_el_formulario_inline_en_el_get_inicial(self):
        with patch("operaciones.views.OperacionInlineCreateForm") as inline_form_class:
            resp = self.client.get(reverse("operaciones:panel_operaciones"))

        self.assertEqual(resp.status_code, 200)
        inline_form_class.assert_not_called()
        self.assertNotIn("inline_form", resp.context)
        self.assertNotContains(resp, 'class="operaciones-inline-form"')


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
            "prioridad": "MEDIA",  # Queremos cambiar solo la prioridad
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
        self.assertEqual(response.json()["status"], "ok")
        self.assertEqual(response.json()["id"], self.operacion.id)
        self.assertEqual(response.json()["estado"], Operacion.Estado.SEGUROS)
        self.assertEqual(response.json()["estado_label"], "Seguros")
        self.assertFalse(response.json()["cuenta_gastos_creada"])
        self.assertIsNone(response.json()["cuenta_gastos_id"])
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

    def test_ejecutivo_no_asignado_puede_mover(self):
        self.client.force_login(self.other_user)

        response = self.client.post(self.move_url, {"estado": Operacion.Estado.SEGUROS})

        self.assertEqual(response.status_code, 200)
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.estado, Operacion.Estado.SEGUROS)

    def test_mover_requiere_autenticacion(self):
        response = self.client.post(self.move_url, {"estado": Operacion.Estado.SEGUROS})
        self.assertEqual(response.status_code, 302)

    def test_mover_requiere_post(self):
        self.client.force_login(self.owner)

        response = self.client.get(self.move_url)

        self.assertEqual(response.status_code, 405)


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesColumnasDinamicasTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.user = User.objects.create_user(username="ops-columns", password="pass", is_superuser=True)
        self.client = Client()
        self.client.force_login(self.user)

    def test_columnas_base_se_crean_en_orden_historico(self):
        codigos = list(
            OperacionColumna.objects.filter(activa=True)
            .order_by("orden", "id")
            .values_list("codigo", flat=True)
        )
        self.assertEqual(
            codigos,
            [
                Operacion.Estado.PENDIENTE,
                Operacion.Estado.SEGUROS,
                Operacion.Estado.PRUEBA_VALOR,
                Operacion.Estado.EN_ADUANA,
                Operacion.Estado.TRANSITO_NACIONAL,
                Operacion.Estado.COORDINAR_PICKUP,
                Operacion.Estado.TRANSITO_INTERNACIONAL,
                Operacion.Estado.EXPEDIENTE_CG,
                Operacion.Estado.SOLICITUD_CUENTA_GASTOS,
            ],
        )

    def test_crea_y_edita_columna_personalizada(self):
        create_response = self.client.post(
            reverse("operaciones:columna_crear"),
            {"nombre": "Documentos listos"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(create_response.status_code, 201)
        columna = OperacionColumna.objects.get(nombre="Documentos listos")
        self.assertTrue(columna.codigo.startswith("DOCUMENTOS_LISTOS"))

        edit_response = self.client.post(
            reverse("operaciones:columna_editar", args=[columna.pk]),
            {"nombre": "Documentos verificados"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(edit_response.status_code, 200)
        columna.refresh_from_db()
        self.assertEqual(columna.nombre, "Documentos verificados")
        self.assertTrue(columna.activa)

    def test_no_elimina_columna_base(self):
        base = OperacionColumna.objects.get(codigo=Operacion.Estado.PENDIENTE)

        response = self.client.post(
            reverse("operaciones:columna_eliminar", args=[base.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        base.refresh_from_db()
        self.assertTrue(base.activa)

    def test_eliminar_columna_personalizada_reasigna_operaciones_y_sincroniza_estado(self):
        origen = OperacionColumna.objects.create(
            nombre="Temporal",
            codigo="TEMPORAL",
            orden=50,
            creada_por=self.user,
        )
        destino = OperacionColumna.objects.get(
            codigo=Operacion.Estado.SOLICITUD_CUENTA_GASTOS
        )
        cliente = Cliente.objects.create(nombre="Cliente columnas")
        operacion = Operacion.objects.create(
            titulo="Mover al eliminar",
            cliente=cliente,
            columna=origen,
            estado=origen.codigo,
            creado_por=self.user,
        )

        response = self.client.post(
            reverse("operaciones:columna_eliminar", args=[origen.pk]),
            {"columna_destino_id": destino.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        operacion.refresh_from_db()
        origen.refresh_from_db()
        self.assertFalse(origen.activa)
        self.assertEqual(operacion.estado, destino.codigo)
        self.assertEqual(operacion.columna_id, destino.pk)
        self.assertTrue(
            CuentaGastos.objects.filter(operacion_origen=operacion).exists()
        )


@override_settings(
    STORAGES={
        "staticfiles": {"BACKEND": "django.contrib.staticfiles.storage.StaticFilesStorage"},
    }
)
class OperacionesCopiarPegarTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin-copy-op",
            password="pass",
            is_superuser=True,
            first_name="Admin",
        )
        self.ejecutivo = User.objects.create_user(
            username="ejecutivo-copy-op",
            password="pass",
            first_name="Ejecutivo",
        )
        self.asignado = User.objects.create_user(
            username="asignado-copy-op",
            password="pass",
            first_name="Asignado",
        )
        self.cliente = Cliente.objects.create(nombre="Cliente copia")
        self.columna_pendiente = OperacionColumna.objects.get(
            codigo=Operacion.Estado.PENDIENTE
        )
        self.columna_seguros = OperacionColumna.objects.get(
            codigo=Operacion.Estado.SEGUROS
        )
        self.columna_cg = OperacionColumna.objects.get(
            codigo=Operacion.Estado.SOLICITUD_CUENTA_GASTOS
        )
        self.referencia = Referencia.objects.create(
            referencia="BC261099",
            consecutivo=99,
            ejecutivo=self.admin,
            cliente="Cliente copia",
            servicio="importacion",
        )
        self.etiqueta = OperacionEtiqueta.objects.create(
            nombre="Urgente copia",
            color="#FF0000",
        )
        self.opcion = OperacionOpcion.objects.create(nombre="Requiere seguro")
        self.original = Operacion.objects.create(
            titulo="Operacion original",
            descripcion="Descripcion original",
            cliente=self.cliente,
            estado=self.columna_pendiente.codigo,
            columna=self.columna_pendiente,
            prioridad=Operacion.Prioridad.ALTA,
            creado_por=self.admin,
            fecha_vencimiento="2026-08-10",
            referencia_origen=self.referencia,
        )
        self.original.asignados.add(self.asignado)
        self.original.etiquetas.add(self.etiqueta)
        self.original.opciones.add(self.opcion)
        OperacionComentario.objects.create(
            operacion=self.original,
            usuario=self.admin,
            comentario="Comentario original",
        )
        OperacionArchivo.objects.create(
            operacion=self.original,
            archivo=SimpleUploadedFile("origen.txt", b"hola"),
            subido_por=self.admin,
        )
        OperacionEnlace.objects.create(
            operacion=self.original,
            titulo="Documento",
            url="https://example.com/doc",
            creado_por=self.admin,
        )
        self.client = Client()

    def _paste_url(self, columna):
        return reverse("operaciones:tarjeta_pegar", args=[columna.pk])

    def test_administrador_puede_copiar_y_pegar_sin_modificar_original(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            self._paste_url(self.columna_seguros),
            {"tarjeta_id": self.original.pk, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertNotEqual(data["tarjeta_id"], self.original.pk)
        copia = Operacion.objects.get(pk=data["tarjeta_id"])
        self.original.refresh_from_db()
        self.assertEqual(self.original.estado, self.columna_pendiente.codigo)
        self.assertEqual(copia.columna_id, self.columna_seguros.pk)
        self.assertEqual(copia.estado, self.columna_seguros.codigo)
        self.assertEqual(copia.titulo, self.original.titulo)
        self.assertEqual(copia.descripcion, self.original.descripcion)
        self.assertEqual(copia.cliente, self.original.cliente)
        self.assertEqual(copia.prioridad, self.original.prioridad)
        self.assertEqual(copia.fecha_vencimiento, self.original.fecha_vencimiento)
        self.assertEqual(copia.creado_por, self.admin)
        self.assertEqual(list(copia.asignados.all()), [self.asignado])
        self.assertEqual(list(copia.etiquetas.all()), [self.etiqueta])
        self.assertEqual(list(copia.opciones.all()), [self.opcion])
        self.assertFalse(copia.comentarios.exists())
        self.assertFalse(copia.archivos.exists())
        self.assertFalse(copia.enlaces.exists())
        self.assertIsNone(copia.referencia_origen)
        self.assertFalse(
            CuentaGastos.objects.filter(operacion_origen=copia).exists()
        )
        self.assertIn('data-panel-operacion-card="1"', data["html"])
        move_response = self.client.post(
            reverse("operaciones:mover_operacion", args=[copia.pk]),
            {"estado": Operacion.Estado.EN_ADUANA},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(move_response.status_code, 200)

    def test_ejecutivo_puede_pegar_y_la_cuenta_gastos_se_crea_para_la_copia(self):
        self.original.estado = self.columna_cg.codigo
        self.original.columna = self.columna_cg
        self.original.save()
        cuenta_original, creada = crear_cuenta_gastos_desde_operacion_si_corresponde(
            self.original,
            creado_por=self.admin,
        )
        self.assertTrue(creada)
        self.client.force_login(self.ejecutivo)

        response = self.client.post(
            self._paste_url(self.columna_cg),
            {"tarjeta_id": self.original.pk, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        copia = Operacion.objects.get(pk=response.json()["tarjeta_id"])
        cuenta_copia = CuentaGastos.objects.get(operacion_origen=copia)
        self.assertNotEqual(copia.pk, self.original.pk)
        self.assertEqual(copia.creado_por, self.ejecutivo)
        self.assertEqual(copia.columna_id, self.columna_cg.pk)
        self.assertEqual(copia.estado, self.columna_cg.codigo)
        self.assertNotEqual(cuenta_copia.pk, cuenta_original.pk)
        self.assertEqual(cuenta_copia.operacion_origen_id, copia.pk)
        self.assertEqual(
            CuentaGastos.objects.filter(operacion_origen=copia).count(),
            1,
        )
        again = self.client.post(
            self._paste_url(self.columna_cg),
            {"tarjeta_id": self.original.pk, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(again.status_code, 201)
        self.assertEqual(CuentaGastos.objects.count(), 3)

    def test_columna_inexistente_o_inactiva_y_operacion_inexistente_no_crean_registros(self):
        self.client.force_login(self.admin)
        before = Operacion.objects.count()

        missing_column = self.client.post(
            reverse("operaciones:tarjeta_pegar", args=[999999]),
            {"tarjeta_id": self.original.pk, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(missing_column.status_code, 404)

        custom = OperacionColumna.objects.create(
            nombre="Temporal inactiva",
            codigo="TEMP_INACTIVA",
            orden=99,
            activa=False,
            creada_por=self.admin,
        )
        inactive = self.client.post(
            self._paste_url(custom),
            {"tarjeta_id": self.original.pk, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(inactive.status_code, 404)

        missing_card = self.client.post(
            self._paste_url(self.columna_seguros),
            {"tarjeta_id": 999999, "modulo": "operaciones"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(missing_card.status_code, 404)
        self.assertEqual(Operacion.objects.count(), before)

    def test_datos_invalidos_y_modulo_incorrecto_se_rechazan(self):
        self.client.force_login(self.admin)
        before = Operacion.objects.count()
        for payload in (
            {"tarjeta_id": "", "modulo": "operaciones"},
            {"tarjeta_id": "abc", "modulo": "operaciones"},
            {"tarjeta_id": self.original.pk, "modulo": "garantias"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post(
                    self._paste_url(self.columna_seguros),
                    payload,
                    HTTP_X_REQUESTED_WITH="XMLHttpRequest",
                )
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
        self.assertEqual(Operacion.objects.count(), before)


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
        self.inline_form_url = reverse("operaciones:formulario_operacion_inline")
        self.columna_inicial = OperacionColumna.objects.filter(
            activa=True
        ).order_by("orden", "id").first()

    def test_endpoint_get_devuelve_formulario_completo_sin_crear_operaciones(self):
        response = self.client.get(self.inline_form_url)

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="operaciones-inline-form"', count=1)
        self.assertContains(response, 'name="titulo"')
        self.assertContains(response, 'name="descripcion"')
        self.assertContains(response, 'name="cliente"')
        self.assertContains(response, 'name="prioridad"')
        self.assertContains(response, 'name="fecha_vencimiento"')
        self.assertContains(response, 'name="asignados"')
        self.assertContains(response, 'name="etiquetas"')
        self.assertContains(response, 'name="archivos"')
        self.assertContains(response, 'name="enlace_titulo"')
        self.assertContains(response, 'name="enlace_url"')
        self.assertFalse(Operacion.objects.exists())

    def test_endpoint_get_formulario_requiere_autenticacion(self):
        response = Client().get(self.inline_form_url)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response["Location"])

    def test_endpoint_formulario_acepta_usuario_autenticado_regular(self):
        self.assertFalse(self.user.is_superuser)

        response = self.client.get(self.inline_form_url)

        self.assertEqual(response.status_code, 200)

    def test_endpoint_formulario_solo_acepta_get(self):
        response = self.client.post(self.inline_form_url)

        self.assertEqual(response.status_code, 405)

    def test_crea_operacion_en_el_estado_de_la_columna(self):
        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion inline",
                "prioridad": Operacion.Prioridad.ALTA,
                "estado": self.columna_inicial.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["operacion_id"], data["id"])
        self.assertEqual(data["estado"], self.columna_inicial.codigo)
        self.assertEqual(data["message"], "Operacion creada correctamente.")
        self.assertIn(f'id="panel-operacion-{data["operacion_id"]}"', data["html"])
        self.assertIn('data-panel-operacion-card="1"', data["html"])
        self.assertIn('data-operacion-state-select="1"', data["html"])

        operacion = Operacion.objects.get(pk=data["id"])
        self.assertEqual(operacion.titulo, "Operacion inline")
        self.assertEqual(operacion.estado, self.columna_inicial.codigo)
        self.assertEqual(operacion.prioridad, Operacion.Prioridad.ALTA)
        self.assertEqual(operacion.creado_por, self.user)

    def test_creacion_inline_solo_permite_la_primera_columna_activa(self):
        columnas = list(
            OperacionColumna.objects.filter(activa=True).order_by("orden", "id")
        )
        permitida = columnas[0]
        bloqueada = columnas[1]

        response = self.client.post(
            self.inline_url,
            {"titulo": "Operacion permitida", "estado": permitida.codigo},
        )
        self.assertEqual(response.status_code, 201)

        response = self.client.post(
            self.inline_url,
            {"titulo": "Operacion bloqueada", "estado": bloqueada.codigo},
        )
        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["message"],
            "Solo se pueden crear tarjetas desde la primera columna activa.",
        )
        self.assertFalse(Operacion.objects.filter(titulo="Operacion bloqueada").exists())

    def test_crea_operacion_con_vencimiento_asignados_y_etiquetas(self):
        User = get_user_model()
        asignado = User.objects.create_user(username="inline_asignado", first_name="Ana")
        etiqueta = OperacionEtiqueta.objects.create(nombre="Urgente", color="#FF0000")

        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion con relaciones",
                "fecha_vencimiento": "2026-08-10",
                "asignados": [asignado.pk],
                "etiquetas": [etiqueta.pk],
                "estado": self.columna_inicial.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        operacion = Operacion.objects.get(pk=data["id"])
        self.assertEqual(str(operacion.fecha_vencimiento), "2026-08-10")
        self.assertEqual(list(operacion.asignados.all()), [asignado])
        self.assertEqual(list(operacion.etiquetas.all()), [etiqueta])
        self.assertIn("Urgente", data["html"])
    def test_crea_operacion_con_titulo_cliente_y_prioridad(self):
        cliente = Cliente.objects.create(nombre="Cliente inline")
        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion inline completa",
                "cliente": cliente.pk,
                "prioridad": Operacion.Prioridad.ALTA,
                "estado": self.columna_inicial.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["estado"], self.columna_inicial.codigo)
        operacion = Operacion.objects.get(pk=data["id"])
        self.assertEqual(operacion.cliente, cliente)
        self.assertEqual(operacion.prioridad, Operacion.Prioridad.ALTA)

    def test_crea_operacion_con_descripcion_archivos_y_enlaces(self):
        archivo = SimpleUploadedFile(
            "evidencia.pdf",
            b"%PDF-1.4 test file",
            content_type="application/pdf",
        )

        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion con soporte",
                "descripcion": "Descripcion extensa",
                "estado": self.columna_inicial.codigo,
                "enlace_titulo": ["Factura"],
                "enlace_url": ["https://example.com/factura"],
                "archivos": [archivo],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201)
        operacion = Operacion.objects.get(pk=response.json()["id"])
        self.assertEqual(operacion.descripcion, "Descripcion extensa")
        self.assertEqual(operacion.archivos.count(), 1)
        self.assertEqual(operacion.enlaces.count(), 1)
        self.assertEqual(operacion.enlaces.first().titulo, "Factura")
        self.assertEqual(operacion.enlaces.first().url, "https://example.com/factura")

    def test_errores_de_formulario_devuelven_el_parcial_inline(self):
        response = self.client.post(
            self.inline_url,
            {"titulo": "", "estado": self.columna_inicial.codigo},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("titulo", data["errors"])
        self.assertEqual(data["error_code"], "FORM_INVALID")
        self.assertIn('data-operacion-inline-form="1"', data["html_form"])
        self.assertIn("Este campo es obligatorio", data["html_form"])
        self.assertIn(
            f'name="estado" value="{self.columna_inicial.codigo}"',
            data["html_form"],
        )
        self.assertFalse(Operacion.objects.exists())

    def test_enlaces_invalidos_devuelven_error_y_mantienen_formulario_abierto(self):
        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion con enlace invalido",
                "estado": self.columna_inicial.codigo,
                "enlace_titulo": ["Documento"],
                "enlace_url": ["nota-invalida"],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertIn("enlaces", data["errors"])
        self.assertIn('data-operacion-inline-form="1"', data["html_form"])
        self.assertFalse(Operacion.objects.exists())

    def test_estado_vacio_etiqueta_visual_y_desconocido_se_rechazan(self):
        for estado in ("", "Pendientes", "NO_EXISTE"):
            with self.subTest(estado=estado):
                response = self.client.post(
                    self.inline_url,
                    {"titulo": "Operacion invalida", "estado": estado},
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["error_code"], "INVALID_STATE")
                self.assertFalse(response.json()["ok"])
        self.assertFalse(Operacion.objects.exists())

    def test_estado_duplicado_se_rechaza(self):
        response = self.client.post(
            self.inline_url,
            {
                "titulo": "Operacion con estado duplicado",
                "estado": [
                    Operacion.Estado.PENDIENTE,
                    Operacion.Estado.EN_ADUANA,
                ],
            },
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error_code"], "INVALID_STATE")
        self.assertFalse(Operacion.objects.exists())

    def test_tablero_renderiza_placeholder_vacio_y_choices_exactos(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        html = response.content.decode()
        choices = list(Operacion._meta.get_field("estado").choices)

        for estado, etiqueta in choices:
            with self.subTest(estado=estado):
                self.assertIn(f'data-estado="{estado}"', html)
                self.assertIn(etiqueta, html)

        self.assertEqual(
            html.count('<input type="hidden" name="estado"'),
            0,
        )
        self.assertEqual(
            html.count('class="btn btn-sm operaciones-column__add-btn"'),
            1,
        )
        self.assertEqual(html.count('class="operaciones-inline-form"'), 0)
        self.assertIn('<div data-operacion-inline-form-slot="1"></div>', html)
        self.assertNotIn('name="estado" value="Pendientes"', html)

    def test_panel_mueve_alta_manual_a_la_nueva_primera_columna_tras_reordenar(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        html = response.content.decode()
        self.assertEqual(html.count('data-operacion-inline-open="1"'), 1)

        columnas = list(
            OperacionColumna.objects.filter(activa=True).order_by("orden", "id")
        )
        nuevo_orden = [str(columna.pk) for columna in reversed(columnas)]
        reorder_response = self.client.post(
            reverse("operaciones:columna_reordenar"),
            {"columnas[]": nuevo_orden},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(reorder_response.status_code, 200)

        nuevo_primero = OperacionColumna.objects.filter(
            activa=True
        ).order_by("orden", "id").first()
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        html = response.content.decode()
        self.assertEqual(html.count('data-operacion-inline-open="1"'), 1)
        self.assertIn(f'data-columna-id="{nuevo_primero.pk}"', html)

    def test_javascript_configura_estado_y_destino_del_formulario_compartido(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        html = response.content.decode()
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('id="panel-operaciones-config"', html)
        self.assertIn("/static/operaciones/js/panel_operaciones.js", html)
        self.assertNotIn("inlineRequestedTarget = {estado};", html)
        self.assertIn("const estado = inlineOpenButton.dataset.estado", javascript)
        self.assertIn("inlineRequestedTarget = {estado};", javascript)
        self.assertIn("loadSharedInlineForm();", javascript)
        self.assertIn("const form = resetSharedInlineForm(target.estado);", javascript)
        self.assertIn("stateInput.value = estado;", javascript)
        self.assertIn("targetLabel.textContent = estadoLabel;", javascript)
        self.assertIn("actions.insertAdjacentElement('afterend', inlineContainer);", javascript)

    def test_javascript_carga_formulario_una_sola_vez_y_permite_reintento(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        html = response.content.decode()
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn(
            '"inlineFormUrl": "/operaciones/nueva/inline/formulario/"',
            html,
        )
        self.assertIn("const inlineFormUrl = config.inlineFormUrl;", javascript)
        self.assertIn("if (inlineFormLoaded)", javascript)
        self.assertIn("if (inlineFormLoadPromise) return inlineFormLoadPromise;", javascript)
        self.assertIn("setInlineOpenButtonsLoading(true);", javascript)
        self.assertIn("inlineFormLoadPromise = getHtml(inlineFormUrl)", javascript)
        self.assertIn("inlineFormLoadPromise = null;", javascript)
        self.assertIn("showInlineLoadFeedback({error: true});", javascript)

    def test_javascript_evitar_insertar_tarjeta_ajena_al_filtro_activo(self):
        response = self.client.get(
            reverse("operaciones:panel_operaciones"),
            {"usuario": self.user.pk},
        )
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("const selectedUserId = document.getElementById('OperacionesUserFilter')?.value", javascript)
        self.assertIn("const shouldInsertCard = !selectedUserId || assignedUserIds.includes(selectedUserId);", javascript)
        self.assertIn("if (shouldInsertCard && !insertCardFromHtml(targetColumn, data.html))", javascript)

    def test_javascript_tom_select_se_inicializa_y_destruye_una_sola_vez(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("if (select.tomselect) return;", javascript)
        self.assertIn("if (select.tomselect) select.tomselect.destroy();", javascript)
        self.assertEqual(javascript.count("root.addEventListener('submit', (e) => {"), 1)

    def test_javascript_comentarios_usa_delegacion_en_document_para_drawer_y_modal(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 200)
        self.assertIn("document.addEventListener('submit', (e) => {", javascript)
        self.assertIn("const commentForm = e.target.closest('[data-operacion-comentario-form=\"1\"]');", javascript)
        self.assertIn("e.preventDefault();", javascript)
        self.assertIn("submitCommentForm(commentForm);", javascript)

    def test_javascript_serializa_antes_de_deshabilitar_el_formulario(self):
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")
        self.assertEqual(response.status_code, 200)
        create_start = javascript.index("function createOperacionInline(form)")
        post_start = javascript.index(
            "postForm(form.action || inlineCreateUrl",
            create_start,
        )
        create_block = javascript[create_start:post_start]

        self.assertLess(
            create_block.index("const formData = new FormData(form);"),
            create_block.index("setInlineFormPending(form, true);"),
        )

    def test_creacion_inline_no_depende_del_encabezado_ajax(self):
        match = resolve(self.inline_url)
        self.assertEqual(match.func.__module__, "operaciones.views")

        response = self.client.post(
            self.inline_url,
            {"titulo": "Operacion sin AJAX", "estado": Operacion.Estado.PENDIENTE},
        )

        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertTrue(Operacion.objects.filter(pk=data["id"]).exists())

    def test_url_inline_resuelve_a_la_vista_esperada(self):
        match = resolve(self.inline_url)

        self.assertEqual(self.inline_url, "/operaciones/nueva/inline/")
        self.assertEqual(match.func.__module__, "operaciones.views")
        self.assertEqual(match.view_name, "operaciones:crear_operacion_inline")
        self.assertEqual(match.url_name, "crear_operacion_inline")
        self.assertEqual(match.namespace, "operaciones")

        form_match = resolve(self.inline_form_url)
        self.assertEqual(self.inline_form_url, "/operaciones/nueva/inline/formulario/")
        self.assertEqual(form_match.func.__module__, "operaciones.views")
        self.assertEqual(form_match.view_name, "operaciones:formulario_operacion_inline")

    def test_creacion_inline_requiere_post(self):
        response = self.client.get(self.inline_url)

        self.assertEqual(response.status_code, 405)

    def test_creacion_inline_sin_csrf_es_rechazada(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)

        response = client.post(
            self.inline_url,
            {"titulo": "Operacion sin CSRF", "estado": Operacion.Estado.PENDIENTE},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 403)
        self.assertFalse(Operacion.objects.exists())


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
                "asignados_present": "1",
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

    def test_conserva_asignados_si_el_campo_no_se_envia(self):
        self.operacion.asignados.add(self.assigned_user)

        response = self.client.post(
            self.edit_url,
            {
                "titulo": "Operacion sin asignados en POST",
                "prioridad": Operacion.Prioridad.MEDIA,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.operacion.refresh_from_db()
        self.assertEqual(list(self.operacion.asignados.all()), [self.assigned_user])

    def test_vacia_asignados_si_el_campo_se_envia_vacio_intencionalmente(self):
        self.operacion.asignados.add(self.assigned_user)

        response = self.client.post(
            self.edit_url,
            {
                "titulo": "Operacion sin asignados",
                "prioridad": Operacion.Prioridad.MEDIA,
                "asignados_present": "1",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.operacion.refresh_from_db()
        self.assertEqual(list(self.operacion.asignados.all()), [])

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

    def test_edicion_rapida_no_depende_de_ajax_y_metodo_permitido(self):
        response = self.client.get(self.edit_url)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])

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

    def test_agregar_comentario_ajax_valida_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.login(username="comments_owner", password="pass")

        response_sin_csrf = client.post(
            self.url,
            {"comentario": "Comentario sin CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest"
        )
        self.assertEqual(response_sin_csrf.status_code, 403)
        self.assertFalse(OperacionComentario.objects.filter(comentario="Comentario sin CSRF").exists())

        request = HttpRequest()
        csrftoken = get_token(request)
        client.cookies.load({"csrftoken": csrftoken})

        response_con_csrf = client.post(
            self.url,
            {"comentario": "Comentario con CSRF", "layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_X_CSRFTOKEN=csrftoken
        )
        self.assertEqual(response_con_csrf.status_code, 200)
        data = response_con_csrf.json()
        self.assertTrue(data["success"])
        self.assertTrue(OperacionComentario.objects.filter(comentario="Comentario con CSRF").exists())

    def test_comentario_requiere_post(self):
        response = self.client.get(self.url, HTTP_X_REQUESTED_WITH="XMLHttpRequest")

        self.assertEqual(response.status_code, 405)

    def test_template_y_javascript_mantienen_contrato_ajax_para_formulario_dinamico(self):
        template = (
            Path(__file__).resolve().parent
            / "templates"
            / "operaciones"
            / "_comentarios_section.html"
        ).read_text(encoding="utf-8")
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")

        self.assertIn('method="post"', template)
        self.assertIn('data-operacion-comentario-form="1"', template)
        self.assertIn("{% csrf_token %}", template)
        self.assertIn("const formData = new FormData(commentForm);", javascript)
        self.assertIn("const csrfToken = window.getCSRFToken?.(commentForm);", javascript)
        self.assertIn("'X-Requested-With': 'XMLHttpRequest'", javascript)
        self.assertIn("'X-CSRFToken': csrfToken", javascript)
        self.assertIn("document.addEventListener('submit', (e) => {", javascript)
        self.assertIn("submitCommentForm(commentForm);", javascript)


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


class OperacionesProgressiveLoadingTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.admin = User.objects.create_user(
            username="admin-phase7d",
            password="pass",
            is_superuser=True,
            is_staff=True,
        )
        self.ejecutivo = User.objects.create_user(
            username="ejecutivo-phase7d",
            password="pass",
            first_name="Ejecutivo",
        )
        self.client.force_login(self.admin)

    def _bulk(self, cantidad, estado=Operacion.Estado.PENDIENTE):
        base = timezone.now() + timedelta(minutes=1)
        Operacion.objects.bulk_create(
            [
                Operacion(
                    titulo=f"Fase 7D {estado} {index:03d}",
                    estado=estado,
                    creado_por=self.admin,
                    fecha_creacion=base + timedelta(seconds=index),
                )
                for index in range(cantidad)
            ]
        )

    @staticmethod
    def _columna(response, estado):
        return next(
            columna
            for columna in response.context["columnas"]
            if columna["estado"] == estado
        )

    def _endpoint(self, estado, loaded_ids=(), **params):
        params.setdefault("offset", len(loaded_ids))
        params.setdefault(
            "loaded", ",".join(str(value) for value in loaded_ids)
        )
        return self.client.get(
            reverse("operaciones:tarjetas_columna", args=[estado]),
            params,
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    @staticmethod
    def _ids(html):
        return [
            int(value)
            for value in re.findall(
                r'data-panel-operacion-id="(\d+)"', html
            )
        ]

    def test_get_inicial_limita_cinco_y_mantiene_nueve_totales_reales(self):
        self._bulk(21)
        before = Operacion.objects.count()
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        columna = self._columna(response, Operacion.Estado.PENDIENTE)
        html = response.content.decode()

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["columnas"]), 9)
        self.assertEqual(columna["count"], 21)
        self.assertEqual(columna["loaded"], 5)
        self.assertEqual(len(columna["items"]), 5)
        self.assertTrue(columna["has_more"])
        self.assertEqual(
            html.count('data-panel-operacion-card="1"'), 5
        )
        self.assertEqual(html.count('data-operaciones-column="1"'), 9)
        self.assertIn('data-total="21"', html)
        self.assertIn("Cargar más (16)", html)
        self.assertNotIn('data-operacion-inline-form="1"', html)
        self.assertNotIn('data-operacion-quick-edit-form="1"', html)
        self.assertEqual(Operacion.objects.count(), before)

    def test_limites_y_nueve_columnas_independientes_e_historicos(self):
        estado = Operacion.Estado.PENDIENTE
        for total, visible, has_more in (
            (0, 0, False),
            (1, 1, False),
            (5, 5, False),
            (6, 5, True),
            (10, 5, True),
            (11, 5, True),
            (20, 5, True),
            (21, 5, True),
        ):
            Operacion.objects.all().delete()
            self._bulk(total)
            columna = self._columna(
                self.client.get(reverse("operaciones:panel_operaciones")),
                estado,
            )
            self.assertEqual(columna["count"], total)
            self.assertEqual(columna["loaded"], visible)
            self.assertEqual(columna["has_more"], has_more)

        Operacion.objects.all().delete()
        for value in Operacion.Estado.values:
            self._bulk(6, value)
        Operacion.objects.create(
            titulo="Estado historico invisible",
            estado="ESTADO_HISTORICO",
            creado_por=self.admin,
        )
        response = self.client.get(reverse("operaciones:panel_operaciones"))
        self.assertEqual(
            [column["loaded"] for column in response.context["columnas"]],
            [5] * 9,
        )
        self.assertNotContains(response, "Estado historico invisible")

    def test_endpoint_cargas_consecutivas_orden_desempate_y_parcial_real(self):
        estado = Operacion.Estado.SEGUROS
        self._bulk(21, estado)
        panel = self.client.get(reverse("operaciones:panel_operaciones"))
        first_ids = [
            operacion.pk for operacion in self._columna(panel, estado)["items"]
        ]
        second = self._endpoint(estado, first_ids)
        second_data = second.json()
        second_ids = self._ids(second_data["html"])
        third = self._endpoint(estado, first_ids + second_ids)
        third_data = third.json()
        third_ids = self._ids(third_data["html"])
        expected = list(
            Operacion.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)
        )

        self.assertEqual(second.status_code, 200)
        self.assertEqual(second_data["loaded"], 10)
        self.assertTrue(second_data["has_more"])
        self.assertEqual(second_data["next_offset"], 15)
        self.assertEqual(third_data["loaded"], 6)
        self.assertFalse(third_data["has_more"])
        self.assertEqual(first_ids + second_ids + third_ids, expected)
        self.assertNotIn("<html", second_data["html"].lower())
        for marker in (
            'data-operacion-state-select="1"',
            'data-panel-operacion-modal-open="1"',
            'data-operacion-quick-edit-open="1"',
            'data-operacion-card-tags="1"',
            'data-operacion-card-comments-count="1"',
            'data-operacion-card-files-count="1"',
            'data-operacion-card-links-count="1"',
        ):
            self.assertIn(marker, second_data["html"])

    def test_endpoint_reconcilia_eliminacion_movimiento_creacion_y_filtro(self):
        estado = Operacion.Estado.EN_ADUANA
        self._bulk(16, estado)
        ordered = list(
            Operacion.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
        )
        for operacion in ordered[:12]:
            operacion.asignados.add(self.ejecutivo)
        first_ids = [operacion.pk for operacion in ordered[:5]]
        deleted_id, moved_id = first_ids[-2:]
        Operacion.objects.filter(pk=deleted_id).delete()
        Operacion.objects.filter(pk=moved_id).update(
            estado=Operacion.Estado.PRUEBA_VALOR
        )
        created = Operacion.objects.create(
            titulo="Creada entre lotes",
            estado=estado,
            creado_por=self.admin,
        )
        created.asignados.add(self.ejecutivo)
        stale_assignment_id = first_ids[-3]
        Operacion.objects.get(pk=stale_assignment_id).asignados.remove(
            self.ejecutivo
        )
        loaded_ids = [created.pk] + first_ids
        response = self._endpoint(
            estado,
            loaded_ids,
            usuario=str(self.ejecutivo.pk),
        )
        data = response.json()
        returned = self._ids(data["html"])

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            data["stale_ids"],
            [stale_assignment_id, deleted_id, moved_id],
        )
        self.assertNotIn(created.pk, returned)
        self.assertTrue(set(first_ids).isdisjoint(returned))
        self.assertEqual(data["total"], 10)

    def test_endpoint_valida_parametros_metodos_y_permisos_reales(self):
        estado = Operacion.Estado.PENDIENTE
        url = reverse("operaciones:tarjetas_columna", args=[estado])
        for params in (
            {"offset": "-1"},
            {"offset": "texto"},
            {"offset": "1", "loaded": "abc"},
            {"offset": "2", "loaded": "1,1"},
            {"offset": "0", "usuario": "invalido"},
            {"offset": "0", "usuario": "999999"},
            {"offset": "0", "usuario": ["1", "2"]},
        ):
            self.assertEqual(self.client.get(url, params).status_code, 400)
        invalid_state = reverse(
            "operaciones:tarjetas_columna",
            args=["ESTADO_INEXISTENTE"],
        )
        self.assertEqual(
            self.client.get(
                invalid_state, {"offset": "0", "loaded": ""}
            ).status_code,
            404,
        )
        self.assertEqual(self.client.post(url).status_code, 405)
        self.assertEqual(self.client.put(url).status_code, 405)
        self.assertEqual(self.client.delete(url).status_code, 405)

        self.client.force_login(self.ejecutivo)
        self.assertEqual(self._endpoint(estado).status_code, 200)
        self.assertEqual(
            self.client.get(reverse("operaciones:panel_operaciones")).status_code,
            200,
        )
        self.client.logout()
        anonymous = self.client.get(url, {"offset": "0", "loaded": ""})
        self.assertEqual(anonymous.status_code, 302)
        self.assertIn("/login/", anonymous.url)

    def test_get_y_endpoint_consultas_constantes_y_solo_lectura(self):
        panel_url = reverse("operaciones:panel_operaciones")
        endpoint_url = reverse(
            "operaciones:tarjetas_columna",
            args=[Operacion.Estado.PENDIENTE],
        )
        self._bulk(1)
        with CaptureQueriesContext(connection) as panel_small:
            self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_small:
            self.client.get(endpoint_url, {"offset": "0", "loaded": ""})
        self._bulk(100)
        before = Operacion.objects.count()
        with CaptureQueriesContext(connection) as panel_large:
            self.client.get(panel_url)
        with CaptureQueriesContext(connection) as endpoint_large:
            self.client.get(endpoint_url, {"offset": "0", "loaded": ""})

        self.assertEqual(len(panel_small), len(panel_large))
        self.assertEqual(len(endpoint_small), len(endpoint_large))
        self.assertEqual(Operacion.objects.count(), before)
        writes = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE)\b", re.I)
        self.assertFalse(
            any(
                writes.match(query["sql"])
                for query in list(panel_large) + list(endpoint_large)
            )
        )

    def test_segundo_lote_conserva_relaciones_y_acciones(self):
        estado = Operacion.Estado.EXPEDIENTE_CG
        self._bulk(6, estado)
        oldest = (
            Operacion.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .last()
        )
        tag = OperacionEtiqueta.objects.create(
            nombre="Urgente 7D", color="#FF0000"
        )
        option = OperacionOpcion.objects.create(nombre="Revisar 7D")
        oldest.etiquetas.add(tag)
        oldest.opciones.add(option)
        first_ids = list(
            Operacion.objects.filter(estado=estado)
            .order_by("-fecha_creacion", "-id")
            .values_list("pk", flat=True)[:5]
        )
        response = self._endpoint(estado, first_ids)
        html = response.json()["html"]

        self.assertIn("Urgente 7D", html)
        self.assertIn('data-operacion-state-select="1"', html)
        self.assertIn('data-operacion-quick-edit-open="1"', html)
        self.assertIn('data-panel-operacion-modal-open="1"', html)
        detail = self.client.get(
            reverse("operaciones:detalle_operacion_modal", args=[oldest.pk])
        )
        self.assertContains(detail, "Revisar 7D")

    def test_javascript_concurrencia_reconciliacion_y_delegacion(self):
        javascript = PANEL_JS_PATH.read_text(encoding="utf-8")
        self.assertIn("const columnLoadRequests = new Map()", javascript)
        self.assertIn("if (existing) return existing.promise", javascript)
        self.assertIn("entry.controller.abort()", javascript)
        self.assertIn("requestVersion !== boardVersion", javascript)
        self.assertIn("Tarjeta duplicada o incompatible.", javascript)
        self.assertIn("staleIds.forEach", javascript)
        self.assertIn("data-operacion-load-more", javascript)
        self.assertIn("No se pudieron cargar las tarjetas.", javascript)
        self.assertIn("invalidateColumnLoads();", javascript)
        self.assertIn("root.dataset.panelJsInitialized = '1'", javascript)
        self.assertEqual(javascript.count("Sortable.create("), 2)
        self.assertEqual(
            javascript.count("root.addEventListener('click'"), 1
        )
        self.assertEqual(
            javascript.count("root.addEventListener('change'"), 1
        )
