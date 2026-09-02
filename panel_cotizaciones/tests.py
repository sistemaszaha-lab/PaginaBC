import re
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.middleware.csrf import get_token
from django.http import HttpRequest
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente

from .forms import PanelCotizacionCreateForm
from .models import (
    PanelCotizacion,
    PanelCotizacionArchivo,
    PanelCotizacionColumna,
    PanelCotizacionComentario,
    PanelCotizacionElementoAccion,
    PanelCotizacionEnlace,
    PanelCotizacionEtiqueta,
)

User = get_user_model()
PANEL_JS_PATH = (
    Path(__file__).resolve().parent
    / "static"
    / "panel_cotizaciones"
    / "js"
    / "panel.js"
)


class PanelCotizacionClienteNormalizacionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_user", password="panel123", first_name="Panel"
        )

    def test_creacion_normaliza_cliente(self):
        cliente = Cliente.objects.create(nombre=" empresa vargas ")
        form = PanelCotizacionCreateForm(
            data={
                "titulo": "Tablero",
                "descripcion": "Descripcion",
                "cliente": cliente.pk,
                "prioridad": "MEDIA",
                "fecha_vencimiento": date(2026, 2, 1).isoformat(),
                "asignados": [],
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

        panel = form.save(commit=False)
        panel.creado_por = self.user
        panel.estado = PanelCotizacion.Estado.REQUERIMIENTO
        panel.save()

        self.assertEqual(panel.cliente, "EMPRESA VARGAS")

    def test_edicion_normaliza_cliente_y_conserva_caracteres(self):
        panel = PanelCotizacion.objects.create(
            titulo="Tablero",
            descripcion="Descripcion",
            cliente="",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        panel.cliente = " mexico  & cia. - log / sur "
        panel.save()
        panel.refresh_from_db()

        self.assertEqual(panel.cliente, "MEXICO & CIA. - LOG / SUR")


class PanelCotizacionAccessAndRenderingTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="panel_admin", password="panel123", email="admin@example.com"
        )
        self.ejecutivo = User.objects.create_user(
            username="panel_exec", password="panel123", first_name="Ejecutivo"
        )
        self.panel = PanelCotizacion.objects.create(
            titulo="Carga inicial",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.admin,
        )

    def test_panel_carga_para_admin_y_ejecutivo(self):
        client = Client()
        client.force_login(self.admin)
        admin_response = client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(admin_response.status_code, 200)
        self.assertContains(admin_response, "Panel de Cotizaciones")

        client = Client()
        client.force_login(self.ejecutivo)
        exec_response = client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(exec_response.status_code, 200)
        self.assertContains(exec_response, "Carga inicial")

    def test_panel_requiere_autenticacion(self):
        response = self.client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(response.status_code, 302)

    def test_panel_no_renderiza_cliente_ni_descripcion_en_tarjetas(self):
        client = Client()
        client.force_login(self.ejecutivo)
        response = client.get(reverse("panel_cotizaciones:panel_cotizaciones"))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "panel-cotizacion-card__client")
        self.assertNotContains(response, "panel-cotizacion-card__description")

    def test_detalle_drawer_renderiza(self):
        client = Client()
        client.force_login(self.ejecutivo)
        response = client.get(
            reverse("panel_cotizaciones:detalle_modal", args=[self.panel.pk]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Carga inicial")
        self.assertContains(response, "CLIENTE UNO")
        self.assertContains(response, "Descripcion")
        self.assertContains(response, "zaha-detail-modal__header")
        self.assertContains(response, "zaha-detail-modal__body")
        self.assertContains(response, "zaha-detail-modal__footer")


class PanelCotizacionFiltroTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_filter", password="panel123", first_name="Panel"
        )
        self.asignado = User.objects.create_user(
            username="panel_asignado", password="panel123", first_name="Asignado"
        )
        self.otro_asignado = User.objects.create_user(
            username="panel_otro_asignado", password="panel123", first_name="Otro"
        )
        self.client = Client()
        self.client.force_login(self.user)

        self.panel = PanelCotizacion.objects.create(
            titulo="Cotizacion Visible",
            descripcion="Descripcion",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.panel.asignados.add(self.asignado)
        self.panel_2 = PanelCotizacion.objects.create(
            titulo="Cotizacion Dos",
            descripcion="Descripcion",
            cliente="CLIENTE DOS",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.panel_2.asignados.add(self.otro_asignado)
        self.panel_3 = PanelCotizacion.objects.create(
            titulo="Sin Asignado",
            descripcion="Descripcion",
            cliente="CLIENTE TRES",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )

    def test_panel_filtra_por_usuario(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": str(self.asignado.id)},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertNotContains(response, "Cotizacion Dos")
        self.assertNotContains(response, "Sin Asignado")

    def test_panel_filtra_por_multiples_usuarios(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": [str(self.asignado.id), str(self.otro_asignado.id)]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertContains(response, "Cotizacion Dos")
        self.assertNotContains(response, "Sin Asignado")

    def test_panel_ignora_valores_vacios_en_filtro(self):
        response = self.client.get(
            reverse("panel_cotizaciones:panel_cotizaciones"),
            {"usuario": ["", str(self.asignado.id)]},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Cotizacion Visible")
        self.assertNotContains(response, "Cotizacion Dos")


@override_settings(PERFORMANCE_DEBUG=False)
class PanelCotizacionCopiarPegarTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(
            username="panel_copy_admin",
            password="panel123",
            email="panel-copy@example.com",
        )
        self.ejecutivo = User.objects.create_user(
            username="panel_copy_exec",
            password="panel123",
            first_name="Ejecutivo",
        )
        self.inactivo = User.objects.create_user(
            username="panel_copy_blocked",
            password="panel123",
            is_active=False,
        )
        self.cliente = Cliente.objects.create(nombre=" Cliente copiado ")
        self.etiqueta_a = PanelCotizacionEtiqueta.objects.create(
            nombre="Alta prioridad copy",
            color="#AA0000",
        )
        self.etiqueta_b = PanelCotizacionEtiqueta.objects.create(
            nombre="Seguimiento copy",
            color="#00AA00",
        )
        self.columna_origen = PanelCotizacionColumna.objects.get(
            codigo=PanelCotizacion.Estado.REQUERIMIENTO
        )
        self.columna_destino = PanelCotizacionColumna.objects.get(
            codigo=PanelCotizacion.Estado.EN_PROGRESO
        )
        self.columna_tercera = PanelCotizacionColumna.objects.get(
            codigo=PanelCotizacion.Estado.ENVIADA
        )
        self.panel = PanelCotizacion.objects.create(
            titulo="Cotizacion original",
            descripcion="Descripcion de prueba",
            cliente=self.cliente.nombre,
            prioridad=PanelCotizacion.Prioridad.ALTA,
            estado=self.columna_origen.codigo,
            columna=self.columna_origen,
            fecha_vencimiento=date(2026, 8, 20),
            creado_por=self.admin,
        )
        self.panel.asignados.set([self.admin, self.ejecutivo])
        self.panel.etiquetas.set([self.etiqueta_a, self.etiqueta_b])
        self.comentario = PanelCotizacionComentario.objects.create(
            cotizacion=self.panel,
            texto="No copiar comentario",
            creado_por=self.admin,
        )
        self.archivo = PanelCotizacionArchivo.objects.create(
            cotizacion=self.panel,
            archivo=SimpleUploadedFile(
                "copy-source.txt",
                b"contenido",
                content_type="text/plain",
            ),
            subido_por=self.admin,
        )
        self.enlace = PanelCotizacionEnlace.objects.create(
            cotizacion=self.panel,
            titulo="No copiar enlace",
            url="https://example.com/original",
            creado_por=self.admin,
        )
        self.client = Client()

    def _paste(self, user, *, columna_id=None, tarjeta_id=None):
        self.client.force_login(user)
        return self.client.post(
            reverse(
                "panel_cotizaciones:columna_pegar",
                args=[columna_id or self.columna_destino.pk],
            ),
            {"tarjeta_id": tarjeta_id or self.panel.pk},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

    def test_admin_puede_copiar_y_pegar(self):
        response = self._paste(self.admin)
        self.assertEqual(response.status_code, 201)
        data = response.json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["columna_id"], self.columna_destino.pk)
        self.assertIn('data-panel-cotizacion-card="1"', data["html"])
        self.assertIn("panel-cotizacion-card__copy-btn", data["html"])
        self.assertNotIn("Acciones", data["html"])

    def test_ejecutivo_puede_copiar_y_pegar(self):
        response = self._paste(self.ejecutivo)
        self.assertEqual(response.status_code, 201)
        self.assertTrue(response.json()["ok"])

    def test_copia_no_modifica_original_y_genera_nuevo_id(self):
        original_snapshot = {
            "titulo": self.panel.titulo,
            "descripcion": self.panel.descripcion,
            "cliente": self.panel.cliente,
            "prioridad": self.panel.prioridad,
            "estado": self.panel.estado,
            "columna_id": self.panel.columna_id,
        }
        response = self._paste(self.admin)
        nueva = PanelCotizacion.objects.get(pk=response.json()["tarjeta_id"])
        self.panel.refresh_from_db()
        self.assertNotEqual(nueva.pk, self.panel.pk)
        self.assertEqual(
            {
                "titulo": self.panel.titulo,
                "descripcion": self.panel.descripcion,
                "cliente": self.panel.cliente,
                "prioridad": self.panel.prioridad,
                "estado": self.panel.estado,
                "columna_id": self.panel.columna_id,
            },
            original_snapshot,
        )

    def test_copia_sincroniza_columna_estado_y_campos_editables(self):
        response = self._paste(self.admin)
        nueva = PanelCotizacion.objects.get(pk=response.json()["tarjeta_id"])
        self.assertEqual(nueva.columna_id, self.columna_destino.pk)
        self.assertEqual(nueva.estado, self.columna_destino.codigo)
        self.assertEqual(nueva.titulo, self.panel.titulo)
        self.assertEqual(nueva.descripcion, self.panel.descripcion)
        self.assertEqual(nueva.cliente, self.panel.cliente)
        self.assertEqual(nueva.prioridad, self.panel.prioridad)
        self.assertEqual(nueva.fecha_vencimiento, self.panel.fecha_vencimiento)
        self.assertEqual(nueva.creado_por, self.admin)

    def test_copia_relaciones_validas_y_excluye_historial_adjuntos_enlaces(self):
        response = self._paste(self.admin)
        nueva = PanelCotizacion.objects.get(pk=response.json()["tarjeta_id"])
        self.assertEqual(
            list(nueva.asignados.order_by("pk").values_list("pk", flat=True)),
            list(self.panel.asignados.order_by("pk").values_list("pk", flat=True)),
        )
        self.assertEqual(
            list(nueva.etiquetas.order_by("pk").values_list("pk", flat=True)),
            list(self.panel.etiquetas.order_by("pk").values_list("pk", flat=True)),
        )
        self.assertFalse(nueva.comentarios.exists())
        self.assertFalse(nueva.archivos.exists())
        self.assertFalse(nueva.enlaces.exists())

    def test_modelo_no_tiene_one_to_one_ni_identificadores_unicos_copiables(self):
        one_to_one_fields = [
            field.name for field in PanelCotizacion._meta.get_fields()
            if getattr(field, "one_to_one", False) and not getattr(field, "auto_created", False)
        ]
        unique_fields = [
            field.name for field in PanelCotizacion._meta.fields
            if getattr(field, "unique", False) and not field.primary_key
        ]
        self.assertEqual(one_to_one_fields, [])
        self.assertEqual(unique_fields, [])
        response = self._paste(self.admin)
        self.assertEqual(response.status_code, 201)

    def test_no_puede_pegar_en_columna_inexistente_o_inactiva(self):
        inexistente = self._paste(self.admin, columna_id=999999)
        self.assertEqual(inexistente.status_code, 404)

        self.columna_destino.activa = False
        self.columna_destino.save(update_fields=["activa"])
        inactiva = self._paste(self.admin)
        self.assertEqual(inactiva.status_code, 404)

    def test_no_puede_copiar_tarjeta_inexistente_y_peticion_invalida_no_crea(self):
        total_antes = PanelCotizacion.objects.count()
        inexistente = self._paste(self.admin, tarjeta_id=999999)
        self.assertEqual(inexistente.status_code, 404)

        invalida = self.client.post(
            reverse("panel_cotizaciones:columna_pegar", args=[self.columna_destino.pk]),
            {"tarjeta_id": "abc"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalida.status_code, 400)

        self.client.force_login(self.admin)
        invalida_ajax = self.client.post(
            reverse("panel_cotizaciones:columna_pegar", args=[self.columna_destino.pk]),
            {"tarjeta_id": "abc"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(invalida_ajax.status_code, 400)
        self.assertEqual(PanelCotizacion.objects.count(), total_antes)

    def test_usuario_sin_permiso_recibe_403(self):
        self.client.force_login(self.admin)
        with patch("panel_cotizaciones.views._puede_operar_panel", return_value=False):
            response = self.client.post(
                reverse("panel_cotizaciones:columna_pegar", args=[self.columna_destino.pk]),
                {"tarjeta_id": self.panel.pk},
                HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            )
        self.assertEqual(response.status_code, 403)
        self.assertFalse(
            PanelCotizacion.objects.filter(
                titulo=self.panel.titulo,
                columna=self.columna_destino,
            ).exists()
        )

    def test_respuesta_exitosa_incluye_html_y_tarjeta_resultante_se_puede_mover(self):
        response = self._paste(self.admin)
        data = response.json()
        self.assertIn("<article", data["html"])
        nueva = PanelCotizacion.objects.get(pk=data["tarjeta_id"])

        self.client.force_login(self.admin)
        move_response = self.client.post(
            reverse("panel_cotizaciones:estado_update"),
            {
                "cotizacion_id": nueva.pk,
                "nuevo_estado": self.columna_tercera.codigo,
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(move_response.status_code, 200)
        nueva.refresh_from_db()
        self.assertEqual(nueva.columna_id, self.columna_tercera.pk)
        self.assertEqual(nueva.estado, self.columna_tercera.codigo)


class PanelCotizacionChecklistTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="panel_checklist_user",
            password="panel123",
            first_name="Checklist",
        )
        self.client = Client()
        self.client.force_login(self.user)
        self.panel = PanelCotizacion.objects.create(
            titulo="Proyecto checklist",
            descripcion="Descripcion inicial",
            cliente="CLIENTE UNO",
            prioridad=PanelCotizacion.Prioridad.MEDIA,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            creado_por=self.user,
        )
        self.otro_panel = PanelCotizacion.objects.create(
            titulo="Proyecto ajeno",
            descripcion="Otra descripcion",
            cliente="CLIENTE DOS",
            prioridad=PanelCotizacion.Prioridad.BAJA,
            estado=PanelCotizacion.Estado.EN_PROGRESO,
            creado_por=self.user,
        )

    def test_guardar_descripcion_desde_detalle(self):
        response = self.client.post(
            reverse("panel_cotizaciones:detalle_modal_update", args=[self.panel.pk]),
            {
                "layout": "drawer",
                "descripcion": "Descripcion general actualizada",
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["status"], "ok")
        self.panel.refresh_from_db()
        self.assertEqual(self.panel.descripcion, "Descripcion general actualizada")

    def test_agregar_elemento_persiste_y_reaparece_al_recargar(self):
        response = self.client.post(
            reverse("panel_cotizaciones:checklist_item_create", args=[self.panel.pk]),
            {"texto": "Llamar al cliente"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        item = PanelCotizacionElementoAccion.objects.get(cotizacion=self.panel)
        self.assertEqual(item.texto, "Llamar al cliente")

        detail_response = self.client.get(
            reverse("panel_cotizaciones:detalle_modal", args=[self.panel.pk]),
            {"layout": "drawer"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertContains(detail_response, "Llamar al cliente")

    def test_marcar_y_desmarcar_elemento(self):
        item = PanelCotizacionElementoAccion.objects.create(
            cotizacion=self.panel,
            texto="Preparar propuesta",
            orden=1,
        )

        marcar = self.client.post(
            reverse("panel_cotizaciones:checklist_item_toggle", args=[self.panel.pk, item.pk]),
            {"completado": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(marcar.status_code, 200)
        item.refresh_from_db()
        self.assertTrue(item.completado)

        desmarcar = self.client.post(
            reverse("panel_cotizaciones:checklist_item_toggle", args=[self.panel.pk, item.pk]),
            {"completado": "0"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(desmarcar.status_code, 200)
        item.refresh_from_db()
        self.assertFalse(item.completado)

    def test_eliminar_elemento(self):
        item = PanelCotizacionElementoAccion.objects.create(
            cotizacion=self.panel,
            texto="Eliminar luego",
            orden=1,
        )

        response = self.client.post(
            reverse("panel_cotizaciones:checklist_item_delete", args=[self.panel.pk, item.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["ok"])
        self.assertFalse(
            PanelCotizacionElementoAccion.objects.filter(pk=item.pk).exists()
        )

    def test_proyecto_a_no_modifica_checklist_de_proyecto_b(self):
        item_otro = PanelCotizacionElementoAccion.objects.create(
            cotizacion=self.otro_panel,
            texto="Privado",
            orden=1,
        )

        response = self.client.post(
            reverse("panel_cotizaciones:checklist_item_toggle", args=[self.panel.pk, item_otro.pk]),
            {"completado": "1"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 404)
        item_otro.refresh_from_db()
        self.assertFalse(item_otro.completado)

    def test_checklist_requiere_login(self):
        self.client.logout()
        response = self.client.post(
            reverse("panel_cotizaciones:checklist_item_create", args=[self.panel.pk]),
            {"texto": "No autorizado"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 302)
        self.assertFalse(
            PanelCotizacionElementoAccion.objects.filter(
                cotizacion=self.panel,
                texto="No autorizado",
            ).exists()
        )

    def test_peticion_invalida_devuelve_error_controlado(self):
        response = self.client.post(
            reverse("panel_cotizaciones:checklist_item_create", args=[self.panel.pk]),
            {"texto": "   "},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertIn("Escribe un elemento de accion.", data["html"])


class PanelCotizacionEtiquetasAjaxTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='testpassword', is_superuser=True)
        self.client.login(username='testuser', password='testpassword')
        self.cotizacion_a = PanelCotizacion.objects.create(
            titulo='Cotizacion A',
            creado_por=self.user,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            prioridad=PanelCotizacion.Prioridad.MEDIA,
        )
        self.cotizacion_b = PanelCotizacion.objects.create(
            titulo='Cotizacion B',
            creado_por=self.user,
            estado=PanelCotizacion.Estado.REQUERIMIENTO,
            prioridad=PanelCotizacion.Prioridad.MEDIA,
        )
        self.cotizacion_a.asignados.add(self.user)
        self.cotizacion_b.asignados.add(self.user)
        self.etiqueta1 = PanelCotizacionEtiqueta.objects.create(nombre='Etiqueta 1', color='#ff0000')
        self.etiqueta2 = PanelCotizacionEtiqueta.objects.create(nombre='Etiqueta 2', color='#00ff00')

    def test_asignar_etiqueta_existente(self):
        url = reverse('panel_cotizaciones:agregar_etiqueta_cotizacion', args=[self.cotizacion_a.id])
        response = self.client.post(url, {'etiquetas': [self.etiqueta1.id]}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(self.cotizacion_a.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_crear_y_asignar(self):
        url = reverse('panel_cotizaciones:crear_etiqueta_cotizacion', args=[self.cotizacion_a.id])
        response = self.client.post(url, {'nombre': 'Nueva Etiqueta', 'color': '#0000ff'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(PanelCotizacionEtiqueta.objects.filter(nombre='Nueva Etiqueta').exists())
        self.assertTrue(self.cotizacion_a.etiquetas.filter(nombre='Nueva Etiqueta').exists())

    def test_desasignar_una(self):
        self.cotizacion_a.etiquetas.add(self.etiqueta1)
        url = reverse('panel_cotizaciones:quitar_etiqueta_cotizacion', args=[self.cotizacion_a.id, self.etiqueta1.id])
        response = self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(response.status_code, 200)
        self.assertFalse(self.cotizacion_a.etiquetas.filter(id=self.etiqueta1.id).exists())
        
        # Test que NO se elimina de la BD global
        self.assertTrue(PanelCotizacionEtiqueta.objects.filter(id=self.etiqueta1.id).exists())

    def test_desasignar_de_tarjeta_a_no_afecta_tarjeta_b(self):
        self.cotizacion_a.etiquetas.add(self.etiqueta1)
        self.cotizacion_b.etiquetas.add(self.etiqueta1)
        url = reverse('panel_cotizaciones:quitar_etiqueta_cotizacion', args=[self.cotizacion_a.id, self.etiqueta1.id])
        self.client.post(url, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        
        self.assertFalse(self.cotizacion_a.etiquetas.filter(id=self.etiqueta1.id).exists())
        self.assertTrue(self.cotizacion_b.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_guardar_formulario_general_conserva_etiquetas(self):
        self.cotizacion_a.etiquetas.add(self.etiqueta1)
        url = reverse('panel_cotizaciones:detalle_modal_update', args=[self.cotizacion_a.id])
        # Actualizamos titulo
        response = self.client.post(url, {
            'titulo': 'Nuevo Titulo',
            'prioridad': PanelCotizacion.Prioridad.ALTA,
            'cliente': '',
            'layout': 'modal',
        })
        if response.status_code != 200 and response.status_code != 302:
            print(response.content.decode('utf-8'))
        self.cotizacion_a.refresh_from_db()
        self.assertTrue(self.cotizacion_a.etiquetas.filter(id=self.etiqueta1.id).exists())

    def test_rechazo_sin_ajax(self):
        url = reverse('panel_cotizaciones:agregar_etiqueta_cotizacion', args=[self.cotizacion_a.id])
        response = self.client.post(url, {'etiquetas': [self.etiqueta1.id]})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['error'], 'Solicitud AJAX requerida.')

