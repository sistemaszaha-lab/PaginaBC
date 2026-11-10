from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from .models import (
    CuentaGastos,
    CuentaGastosColumna,
    CuentaGastosEtiqueta,
    CuentaGastosOpcion,
)
from .services import (
    CuentaGastosAutomationError,
    crear_copia_vobo_angie_si_corresponde,
    copiar_cuenta_gastos_a_columna,
)


class VoBoAngieSolicitudesGeoTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(
            username="vobo-automation-admin",
            email="vobo@example.com",
            password="pass",
        )
        self.client.force_login(self.usuario)
        CuentaGastosColumna.objects.update(activa=False)
        self.origen = CuentaGastosColumna.objects.get(codigo="VOBO_ANGIE")
        self.origen.activa = True
        self.origen.save()
        self.destino = CuentaGastosColumna.objects.get(codigo="SOLICITUDES_GEO_1")
        self.destino.activa = True
        self.destino.save()
        self.otra = CuentaGastosColumna.objects.create(
            nombre="Pendientes", codigo="CUSTOM_PENDING", orden=3
        )
        self.etiqueta = CuentaGastosEtiqueta.objects.create(
            nombre="Urgente Geo", color="#123456"
        )
        self.opcion = CuentaGastosOpcion.objects.create(nombre="Enviar XML")

    def _cuenta(self, *, columna=None, titulo="Solicitud de origen"):
        cuenta = CuentaGastos.objects.create(
            titulo=titulo,
            descripcion="Detalle que debe conservarse",
            prioridad=CuentaGastos.Prioridad.ALTA,
            creado_por=self.usuario,
            columna=columna or self.otra,
            estado=(columna or self.otra).codigo,
        )
        cuenta.asignados.add(self.usuario)
        cuenta.etiquetas.add(self.etiqueta)
        cuenta.opciones.add(self.opcion)
        return cuenta

    def _assert_copia(self, origen):
        copia = CuentaGastos.objects.get(vobo_angie_origen=origen)
        self.assertNotEqual(copia.pk, origen.pk)
        self.assertEqual(copia.columna_id, self.destino.pk)
        self.assertEqual(copia.estado, self.destino.codigo)
        self.assertEqual(copia.titulo, origen.titulo)
        self.assertEqual(copia.descripcion, origen.descripcion)
        self.assertEqual(copia.prioridad, origen.prioridad)
        self.assertEqual(list(copia.asignados.all()), [self.usuario])
        self.assertEqual(list(copia.etiquetas.all()), [self.etiqueta])
        self.assertEqual(list(copia.opciones.all()), [self.opcion])
        self.assertIsNone(copia.operacion_origen_id)
        self.assertIsNone(copia.operacion_flete_origen_id)
        self.assertIsNone(copia.garantia_origen_id)
        return copia

    def test_creacion_directa_en_vobo_crea_una_copia_con_relaciones(self):
        response = self.client.post(
            reverse("cuenta_gastos:crear_cuenta_gastos_inline"),
            {
                "titulo": "Directa en VoBo",
                "descripcion": "Datos preservados",
                "prioridad": CuentaGastos.Prioridad.ALTA,
                "estado": self.origen.codigo,
                "asignados": [str(self.usuario.pk)],
                "etiquetas": [str(self.etiqueta.pk)],
                "opciones": [str(self.opcion.pk)],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201, response.content)
        origen = CuentaGastos.objects.get(
            titulo="Directa en VoBo", columna=self.origen
        )
        self.assertEqual(origen.columna_id, self.origen.pk)
        copia = self._assert_copia(origen)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=origen).count(), 1)
        copia.titulo = "Edición independiente"
        copia.save(update_fields=["titulo"])
        origen.refresh_from_db()
        self.assertEqual(origen.titulo, "Directa en VoBo")

    def test_movimiento_a_vobo_crea_copia_y_repetir_es_idempotente(self):
        origen = self._cuenta()
        url = reverse("cuenta_gastos:mover_cuenta_gastos", args=[origen.pk])

        primera = self.client.post(
            url,
            {"estado": self.origen.codigo, "columna_id": self.origen.pk},
        )
        segunda = self.client.post(
            url,
            {"estado": self.origen.codigo, "columna_id": self.origen.pk},
        )

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        origen.refresh_from_db()
        self.assertEqual(origen.columna_id, self.origen.pk)
        self._assert_copia(origen)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=origen).count(), 1)

    def test_otro_flujo_que_genera_una_tarjeta_en_vobo_activa_la_copia(self):
        original = self._cuenta(titulo="Copiada a VoBo")

        copia_flujo = copiar_cuenta_gastos_a_columna(
            original, self.origen, self.usuario
        )

        self.assertEqual(copia_flujo.columna_id, self.origen.pk)
        geo = self._assert_copia(copia_flujo)
        self.assertNotEqual(geo.pk, copia_flujo.pk)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=copia_flujo).count(), 1)

    def test_servicio_es_idempotente_y_no_recursa_desde_solicitudes_geo(self):
        origen = self._cuenta(columna=self.origen)

        primera, creada = crear_copia_vobo_angie_si_corresponde(
            origen, creado_por=self.usuario
        )
        segunda, creada_de_nuevo = crear_copia_vobo_angie_si_corresponde(
            origen, creado_por=self.usuario
        )
        respuesta_destino = crear_copia_vobo_angie_si_corresponde(
            primera, creado_por=self.usuario
        )

        self.assertTrue(creada)
        self.assertFalse(creada_de_nuevo)
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(respuesta_destino, (None, False))
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=origen).count(), 1)

    def test_reentrada_con_copia_en_papelera_no_duplica_ni_sincroniza_relaciones(self):
        origen = self._cuenta(columna=self.origen)
        copia, _ = crear_copia_vobo_angie_si_corresponde(origen, creado_por=self.usuario)
        copia.eliminado_en = timezone.now()
        copia.save(update_fields=["eliminado_en"])
        copia.asignados.clear()
        copia.etiquetas.clear()
        copia.opciones.clear()
        origen.refresh_from_db()
        self.assertEqual(origen.asignados.count(), 1)
        self.assertEqual(origen.etiquetas.count(), 1)
        self.assertEqual(origen.opciones.count(), 1)
        url = reverse("cuenta_gastos:mover_cuenta_gastos", args=[origen.pk])
        self.assertEqual(self.client.post(url, {"estado": self.otra.codigo}).status_code, 200)
        self.assertEqual(self.client.post(url, {"estado": self.origen.codigo}).status_code, 200)
        self.assertEqual(CuentaGastos.objects.filter(vobo_angie_origen=origen).count(), 1)
        self.assertEqual(copia.asignados.count(), 0)

    def test_columna_destino_inactiva_no_mueve_ni_duplica(self):
        origen = self._cuenta()
        url = reverse("cuenta_gastos:mover_cuenta_gastos", args=[origen.pk])
        self.destino.activa = False
        self.destino.save(update_fields=["activa"])
        response = self.client.post(
            url, {"estado": self.origen.codigo, "columna_id": self.origen.pk}
        )
        self.assertEqual(response.status_code, 400)
        origen.refresh_from_db()
        self.assertEqual(origen.columna_id, self.otra.pk)
        self.assertFalse(CuentaGastos.objects.filter(vobo_angie_origen=origen).exists())

    def test_renombrar_columnas_y_homonimas_no_interrumpe_flujo(self):
        self.origen.nombre = "Revisión contable"
        self.origen.save(update_fields=["nombre"])
        self.destino.nombre = "Envíos"
        self.destino.save(update_fields=["nombre"])
        homonima = CuentaGastosColumna.objects.create(nombre="VoBo Angie", codigo="VOBO_DUPLICADO")
        CuentaGastosColumna.objects.create(nombre="Solicitudes a Geo 1", codigo="GEO_DUPLICADO")
        origen = self._cuenta(columna=self.origen)
        copia, creada = crear_copia_vobo_angie_si_corresponde(origen, creado_por=self.usuario)
        self.assertTrue(creada)
        self.assertEqual(copia.columna_id, self.destino.pk)
        self.assertEqual(crear_copia_vobo_angie_si_corresponde(
            self._cuenta(columna=homonima), creado_por=self.usuario), (None, False))

    def test_columna_origen_inactiva_falla_sin_crear_copia(self):
        origen = self._cuenta(columna=self.origen)
        self.origen.activa = False
        self.origen.save(update_fields=["activa"])

        with self.assertRaisesRegex(CuentaGastosAutomationError, "VOBO_ANGIE"):
            crear_copia_vobo_angie_si_corresponde(
                origen, creado_por=self.usuario
            )

        self.assertFalse(CuentaGastos.objects.filter(vobo_angie_origen=origen).exists())


class VoBoAngieSolicitudesGeoConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(
            username="vobo-race", password="pass"
        )
        CuentaGastosColumna.objects.update(activa=False)
        self.origen_columna = CuentaGastosColumna.objects.update_or_create(
            codigo="VOBO_ANGIE", defaults={"nombre": "VoBo Angie", "activa": True}
        )[0]
        self.destino_columna = CuentaGastosColumna.objects.update_or_create(
            codigo="SOLICITUDES_GEO_1", defaults={"nombre": "Solicitudes a Geo 1", "activa": True}
        )[0]
        self.origen = CuentaGastos.objects.create(
            titulo="Concurrencia VoBo",
            creado_por=self.usuario,
            columna=self.origen_columna,
            estado=self.origen_columna.codigo,
        )

    def test_eventos_concurrentes_crean_una_sola_copia(self):
        barrera = Barrier(2)

        def ejecutar():
            close_old_connections()
            try:
                barrera.wait(timeout=5)
                cuenta = CuentaGastos.objects.get(pk=self.origen.pk)
                usuario = get_user_model().objects.get(pk=self.usuario.pk)
                copia, creada = crear_copia_vobo_angie_si_corresponde(
                    cuenta, creado_por=usuario
                )
                return copia.pk, creada
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _index: ejecutar(), range(2)))

        self.assertEqual(len({pk for pk, _creada in resultados}), 1)
        self.assertEqual(sum(creada for _pk, creada in resultados), 1)
        self.assertEqual(
            CuentaGastos.objects.filter(vobo_angie_origen=self.origen).count(), 1
        )

