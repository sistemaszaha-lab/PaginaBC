from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections
from django.test import Client, TestCase, TransactionTestCase
from django.urls import reverse
from django.utils import timezone

from cuenta_gastos.models import (
    CuentaGastos,
    CuentaGastosColumna,
)
from cuenta_gastos.services import (
    CuentaGastosFleteTransferError,
    crear_copia_flete_desde_operacion,
)
from .models import Operacion, OperacionColumna, OperacionEtiqueta, OperacionOpcion


class CuentaGastosFleteTests(TestCase):
    def setUp(self):
        User = get_user_model()
        self.usuario = User.objects.create_superuser(
            username="flete-admin", email="flete@example.com", password="pass"
        )
        OperacionColumna.objects.update(activa=False)
        CuentaGastosColumna.objects.update(activa=False)
        self.columna_operaciones = OperacionColumna.objects.get(codigo="FACTURA_FLETES_1")
        self.columna_operaciones.activa = True
        self.columna_operaciones.orden = 0
        self.columna_operaciones.save()
        self.columna_gastos = CuentaGastosColumna.objects.get(codigo="FACTURA_FLETES_1")
        self.columna_gastos.activa = True
        self.columna_gastos.save()
        self.operacion = Operacion.objects.create(
            titulo="Flete marítimo",
            descripcion="Contenedor 123",
            prioridad=Operacion.Prioridad.ALTA,
            fecha_vencimiento=date(2026, 12, 10),
            creado_por=self.usuario,
            columna=self.columna_operaciones,
            estado=self.columna_operaciones.codigo,
        )
        self.operacion.asignados.add(self.usuario)
        etiqueta = OperacionEtiqueta.objects.create(nombre="Urgente", color="#123456")
        opcion = OperacionOpcion.objects.create(nombre="Marítimo")
        self.operacion.etiquetas.add(etiqueta)
        self.operacion.opciones.add(opcion)

    def test_crea_copia_independiente_con_datos_y_relaciones_sin_alterar_origen(self):
        estado_original = (self.operacion.estado, self.operacion.columna_id, self.operacion.titulo)

        copia, creada = crear_copia_flete_desde_operacion(
            self.operacion, creado_por=self.usuario
        )

        self.assertTrue(creada)
        self.assertIsNotNone(copia.pk)
        self.assertEqual(copia.operacion_flete_origen_id, self.operacion.pk)
        self.assertIsNone(copia.operacion_origen_id)
        self.assertIsNone(copia.garantia_origen_id)
        self.assertEqual(copia.columna_id, self.columna_gastos.pk)
        self.assertEqual(copia.estado, "FACTURA_FLETES_1")
        self.assertEqual(copia.titulo, self.operacion.titulo)
        self.assertEqual(copia.descripcion, self.operacion.descripcion)
        self.assertEqual(copia.prioridad, self.operacion.prioridad)
        self.assertEqual(copia.fecha_vencimiento, self.operacion.fecha_vencimiento)
        self.assertEqual(list(copia.asignados.all()), [self.usuario])
        self.assertEqual(list(copia.etiquetas.values_list("nombre", flat=True)), ["Urgente"])
        self.assertEqual(list(copia.opciones.values_list("nombre", flat=True)), ["Marítimo"])
        self.operacion.refresh_from_db()
        self.assertEqual(
            (self.operacion.estado, self.operacion.columna_id, self.operacion.titulo),
            estado_original,
        )
        copia.titulo = "Flete editado en Cuenta de Gastos"
        copia.save(update_fields=["titulo"])
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.titulo, estado_original[2])

    def test_eventos_repetidos_reutilizan_la_copia_y_no_ocupan_operacion_origen(self):
        flujo_existente = CuentaGastos.objects.create(
            titulo="Flujo existente",
            creado_por=self.usuario,
            operacion_origen=self.operacion,
        )
        primera, creada = crear_copia_flete_desde_operacion(
            self.operacion, creado_por=self.usuario
        )
        segunda, creada_dos = crear_copia_flete_desde_operacion(
            self.operacion, creado_por=self.usuario
        )

        self.assertTrue(creada)
        self.assertFalse(creada_dos)
        self.assertEqual(primera.pk, segunda.pk)
        self.assertEqual(flujo_existente.operacion_origen_id, self.operacion.pk)
        self.assertEqual(
            CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).count(), 1
        )

    def test_renombrar_ambas_columnas_no_interrumpe_flujo(self):
        OperacionColumna.objects.filter(pk=self.columna_operaciones.pk).update(nombre="Transporte")
        CuentaGastosColumna.objects.filter(pk=self.columna_gastos.pk).update(nombre="Cobros")
        copia, creada = crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario)
        self.assertTrue(creada)
        self.assertEqual(copia.columna_id, self.columna_gastos.pk)

    def test_reentrada_con_copia_en_papelera_no_duplica_ni_sincroniza_relaciones(self):
        copia, _ = crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario)
        copia.eliminado_en = timezone.now()
        copia.save(update_fields=["eliminado_en"])
        copia.asignados.clear()
        copia.etiquetas.clear()
        copia.opciones.clear()
        self.assertEqual(self.operacion.asignados.count(), 1)
        self.assertEqual(self.operacion.etiquetas.count(), 1)
        self.assertEqual(self.operacion.opciones.count(), 1)
        otra = OperacionColumna.objects.create(nombre="Otra", codigo="OTRA")
        self.client.force_login(self.usuario)
        url = reverse("operaciones:mover_operacion", args=[self.operacion.pk])
        self.assertEqual(self.client.post(url, {"estado": otra.codigo}).status_code, 200)
        self.assertEqual(self.client.post(url, {"estado": self.columna_operaciones.codigo}).status_code, 200)
        self.assertEqual(CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).count(), 1)
        self.assertEqual(copia.asignados.count(), 0)

    def test_homonimas_con_otro_codigo_no_disparan_ni_desvian_flujo(self):
        otra = OperacionColumna.objects.create(nombre="Factura de Fletes 1", codigo="OTRO")
        CuentaGastosColumna.objects.create(nombre="Factura de Fletes 1", codigo="OTRO")
        copia, creada = crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario)
        self.assertTrue(creada)
        self.assertEqual(copia.columna_id, self.columna_gastos.pk)
        self.operacion.columna = otra
        self.operacion.estado = otra.codigo
        self.operacion.save()
        self.assertEqual(crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario), (None, False))

    def test_detiene_si_falta_columna_flete_en_origen_o_destino(self):
        self.columna_operaciones.activa = False
        self.columna_operaciones.save(update_fields=["activa"])
        with self.assertLogs("cuenta_gastos.services", level="ERROR"):
            with self.assertRaisesRegex(CuentaGastosFleteTransferError, "Operaciones"):
                crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario)

        self.columna_operaciones.activa = True
        self.columna_operaciones.save(update_fields=["activa"])
        self.columna_gastos.activa = False
        self.columna_gastos.save(update_fields=["activa"])
        with self.assertLogs("cuenta_gastos.services", level="ERROR"):
            with self.assertRaisesRegex(CuentaGastosFleteTransferError, "Cuenta de Gastos"):
                crear_copia_flete_desde_operacion(self.operacion, creado_por=self.usuario)
        self.assertFalse(CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).exists())

    def test_al_mover_tarjeta_se_crea_copia_automatica_y_repetir_no_duplica(self):
        otra_columna = OperacionColumna.objects.create(
            nombre="Pendientes", codigo="OPS_PENDIENTE_TEST", activa=True
        )
        self.operacion.columna = otra_columna
        self.operacion.estado = otra_columna.codigo
        self.operacion.save(update_fields=["columna", "estado"])
        self.client = Client()
        self.client.force_login(self.usuario)
        url = reverse("operaciones:mover_operacion", args=[self.operacion.pk])

        primera = self.client.post(
            url,
            {"estado": self.columna_operaciones.codigo},
        )
        segunda = self.client.post(
            url,
            {"estado": self.columna_operaciones.codigo},
        )

        self.assertEqual(primera.status_code, 200)
        self.assertEqual(segunda.status_code, 200)
        self.assertTrue(primera.json()["cuenta_gastos_flete_creada"])
        self.assertFalse(segunda.json()["cuenta_gastos_flete_creada"])
        self.assertEqual(
            CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).count(), 1
        )
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.columna_id, self.columna_operaciones.pk)

    def test_crear_operacion_directamente_en_factura_de_fletes_crea_copia(self):
        self.client = Client()
        self.client.force_login(self.usuario)
        response = self.client.post(
            reverse("operaciones:crear_operacion_inline"),
            {
                "titulo": "Flete creado en origen",
                "estado": self.columna_operaciones.codigo,
                "asignados": [str(self.usuario.pk)],
            },
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )

        self.assertEqual(response.status_code, 201, response.content)
        operacion = Operacion.objects.get(titulo="Flete creado en origen")
        copia = CuentaGastos.objects.get(operacion_flete_origen=operacion)
        self.assertEqual(copia.columna_id, self.columna_gastos.pk)
        self.assertEqual(copia.estado, self.columna_gastos.codigo)
        self.assertEqual(operacion.columna_id, self.columna_operaciones.pk)

    def test_movimiento_a_flete_sin_destino_se_revierte_y_devuelve_error(self):
        otra_columna = OperacionColumna.objects.create(
            nombre="Pendientes", codigo="OPS_PENDIENTE_TEST", activa=True
        )
        self.operacion.columna = otra_columna
        self.operacion.estado = otra_columna.codigo
        self.operacion.save(update_fields=["columna", "estado"])
        CuentaGastosColumna.objects.filter(pk=self.columna_gastos.pk).update(activa=False)
        self.client = Client()
        self.client.force_login(self.usuario)
        response = self.client.post(
            reverse("operaciones:mover_operacion", args=[self.operacion.pk]),
            {"estado": self.columna_operaciones.codigo},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("FACTURA_FLETES_1", response.json()["error"])
        self.operacion.refresh_from_db()
        self.assertEqual(self.operacion.columna_id, otra_columna.pk)
        self.assertFalse(CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).exists())


