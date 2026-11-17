from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import close_old_connections, connection
from django.test import RequestFactory, TestCase, TransactionTestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from cuenta_gastos.models import CuentaGastos, CuentaGastosColumna
from cuenta_gastos.services import (
    crear_copia_anticipo_desde_operacion,
    operacion_elegible_para_anticipo,
)
from solicitudes.models import Referencia
from .models import Operacion, OperacionColumna
from .views import _columnas_kanban, _render_card_html


class AnticipoTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_user(username="anticipo", password="pass")
        self.otro = get_user_model().objects.create_user(username="sin-permiso")
        self.columna, _ = OperacionColumna.objects.get_or_create(
            codigo=Operacion.Estado.PENDIENTE,
            defaults={"nombre": Operacion.Estado.PENDIENTE.label},
        )
        self.destino, _ = CuentaGastosColumna.objects.get_or_create(
            codigo=CuentaGastos.Estado.FACTURA_ANTICIPO,
            defaults={"nombre": CuentaGastos.Estado.FACTURA_ANTICIPO.label},
        )
        self.client.force_login(self.usuario)

    def crear_operacion(self, codigo, servicio, *, consecutivo=1, columna=None):
        ref = Referencia.objects.create(
            referencia=codigo, consecutivo=consecutivo, servicio=servicio,
            fecha=date(2026, 1, 1),
        ) if codigo else None
        operacion = Operacion.objects.create(
            titulo=f"Operación {codigo}", descripcion="Datos de origen",
            creado_por=self.usuario, referencia_origen=ref,
            columna=columna or self.columna,
            estado=(columna or self.columna).codigo,
        )
        operacion.asignados.add(self.usuario)
        return operacion

    def test_tipos_5_y_6_de_cualquier_anio_con_consecutivo_completo(self):
        for anio in (26, 27, 28, 35):
            for tipo, servicio in ((5, "comercializador_importacion"),
                                   (6, "comercializador_exportacion")):
                with self.subTest(anio=anio, tipo=tipo):
                    op = self.crear_operacion(
                        f"BC{anio}{tipo}{anio * 100 + tipo}", servicio,
                        consecutivo=anio * 100 + tipo,
                    )
                    self.assertTrue(operacion_elegible_para_anticipo(op))
        antigua = self.crear_operacion(
            "BC265999", "comercializador_importacion", consecutivo=999,
        )
        antigua.referencia_origen.fecha = date(2027, 1, 1)
        antigua.referencia_origen.save(update_fields=["fecha"])
        self.assertTrue(operacion_elegible_para_anticipo(antigua))

    def test_rechaza_otros_tipos_y_codigos_ambiguos(self):
        casos = (
            ("BC261005", "importacion", 5),
            ("BC261006", "comercializador_importacion", 6),
            ("BC266006", "comercializador_importacion", 6),
            ("BC265", "comercializador_importacion", 5),
            ("BC2650006X", "comercializador_importacion", 6),
        )
        for codigo, servicio, consecutivo in casos:
            with self.subTest(codigo=codigo):
                op = self.crear_operacion(codigo, servicio, consecutivo=consecutivo)
                self.assertFalse(operacion_elegible_para_anticipo(op))
                response = self.client.post(reverse("operaciones:solicitar_factura_anticipo", args=[op.pk]))
                self.assertEqual(response.status_code, 400)
        self.assertFalse(operacion_elegible_para_anticipo(self.crear_operacion(None, None)))

    def test_copia_manual_conserva_origen_y_no_duplica(self):
        op = self.crear_operacion("BC2651234", "comercializador_importacion", consecutivo=1234)
        url = reverse("operaciones:solicitar_factura_anticipo", args=[op.pk])
        self.assertEqual(self.client.post(url).status_code, 200)
        self.assertFalse(self.client.post(url).json()["creada"])
        copia = CuentaGastos.objects.get(operacion_anticipo_origen=op)
        self.assertEqual(copia.columna_id, self.destino.pk)
        self.assertEqual(copia.estado, self.destino.codigo)
        self.assertEqual((copia.titulo, copia.descripcion), (op.titulo, op.descripcion))
        self.assertEqual(copia.operacion_anticipo_origen.referencia_origen.referencia, "BC2651234")
        self.assertEqual(copia.referencia_anticipo_codigo, "BC2651234")
        self.assertIsNone(copia.operacion_origen_id)
        op.refresh_from_db()
        self.assertEqual((op.estado, op.columna_id), (self.columna.codigo, self.columna.pk))
        self.assertEqual(CuentaGastos.objects.filter(operacion_anticipo_origen=op).count(), 1)

    def test_permisos_columna_inactiva_y_boton_en_cualquier_columna(self):
        otra_columna, _ = OperacionColumna.objects.get_or_create(
            codigo=Operacion.Estado.COORDINAR_PICKUP,
            defaults={"nombre": Operacion.Estado.COORDINAR_PICKUP.label},
        )
        op1 = self.crear_operacion("BC265001", "comercializador_importacion")
        op2 = self.crear_operacion("BC276002", "comercializador_exportacion", consecutivo=2, columna=otra_columna)
        tarjetas = [item for columna in _columnas_kanban(self.usuario) for item in columna["items"]]
        self.assertTrue(next(item for item in tarjetas if item.pk == op1.pk).puede_solicitar_anticipo)
        self.assertTrue(next(item for item in tarjetas if item.pk == op2.pk).puede_solicitar_anticipo)
        request = RequestFactory().get("/operaciones/")
        request.user = self.usuario
        self.assertIn("Solicitar factura por anticipo", _render_card_html(request, op1))
        self.assertIn("Solicitar factura por anticipo", _render_card_html(request, op2))
        sin_ref = self.crear_operacion(None, None)
        self.assertNotIn("Solicitar factura por anticipo", _render_card_html(request, sin_ref))
        self.client.force_login(self.otro)
        self.assertEqual(self.client.post(reverse("operaciones:solicitar_factura_anticipo", args=[op1.pk])).status_code, 403)
        self.client.force_login(self.usuario)
        self.destino.activa = False
        self.destino.save(update_fields=["activa"])
        response = self.client.post(reverse("operaciones:solicitar_factura_anticipo", args=[op2.pk]))
        self.assertEqual(response.status_code, 400)
        self.assertIn("FACTURA_ANTICIPO", response.json()["error"])
        self.assertFalse(CuentaGastos.objects.filter(operacion_anticipo_origen=op2).exists())

    def test_tarjeta_conserva_permisos_de_propietario_asignado_grupos_y_solo_lectura(self):
        op = self.crear_operacion("BC265400", "comercializador_importacion", consecutivo=400)
        request = RequestFactory().get("/operaciones/")

        def tiene_boton(usuario):
            request.user = usuario
            return "Solicitar factura por anticipo" in _render_card_html(request, op)

        self.assertTrue(tiene_boton(self.usuario))  # creador
        self.assertFalse(tiene_boton(self.otro))
        op.asignados.add(self.otro)
        self.assertTrue(tiene_boton(self.otro))  # asignado

        tercero = get_user_model().objects.create_user(username="anticipo-tercero")
        self.assertFalse(tiene_boton(tercero))
        grupo = Group.objects.create(name="EJECUTIVO OPERACIONES")
        tercero.groups.add(grupo)
        self.assertTrue(tiene_boton(tercero))  # acceso global por grupo
        tercero.groups.remove(grupo)
        tercero.is_staff = True
        tercero.save(update_fields=["is_staff"])
        self.assertTrue(tiene_boton(tercero))  # staff
        tercero.groups.add(Group.objects.get_or_create(name="SOLO_LECTURA")[0])
        self.assertFalse(tiene_boton(tercero))  # solo lectura prevalece en la tarjeta

    def test_consultas_de_permisos_del_tablero_no_crecen_con_tarjetas(self):
        def agregar(numero):
            ref = Referencia.objects.create(
                referencia=f"BC265{numero:03d}", consecutivo=numero,
                servicio="comercializador_importacion",
            )
            op = Operacion.objects.create(
                titulo=f"Asignada {numero}", creado_por=self.otro,
                columna=self.columna, estado=self.columna.codigo,
                referencia_origen=ref,
            )
            op.asignados.add(self.usuario)

        agregar(1)
        with CaptureQueriesContext(connection) as pocas:
            primera = _columnas_kanban(self.usuario)
        for numero in range(2, 22):
            agregar(numero)
        with CaptureQueriesContext(connection) as muchas:
            segunda = _columnas_kanban(self.usuario)
        tarjetas = [item for columna in segunda for item in columna["items"]]
        self.assertEqual(sum(len(columna["items"]) for columna in primera), 1)
        self.assertEqual(len(tarjetas), 21)
        self.assertTrue(all(item.puede_solicitar_anticipo for item in tarjetas))
        self.assertLessEqual(len(muchas), len(pocas) + 1)

    def test_esquema_acepta_insercion_heredada_que_omite_campo_nuevo(self):
        origen = CuentaGastos.objects.create(titulo="Fila heredada", creado_por=self.usuario)
        meta = CuentaGastos._meta
        columns = [
            field.column for field in meta.local_concrete_fields
            if not field.primary_key
            and field.name not in {"operacion_anticipo_origen", "referencia_anticipo_codigo"}
        ]
        quote = connection.ops.quote_name
        names = ", ".join(quote(column) for column in columns)
        with connection.cursor() as cursor:
            cursor.execute(
                f"INSERT INTO {quote(meta.db_table)} ({names}) "
                f"SELECT {names} FROM {quote(meta.db_table)} "
                f"WHERE {quote(meta.pk.column)} = %s RETURNING {quote(meta.pk.column)}",
                [origen.pk],
            )
            legacy_pk = cursor.fetchone()[0]
        heredada = CuentaGastos.objects.get(pk=legacy_pk)
        self.assertEqual(heredada.referencia_anticipo_codigo, "")
        self.assertIsNone(heredada.operacion_anticipo_origen_id)


class AnticipoConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.columna, _ = OperacionColumna.objects.get_or_create(
            codigo=Operacion.Estado.PENDIENTE,
            defaults={"nombre": Operacion.Estado.PENDIENTE.label},
        )
        CuentaGastosColumna.objects.get_or_create(
            codigo=CuentaGastos.Estado.FACTURA_ANTICIPO,
            defaults={"nombre": CuentaGastos.Estado.FACTURA_ANTICIPO.label},
        )

    def test_solicitudes_concurrentes_crean_una_copia(self):
        usuario = get_user_model().objects.create_user(username="anticipo-concurrente")
        columna = self.columna
        ref = Referencia.objects.create(
            referencia="BC285001", consecutivo=1,
            servicio="comercializador_importacion",
        )
        op = Operacion.objects.create(
            titulo="Concurrencia", creado_por=usuario, columna=columna,
            estado=columna.codigo, referencia_origen=ref,
        )
        barrera = Barrier(2)

        def ejecutar():
            close_old_connections()
            try:
                barrera.wait(timeout=5)
                return crear_copia_anticipo_desde_operacion(
                    Operacion.objects.get(pk=op.pk),
                    creado_por=get_user_model().objects.get(pk=usuario.pk),
                )
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=2) as executor:
            resultados = list(executor.map(lambda _: ejecutar(), range(2)))
        self.assertEqual(len({cuenta.pk for cuenta, _ in resultados}), 1)
        self.assertEqual(sum(creada for _, creada in resultados), 1)
        self.assertEqual(CuentaGastos.objects.filter(operacion_anticipo_origen=op).count(), 1)
