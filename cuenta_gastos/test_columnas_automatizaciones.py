from importlib import import_module
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.loader import MigrationLoader
from django.test import TestCase, RequestFactory, modify_settings
from django.urls import reverse

from operaciones.models import Operacion, OperacionColumna
from operaciones.services import copiar_operacion_a_columna
from .models import CuentaGastos, CuentaGastosColumna


class MigracionColumnasTests(TestCase):
    def setUp(self):
        self.migracion = import_module('cuenta_gastos.migrations.0014_columnas_automatizaciones')
        self.historicos = MigrationLoader(connection).project_state([
            ('cuenta_gastos', '0013_cuentagastos_vobo_angie_origen'),
        ]).apps
        self.schema = SimpleNamespace(connection=connection)
        OperacionColumna.objects.filter(codigo='FACTURA_FLETES_1').delete()
        CuentaGastosColumna.objects.filter(codigo__in=['FACTURA_FLETES_1', 'SOLICITUDES_GEO_1']).delete()

    def ejecutar(self):
        self.migracion.crear_columnas(self.historicos, self.schema)

    def catalogo(self):
        return [list(m.objects.order_by('pk').values()) for m in (OperacionColumna, CuentaGastosColumna)]

    def test_crea_al_final_con_defaults_y_conserva_todas_las_filas_existentes(self):
        antes = self.catalogo()
        self.ejecutar()
        for modelo, filas in zip((OperacionColumna, CuentaGastosColumna), antes):
            self.assertEqual(list(modelo.objects.filter(pk__in=[f['id'] for f in filas]).order_by('pk').values()), filas)
            flete = modelo.objects.get(codigo='FACTURA_FLETES_1')
            self.assertEqual(flete.orden, max(f['orden'] for f in filas) + 1)
            self.assertTrue(flete.activa)
            self.assertIsNone(flete.creada_por_id)
        self.assertTrue(OperacionColumna.objects.get(codigo='FACTURA_FLETES_1').visible_para_todos)
        self.assertEqual(CuentaGastosColumna.objects.get(codigo='SOLICITUDES_GEO_1').color_fondo, '#F8F9FA')

    def test_repeticion_y_reversion_no_modifican_ni_borran_columnas_renombradas(self):
        self.ejecutar()
        OperacionColumna.objects.filter(codigo='FACTURA_FLETES_1').update(nombre='Transporte')
        CuentaGastosColumna.objects.filter(codigo='FACTURA_FLETES_1').update(nombre='Cobros')
        CuentaGastosColumna.objects.filter(codigo='SOLICITUDES_GEO_1').update(nombre='Envíos')
        CuentaGastosColumna.objects.filter(codigo='VOBO_ANGIE').update(nombre='Revisión')
        antes = self.catalogo()
        with self.assertRaisesRegex(RuntimeError, 'ya está ocupado'):
            self.ejecutar()
        self.migracion.Migration.operations[0].reverse_code(self.historicos, self.schema)
        self.assertEqual(self.catalogo(), antes)

    def test_codigo_reservado_ocupado_detiene_migracion_sin_modificar_catalogo(self):
        for modelo, codigo in (
            (OperacionColumna, 'FACTURA_FLETES_1'),
            (CuentaGastosColumna, 'FACTURA_FLETES_1'),
            (CuentaGastosColumna, 'SOLICITUDES_GEO_1'),
        ):
            with self.subTest(codigo=codigo, modelo=modelo):
                conflicto = modelo.objects.create(codigo=codigo, nombre='Columna Existente')
                antes = self.catalogo()
                with self.assertRaisesRegex(RuntimeError, 'ya está ocupado'):
                    self.ejecutar()
                self.assertEqual(self.catalogo(), antes)
                conflicto.delete()

    def test_conflictos_detienen_todo_antes_de_escribir(self):
        for modelo, codigo, nombre in (
            (OperacionColumna, 'FACTURA_FLETES_1', 'Factura de Fletes 1'),
            (CuentaGastosColumna, 'FACTURA_FLETES_1', 'Factura de Fletes 1'),
            (CuentaGastosColumna, 'SOLICITUDES_GEO_1', 'Solicitudes a Geo 1'),
            (CuentaGastosColumna, 'VOBO_ANGIE', 'VoBo Angie'),
        ):
            with self.subTest(codigo=codigo, modelo=modelo):
                conflicto = modelo.objects.create(codigo='CODIGO_CLIENTE', nombre=nombre)
                antes = self.catalogo()
                with self.assertRaisesRegex(RuntimeError, 'ambiguo'):
                    self.ejecutar()
                self.assertEqual(self.catalogo(), antes)
                conflicto.delete()

    def test_vobo_con_codigo_cambiado_no_se_adopta_por_nombre(self):
        CuentaGastosColumna.objects.filter(codigo='VOBO_ANGIE').update(codigo='CODIGO_CLIENTE')
        antes = self.catalogo()
        with self.assertRaises(RuntimeError):
            self.ejecutar()
        self.assertEqual(self.catalogo(), antes)

    def test_vobo_ausente_o_inactivo_impide_crear_destinos(self):
        vobo = CuentaGastosColumna.objects.get(codigo='VOBO_ANGIE')
        vobo.activa = False
        vobo.save()
        with self.assertRaisesRegex(RuntimeError, 'inactivo'):
            self.ejecutar()
        vobo.delete()
        with self.assertRaisesRegex(RuntimeError, 'Falta el código histórico'):
            self.ejecutar()
        self.assertFalse(OperacionColumna.objects.filter(codigo='FACTURA_FLETES_1').exists())

    def test_destino_reservado_inactivo_es_conflicto_y_no_se_reactiva(self):
        CuentaGastosColumna.objects.create(codigo='SOLICITUDES_GEO_1', nombre='Privada', activa=False)
        antes = self.catalogo()
        with self.assertRaisesRegex(RuntimeError, 'inactivo'):
            self.ejecutar()
        self.assertEqual(self.catalogo(), antes)