class CuentaGastosFleteConcurrencyTests(TransactionTestCase):
    reset_sequences = True

    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="flete-race")
        OperacionColumna.objects.update(activa=False)
        CuentaGastosColumna.objects.update(activa=False)
        self.columna_operaciones = OperacionColumna.objects.update_or_create(
            codigo="FACTURA_FLETES_1", defaults={"nombre": "Factura de Fletes 1", "activa": True}
        )[0]
        self.columna_gastos = CuentaGastosColumna.objects.update_or_create(
            codigo="FACTURA_FLETES_1", defaults={"nombre": "Factura de Fletes 1", "activa": True}
        )[0]
        self.operacion = Operacion.objects.create(
            titulo="Concurrencia",
            creado_por=self.usuario,
            columna=self.columna_operaciones,
            estado=self.columna_operaciones.codigo,
        )

    def test_eventos_concurrentes_producen_una_sola_copia(self):
        barrera = Barrier(2)

        def ejecutar():
            close_old_connections()
            try:
                barrera.wait(timeout=5)
                cuenta, creada = crear_copia_flete_desde_operacion(
                    Operacion.objects.get(pk=self.operacion.pk),
                    creado_por=get_user_model().objects.get(pk=self.usuario.pk),
                )
                return cuenta.pk, creada
            finally:
                close_old_connections()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _index: ejecutar(), range(2)))

        self.assertEqual(len({pk for pk, _creada in resultados}), 1)
        self.assertEqual(sum(creada for _pk, creada in resultados), 1)
        self.assertEqual(
            CuentaGastos.objects.filter(operacion_flete_origen=self.operacion).count(), 1
        )
