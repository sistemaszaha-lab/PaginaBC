from datetime import timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Incidencia


class PanelIncidenciasResumenTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester",
            password="secret123",
            first_name="Ada",
            last_name="Lovelace",
        )
        self.client.force_login(self.user)

    def _crear_incidencia(self, **overrides):
        base = {
            "codigo": f"INC-{Incidencia.objects.count() + 1:03d}",
            "titulo": "Incidencia de prueba",
            "descripcion": "",
            "responsable": self.user,
            "estado": Incidencia.Estado.ABIERTO,
            "prioridad": Incidencia.Prioridad.MEDIA,
            "fecha_limite": None,
        }
        base.update(overrides)
        return Incidencia.objects.create(**base)

    def test_panel_renderiza_resumen_con_metricas_reales(self):
        hoy = timezone.localdate()
        self._crear_incidencia(estado=Incidencia.Estado.ABIERTO)
        self._crear_incidencia(estado=Incidencia.Estado.ABIERTO, fecha_limite=hoy - timedelta(days=2))
        self._crear_incidencia(estado=Incidencia.Estado.PROCESO, fecha_limite=hoy + timedelta(days=2))
        self._crear_incidencia(estado=Incidencia.Estado.CERRADO, fecha_limite=hoy - timedelta(days=4))

        response = self.client.get(reverse("incidencias:panel_incidencias"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["resumen"]["pendientes"], 2)
        self.assertEqual(response.context["resumen"]["en_proceso"], 1)
        self.assertEqual(response.context["resumen"]["resueltas"], 1)
        self.assertEqual(response.context["resumen"]["vencidas"], 1)
        self.assertContains(response, 'data-summary-key="pendientes"')
        self.assertContains(response, 'data-summary-key="vencidas"')

    def test_crear_incidencia_devuelve_resumen_actualizado(self):
        hoy = timezone.localdate()
        self._crear_incidencia(
            estado=Incidencia.Estado.PROCESO,
            fecha_limite=hoy - timedelta(days=1),
        )

        response = self.client.post(
            reverse("incidencias:crear_incidencia"),
            {
                "codigo": "INC-999",
                "titulo": "Nueva",
                "descripcion": "Creada por test",
                "responsable": self.user.id,
                "estado": Incidencia.Estado.ABIERTO,
                "prioridad": Incidencia.Prioridad.ALTA,
                "fecha_limite": hoy.isoformat(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["resumen"]["pendientes"], 1)
        self.assertEqual(payload["resumen"]["en_proceso"], 1)
        self.assertEqual(payload["resumen"]["resueltas"], 0)
        self.assertEqual(payload["resumen"]["vencidas"], 1)

    def test_editar_y_eliminar_recalcula_resumen(self):
        hoy = timezone.localdate()
        incidencia = self._crear_incidencia(
            estado=Incidencia.Estado.ABIERTO,
            fecha_limite=hoy - timedelta(days=3),
        )

        editar_response = self.client.post(
            reverse("incidencias:editar_incidencia", args=[incidencia.pk]),
            {
                "codigo": incidencia.codigo,
                "titulo": incidencia.titulo,
                "descripcion": incidencia.descripcion,
                "responsable": self.user.id,
                "estado": Incidencia.Estado.CERRADO,
                "prioridad": incidencia.prioridad,
                "fecha_limite": incidencia.fecha_limite.isoformat(),
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(editar_response.status_code, 200)
        editar_payload = editar_response.json()
        self.assertEqual(editar_payload["resumen"]["pendientes"], 0)
        self.assertEqual(editar_payload["resumen"]["resueltas"], 1)
        self.assertEqual(editar_payload["resumen"]["vencidas"], 0)

        eliminar_response = self.client.post(
            reverse("incidencias:eliminar_incidencia", args=[incidencia.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(eliminar_response.status_code, 200)
        eliminar_payload = eliminar_response.json()
        self.assertEqual(eliminar_payload["resumen"]["pendientes"], 0)
        self.assertEqual(eliminar_payload["resumen"]["en_proceso"], 0)
        self.assertEqual(eliminar_payload["resumen"]["resueltas"], 0)
        self.assertEqual(eliminar_payload["resumen"]["vencidas"], 0)
