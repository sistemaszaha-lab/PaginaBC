"""Contrato del listado paginado, compatible con SQLite y PostgreSQL."""

import json
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from cuenta_gastos.models import CuentaGastos, DocumentoRepositorio
from garantias.models import Garantia
from operaciones.models import Operacion, OperacionEtiqueta
from panel_cotizaciones.models import PanelCotizacion
from solicitudes.models import Cotizacion, Referencia, Solicitud


class PapeleraRendimientoTests(TestCase):
    def setUp(self):
        users = get_user_model()
        self.admin = users.objects.create_user("admin_rendimiento", is_superuser=True)
        self.user = users.objects.create_user("usuario_rendimiento")
        self.other = users.objects.create_user("otro_rendimiento")
        self.url = reverse("papelera")
        self.client.force_login(self.admin)

    def _make_nine(self, moment):
        today = timezone.localdate()
        objects = [
            OperacionEtiqueta.objects.create(nombre="Etiqueta R"),
            Operacion.objects.create(titulo="Operación R", creado_por=self.user),
            Garantia.objects.create(titulo="Garantía R", creado_por=self.user),
            PanelCotizacion.objects.create(titulo="Panel R", creado_por=self.user),
            CuentaGastos.objects.create(titulo="Cuenta R", creado_por=self.user),
            Solicitud.objects.create(anio=2026, sg="SG26001R", cliente="Cliente R", fecha_recepcion=today, tipo="Servicio", ejecutivo=self.user),
            Cotizacion.objects.create(anio=2026, consecutivo="C26001R", cliente="Cliente R", fecha_solicitud=today, tipo="Servicio", ejecutivo=self.user),
            Referencia.objects.create(referencia="BC26001R", consecutivo=10001, cliente="Cliente R", ejecutivo=self.user),
            DocumentoRepositorio.objects.create(archivo="pruebas/documento.txt", nombre_original="Documento R", subido_por=self.user),
        ]
        for obj in objects:
            type(obj).objects.filter(pk=obj.pk).update(eliminado_en=moment, eliminado_por=self.admin)
        return objects

    def test_orden_global_y_empates_en_nueve_modelos_con_paginas_de_30(self):
        same_time = timezone.now() - timedelta(days=1)
        nine = self._make_nine(same_time)
        extra = [Operacion(titulo=f"Extra {n}", creado_por=self.user, eliminado_en=same_time - timedelta(minutes=n + 1)) for n in range(25)]
        Operacion.objects.bulk_create(extra)
        with CaptureQueriesContext(connection) as queries:
            response = self.client.get(self.url)
        self.assertTrue(any("UNION ALL" in query["sql"].upper() and "LIMIT 30" in query["sql"].upper() for query in queries))
        self.assertEqual(response.context["papelera_total"], 34)
        self.assertEqual(len(response.context["papelera_items"]), 30)
        self.assertEqual(
            [item["tipo"] for item in response.context["papelera_items"][:9]],
            ["operacion_etiqueta", "operacion", "garantia", "cotizacion", "cuenta_gastos", "solicitud", "cotizacion_ref", "referencia", "documento_repositorio"],
        )
        second = self.client.get(self.url, {"pagina": 2})
        self.assertEqual(len(second.context["papelera_items"]), 4)
        self.assertEqual(second.context["papelera_items"][-1]["titulo"], "Extra 24")
        self.assertEqual(
            len({(item["tipo"], item["id"]) for item in response.context["papelera_items"] + second.context["papelera_items"]}),
            34,
        )
        self.assertEqual(len(nine), 9)

    def test_empate_dentro_del_modelo_usa_id_descendente(self):
        moment = timezone.now()
        objects = [Operacion.objects.create(titulo=f"Igual {n}", creado_por=self.user, eliminado_en=moment) for n in range(3)]
        response = self.client.get(self.url, {"tipo": "operacion"})
        self.assertEqual([item["id"] for item in response.context["papelera_items"]], [obj.pk for obj in reversed(objects)])

    def test_permisos_filtros_y_busqueda_se_aplican_antes_de_paginar(self):
        now = timezone.now()
        own = Operacion.objects.create(titulo="Visible Alfa", creado_por=self.user, eliminado_en=now)
        assigned = Operacion.objects.create(titulo="Visible Beta", creado_por=self.other, eliminado_en=now)
        assigned.asignados.add(self.user)
        hidden = Operacion.objects.create(titulo="Oculto", creado_por=self.other, eliminado_en=now)
        CuentaGastos.objects.create(titulo="Visible Cuenta", creado_por=self.user, eliminado_en=now)
        self.client.force_login(self.user)
        result = self.client.get(self.url, {"tipo": "operacion", "q": "Visible"})
        self.assertEqual(result.context["papelera_total"], 2)
        self.assertEqual({item["id"] for item in result.context["papelera_items"]}, {own.pk, assigned.pk})
        self.assertNotContains(result, "Oculto")
        self.assertNotIn(hidden.pk, {item["id"] for item in result.context["papelera_items"]})
        all_items = self.client.get(self.url)
        self.assertEqual(all_items.context["papelera_total"], 3)
        self.assertFalse(all_items.context["papelera_can_delete"])

    def test_acciones_individuales_y_masivas_siguen_funcionando(self):
        now = timezone.now()
        restored = Operacion.objects.create(titulo="Restaurar", creado_por=self.user, eliminado_en=now)
        deleted = Operacion.objects.create(titulo="Eliminar", creado_por=self.user, eliminado_en=now)
        self.assertEqual(self.client.post(reverse("papelera_restaurar", args=["operacion", restored.pk])).status_code, 200)
        self.assertEqual(self.client.post(reverse("papelera_eliminar_definitivamente", args=["operacion", deleted.pk])).status_code, 200)
        restored.refresh_from_db()
        self.assertIsNone(restored.eliminado_en)
        self.assertFalse(Operacion.objects.filter(pk=deleted.pk).exists())

        bulk_a = Operacion.objects.create(titulo="Masiva A", creado_por=self.user, eliminado_en=now)
        bulk_b = Operacion.objects.create(titulo="Masiva B", creado_por=self.user, eliminado_en=now)
        payload = {"items": [{"tipo": "operacion", "id": bulk_a.pk}, {"tipo": "operacion", "id": bulk_b.pk}]}
        response = self.client.post(reverse("papelera_restaurar_seleccion"), data=json.dumps(payload), content_type="application/json")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["procesados"], 2)
        self.assertEqual(Operacion.objects.filter(pk__in=[bulk_a.pk, bulk_b.pk], eliminado_en__isnull=True).count(), 2)

        bulk_delete = Operacion.objects.create(titulo="Masiva Eliminar", creado_por=self.user, eliminado_en=now)
        response = self.client.post(
            reverse("papelera_eliminar_seleccion"),
            data=json.dumps({"items": [{"tipo": "operacion", "id": bulk_delete.pk}]}),
            content_type="application/json",
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Operacion.objects.filter(pk=bulk_delete.pk).exists())

    def test_numero_de_consultas_no_crece_con_registros_eliminados(self):
        self.client.force_login(self.user)
        now = timezone.now()
        Operacion.objects.bulk_create([Operacion(titulo=f"Primera {n}", creado_por=self.user, eliminado_en=now) for n in range(2)])
        with CaptureQueriesContext(connection) as few:
            first = self.client.get(self.url, {"tipo": "operacion"})
        Operacion.objects.bulk_create([Operacion(titulo=f"Luego {n}", creado_por=self.user, eliminado_en=now) for n in range(80)])
        with CaptureQueriesContext(connection) as many:
            second = self.client.get(self.url, {"tipo": "operacion"})
        self.assertEqual(len(first.context["papelera_items"]), 2)
        self.assertEqual(len(second.context["papelera_items"]), 30)
        self.assertEqual(second.context["papelera_total"], 82)
        self.assertLessEqual(len(many), len(few) + 1)
        self.assertLessEqual(len(many), 20)