class EntradasAdicionalesTests(TestCase):
    def setUp(self):
        self.usuario = get_user_model().objects.create_superuser(username='entradas', password='pass')
        self.client.force_login(self.usuario)
        self.vobo = CuentaGastosColumna.objects.get(codigo='VOBO_ANGIE')
        self.geo = CuentaGastosColumna.objects.get(codigo='SOLICITUDES_GEO_1')

    def test_reasignacion_por_eliminar_columna_activa_vobo_y_revierte_si_falta_destino(self):
        columna = CuentaGastosColumna.objects.create(nombre='Temporal', codigo='TEMP')
        cuenta = CuentaGastos.objects.create(creado_por=self.usuario, columna=columna)
        self.geo.activa = False
        self.geo.save()
        url = reverse('cuenta_gastos:columna_eliminar', args=[columna.pk])
        datos = {'columna_destino_id': self.vobo.pk}
        respuesta = self.client.post(url, datos, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(respuesta.status_code, 400)
        cuenta.refresh_from_db()
        columna.refresh_from_db()
        self.assertEqual(cuenta.columna_id, columna.pk)
        self.assertTrue(columna.activa)
        self.geo.activa = True
        self.geo.save()
        respuesta = self.client.post(url, datos, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        self.assertEqual(respuesta.status_code, 200)
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.columna_id, self.vobo.pk)
        self.assertEqual(CuentaGastos.objects.get(vobo_angie_origen=cuenta).columna_id, self.geo.pk)

    def test_copiar_operacion_a_flete_activa_flujo_con_relaciones_finales(self):
        origen = Operacion.objects.create(creado_por=self.usuario, titulo='Copiar')
        origen.asignados.add(self.usuario)
        columna = OperacionColumna.objects.get(codigo='FACTURA_FLETES_1')
        nueva = copiar_operacion_a_columna(origen, columna, self.usuario)
        cuenta = CuentaGastos.objects.get(operacion_flete_origen=nueva)
        self.assertEqual(list(cuenta.asignados.all()), [self.usuario])
        self.assertEqual(cuenta.columna.codigo, 'FACTURA_FLETES_1')
        self.assertFalse(CuentaGastos.objects.filter(operacion_flete_origen=origen).exists())

    def test_editar_nombre_por_panel_ignora_codigo_en_post(self):
        for modelo, modulo, codigos in (
            (OperacionColumna, 'operaciones', ['FACTURA_FLETES_1']),
            (CuentaGastosColumna, 'cuenta_gastos', ['FACTURA_FLETES_1', 'VOBO_ANGIE', 'SOLICITUDES_GEO_1']),
        ):
            for codigo in codigos:
                columna = modelo.objects.get(codigo=codigo)
                respuesta = self.client.post(reverse(f'{modulo}:columna_editar', args=[columna.pk]),
                    {'nombre': 'Nombre editable', 'codigo': 'CAMBIO', 'color_fondo': '#F8F9FA', 'visible_para_todos': 'on'},
                    HTTP_X_REQUESTED_WITH='XMLHttpRequest')
                self.assertEqual(respuesta.status_code, 200, respuesta.content)
                columna.refresh_from_db()
                self.assertEqual(columna.nombre, 'Nombre editable')
                self.assertEqual(columna.codigo, codigo)


@modify_settings(INSTALLED_APPS={'append': 'django.contrib.admin'})
class AdministracionColumnasTests(TestCase):
    def setUp(self):
        from django.contrib.admin.sites import AdminSite
        self.site = AdminSite()
        self.request = RequestFactory().post('/')
        self.request.user = get_user_model().objects.create_superuser(username='admin-columnas', password='pass')

    def test_admin_permite_renombrar_e_ignora_manipulacion_de_codigos_reservados(self):
        from operaciones.admin import OperacionColumnaAdmin
        from cuenta_gastos.admin import CuentaGastosColumnaAdmin
        for modelo, admin_class, codigos in (
            (OperacionColumna, OperacionColumnaAdmin, ['FACTURA_FLETES_1']),
            (CuentaGastosColumna, CuentaGastosColumnaAdmin, ['FACTURA_FLETES_1', 'VOBO_ANGIE', 'SOLICITUDES_GEO_1']),
        ):
            administrador = admin_class(modelo, self.site)
            for codigo in codigos:
                columna = modelo.objects.get(codigo=codigo)
                Form = administrador.get_form(self.request, columna)
                form = Form({'nombre': 'Nuevo nombre', 'codigo': 'MANIPULADO', 'orden': columna.orden,
                    'activa': 'on', 'visible_para_todos': 'on', 'color_fondo': '#F8F9FA'}, instance=columna)
                self.assertNotIn('codigo', form.fields)
                self.assertTrue(form.is_valid(), form.errors)
                form.save()
                columna.refresh_from_db()
                self.assertEqual(columna.codigo, codigo)
                self.assertEqual(columna.nombre, 'Nuevo nombre')

    def test_admin_crea_y_mueve_tarjetas_y_copia_m2m_una_sola_vez(self):
        from operaciones.admin import OperacionAdmin
        from cuenta_gastos.admin import CuentaGastosAdmin
        for modelo, admin_class, columna in (
            (Operacion, OperacionAdmin, OperacionColumna.objects.get(codigo='FACTURA_FLETES_1')),
            (CuentaGastos, CuentaGastosAdmin, CuentaGastosColumna.objects.get(codigo='VOBO_ANGIE')),
        ):
            administrador = admin_class(modelo, self.site)
            for nueva in (True, False):
                obj = None if nueva else modelo.objects.create(creado_por=self.request.user)
                Form = administrador.get_form(self.request, obj)
                form = Form({'titulo': 'Desde admin', 'columna': columna.pk, 'prioridad': 'MEDIA',
                    'creado_por': self.request.user.pk, 'asignados': [self.request.user.pk], 'posicion': 0}, instance=obj)
                self.assertTrue(form.is_valid(), form.errors)
                obj = form.save(commit=False)
                administrador.save_model(self.request, obj, form, not nueva)
                administrador.save_related(self.request, form, [], not nueva)
                administrador.save_related(self.request, form, [], True)
                copias = CuentaGastos.objects.filter(**{
                    'operacion_flete_origen' if modelo is Operacion else 'vobo_angie_origen': obj,
                })
                self.assertEqual(copias.count(), 1)
                self.assertEqual(list(copias.get().asignados.all()), [self.request.user])
                obj.refresh_from_db()
                self.assertEqual(obj.columna_id, columna.pk)
