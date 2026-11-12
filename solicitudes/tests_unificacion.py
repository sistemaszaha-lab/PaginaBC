from datetime import date
from copy import copy
from importlib import import_module
from html import unescape
from types import SimpleNamespace

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from clientes.models import Cliente
from solicitudes.forms import SolicitudForm
from solicitudes.models import Cotizacion, Solicitud
from solicitudes_app.trash import restaurar_desde_papelera


class UnificacionSolicitudesTests(TestCase):
    def setUp(self):
        self.usuario = User.objects.create_user(username="unificacion", password="pass")
        self.client.force_login(self.usuario)
        self.cliente = Cliente.objects.create(nombre="Alfa")
        self.otro = Cliente.objects.create(nombre="Alfa", empresa="Otra")

    def solicitud(self, numero, cliente=None, fecha=date(2026, 1, 1)):
        catalogo = self.cliente if cliente is None else cliente
        return Solicitud.objects.create(
            anio=2026, sg=f"SG-U-{numero}", cliente=catalogo.nombre,
            cliente_catalogo=catalogo, fecha_recepcion=fecha, tipo="Importación aérea",
        )

    def cotizacion(self, numero):
        return Cotizacion.objects.create(
            anio=2026, consecutivo=f"COT-U-{numero}", cliente="PROSPECTO",
            fecha_solicitud=date(2026, 1, 1), tipo="Servicio",
        )

    def test_tablas_menu_y_enlace_historico(self):
        solicitud = self.solicitud(1)
        cotizacion = self.cotizacion(1)
        response = self.client.get(reverse("lista_solicitudes"))
        html = response.content.decode()
        self.assertLess(html.index('id="solicitudes-body"'), html.index('id="cotizaciones-body"'))
        self.assertContains(response, solicitud.sg)
        self.assertContains(response, cotizacion.consecutivo)
        self.assertEqual(html.count('class="sidebar-link is-active">Solicitudes</a>'), 1)
        self.assertNotIn('>Cotizaciones-Ref</a>', html)
        historico = self.client.get(reverse("lista_cotizaciones"), {"q": "PROSPECTO"})
        self.assertEqual(historico.status_code, 302)
        self.assertIn('cot_q=PROSPECTO', historico.url)
        self.assertTrue(historico.url.endswith('#cotizaciones-ref'))

    def test_cliente_registrado_es_recurrente_desde_la_primera_solicitud(self):
        primera = self.solicitud(1)
        segunda = self.solicitud(2)
        otro = self.solicitud(3, self.otro)
        response = self.client.get(reverse("lista_solicitudes"))
        por_id = {item.pk: item for item in response.context["solicitudes"]}
        self.assertTrue(por_id[primera.pk].es_cliente_recurrente)
        self.assertTrue(por_id[segunda.pk].es_cliente_recurrente)
        self.assertTrue(por_id[otro.pk].es_cliente_recurrente)
        tercera = self.solicitud(4)
        response = self.client.get(reverse("lista_solicitudes"))
        por_id = {item.pk: item for item in response.context["solicitudes"]}
        self.assertTrue(por_id[primera.pk].es_cliente_recurrente)
        self.assertTrue(por_id[tercera.pk].es_cliente_recurrente)
        self.assertContains(response, "Recurrente", count=4)

    def test_sin_cliente_es_nuevo_y_nombre_duplicado_es_recurrente_sin_id(self):
        sin_cliente = Solicitud.objects.create(
            anio=2026, sg="SG-U-99", cliente="Sin cliente",
            fecha_recepcion=date(2026, 1, 1), tipo="Servicio",
        )
        ambiguo = Solicitud.objects.create(
            anio=2026, sg="SG-U-98", cliente="ALFA",
            fecha_recepcion=date(2026, 1, 1), tipo="Servicio",
        )
        response = self.client.get(reverse("lista_solicitudes"))
        self.assertIsNone(Solicitud.objects.get(pk=sin_cliente.pk).cliente_catalogo_id)
        self.assertIsNone(Solicitud.objects.get(pk=ambiguo.pk).cliente_catalogo_id)
        por_id = {item.pk: item for item in response.context["solicitudes"]}
        self.assertFalse(por_id[sin_cliente.pk].es_cliente_recurrente)
        self.assertTrue(por_id[ambiguo.pk].es_cliente_recurrente)
        self.assertContains(response, "⭐ Nuevo cliente", count=1)
        self.assertContains(response, "Recurrente", count=1)
        self.assertNotContains(response, "Sin identificar")

    def test_clasificacion_historica_es_dinamica_y_comparacion_exacta(self):
        nombres = ["  alfa  ", "ALFA TRANSPORTE", "PROSPECTO", "PROSPECTO", "SIN CLIENTE"]
        solicitudes = Solicitud.objects.bulk_create([
            Solicitud(anio=2026, sg=f"SG-H-{numero}", cliente=nombre,
                      fecha_recepcion=date(2026, 1, 1), tipo="Servicio")
            for numero, nombre in enumerate(nombres)
        ])
        respuesta = self.client.get(reverse("lista_solicitudes"), {"partial": "1"})
        por_id = {item.pk: item for item in respuesta.context["solicitudes"]}
        self.assertTrue(por_id[solicitudes[0].pk].es_cliente_recurrente)
        for solicitud in solicitudes[1:]:
            self.assertFalse(por_id[solicitud.pk].es_cliente_recurrente)
        self.assertTrue(all(item.cliente_catalogo_id is None for item in por_id.values()))

        Cliente.objects.create(nombre="Prospecto")
        respuesta = self.client.get(reverse("lista_solicitudes"), {"partial": "1"})
        por_id = {item.pk: item for item in respuesta.context["solicitudes"]}
        self.assertTrue(por_id[solicitudes[2].pk].es_cliente_recurrente)
        self.assertTrue(por_id[solicitudes[3].pk].es_cliente_recurrente)
        self.assertFalse(por_id[solicitudes[1].pk].es_cliente_recurrente)
        self.assertTrue(all(item.cliente_catalogo_id is None for item in por_id.values()))

    def test_catalogo_historico_con_minusculas_y_espacios_exteriores(self):
        Cliente.objects.filter(pk=self.cliente.pk).update(nombre="  aLfA  ")
        solicitud = Solicitud.objects.bulk_create([
            Solicitud(anio=2026, sg="SG-H-CASO", cliente=" alfa ",
                      fecha_recepcion=date(2026, 1, 1), tipo="Servicio")
        ])[0]
        respuesta = self.client.get(reverse("lista_solicitudes"))
        por_id = {item.pk: item for item in respuesta.context["solicitudes"]}
        self.assertTrue(por_id[solicitud.pk].es_cliente_recurrente)

    def test_filtros_y_paginas_independientes(self):
        for numero in range(1, 28):
            self.solicitud(numero)
            self.cotizacion(numero)
        paginada = self.client.get(reverse("lista_solicitudes"), {
            "page": 2, "cot_page": 1,
        })
        self.assertEqual(paginada.context["page_obj"].number, 2)
        self.assertEqual(paginada.context["cot"]["page_obj"].number, 1)
        self.assertEqual(len(paginada.context["solicitudes"]), 2)
        self.assertEqual(len(paginada.context["cot"]["cotizaciones"]), 25)
        self.assertIn('cot_page=2#cotizaciones-ref', paginada.content.decode())
        response = self.client.get(reverse("lista_solicitudes"), {
            "q": "SG-U-1", "page": 2, "cot_q": "COT-U-2", "cot_page": 2,
        })
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["q"], "SG-U-1")
        self.assertEqual(response.context["cot"]["q"], "COT-U-2")
        self.assertEqual(response.context["page_obj"].number, 1)
        self.assertEqual(response.context["cot"]["page_obj"].number, 1)
        self.assertIn('name="cot_q"', response.content.decode())
        self.assertIn('name="q"', response.content.decode())
        self.assertNotEqual(response.context["solicitudes"].model, response.context["cot"]["cotizaciones"].model)

        cot_partial = self.client.get(reverse("lista_solicitudes"), {
            "partial": "cot", "cot_q": "COT-U-2", "q": "SG-U-1",
        })
        self.assertContains(cot_partial, "COT-U-2")
        self.assertNotContains(cot_partial, 'id="solicitudes-body"')
        sol_partial = self.client.get(reverse("lista_solicitudes"), {
            "partial": "1", "cot_q": "COT-U-2", "q": "SG-U-1",
        })
        self.assertContains(sol_partial, "SG-U-1")
        self.assertNotContains(sol_partial, 'id="cotizaciones-body"')

    def test_acciones_cotizacion_funcionan_en_pagina_unificada(self):
        cotizacion = self.cotizacion(1)
        response = self.client.get(reverse("lista_solicitudes"))
        self.assertContains(response, reverse("editar_cotizacion", args=[cotizacion.pk]))
        cambio = self.client.post(reverse("cambiar_estado_cotizacion", args=[cotizacion.pk]))
        self.assertEqual(cambio.status_code, 200)
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, "Cumplido")

    def test_formulario_vincula_id_y_descarta_id_si_cambia_el_nombre(self):
        datos = {
            "anio": 2026, "cliente": str(self.otro),
            "cliente_catalogo_id": self.otro.pk,
            "fecha_recepcion": "2026-01-01", "tipo": "Importación aérea",
        }
        form = SolicitudForm(data=datos)
        self.assertTrue(form.is_valid(), form.errors)
        solicitud = form.save()
        self.assertEqual(solicitud.cliente_catalogo_id, self.otro.pk)
        self.assertEqual(solicitud.cliente, self.otro.nombre)

        datos["cliente"] = "UN CLIENTE DISTINTO"
        form_nuevo = SolicitudForm(data=datos)
        self.assertTrue(form_nuevo.is_valid(), form_nuevo.errors)
        nueva = form_nuevo.save()
        self.assertIsNone(nueva.cliente_catalogo_id)
        self.assertEqual(nueva.cliente, "UN CLIENTE DISTINTO")
        self.assertFalse(Cliente.objects.filter(nombre=nueva.cliente).exists())

        datos["cliente"] = "OTRO CLIENTE NUEVO"
        form_edicion = SolicitudForm(data=datos, instance=solicitud)
        self.assertTrue(form_edicion.is_valid(), form_edicion.errors)
        form_edicion.save()
        solicitud.refresh_from_db()
        self.assertIsNone(solicitud.cliente_catalogo_id)
        self.assertEqual(solicitud.cliente, "OTRO CLIENTE NUEVO")

    def test_edicion_copia_y_restauracion_conservan_cliente(self):
        original = self.solicitud(1, self.otro)
        datos = {
            "anio": 2026, "cliente": original.cliente,
            "cliente_catalogo_id": self.otro.pk,
            "fecha_recepcion": "2026-01-01", "tipo": "Importación aérea",
        }
        form = SolicitudForm(data=datos, instance=original)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        original.refresh_from_db()
        self.assertEqual(original.cliente_catalogo_id, self.otro.pk)

        copia = copy(original)
        copia.pk = None
        copia.sg = "SG-U-COPIA"
        copia.save()
        self.assertEqual(copia.cliente_catalogo_id, self.otro.pk)

        original.eliminado_en = timezone.now()
        original.save(update_fields=["eliminado_en"])
        restaurar_desde_papelera(original, self.usuario)
        original.refresh_from_db()
        self.assertIsNone(original.eliminado_en)
        self.assertEqual(original.cliente_catalogo_id, self.otro.pk)

    def test_edicion_cambia_a_otro_cliente_del_catalogo(self):
        solicitud = self.solicitud(1, self.otro)
        form = SolicitudForm(data={
            "anio": 2026, "cliente": self.cliente.nombre,
            "cliente_catalogo_id": self.cliente.pk,
            "fecha_recepcion": "2026-01-01", "tipo": "Importación aérea",
        }, instance=solicitud)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        solicitud.refresh_from_db()
        self.assertEqual(solicitud.cliente_catalogo_id, self.cliente.pk)
        self.assertEqual(solicitud.cliente, self.cliente.nombre)

    def test_migracion_vincula_solo_nombres_unicos_sin_perder_registros(self):
        unico = Cliente.objects.create(nombre="Único")
        Solicitud.objects.bulk_create([
            Solicitud(anio=2026, sg="SG-M-1", cliente="ÚNICO", fecha_recepcion=date(2026, 1, 1), tipo="Servicio"),
            Solicitud(anio=2026, sg="SG-M-2", cliente="ALFA", fecha_recepcion=date(2026, 1, 1), tipo="Servicio"),
            Solicitud(anio=2026, sg="SG-M-3", cliente="SIN CLIENTE", fecha_recepcion=date(2026, 1, 1), tipo="Servicio"),
        ])
        antes = Solicitud.objects.count()
        migracion = import_module("solicitudes.migrations.0017_solicitud_cliente_catalogo")
        with CaptureQueriesContext(connection) as consultas:
            migracion.vincular_clientes_unicos(
                import_module("django.apps").apps,
                SimpleNamespace(connection=connection),
            )
        self.assertEqual(len(consultas), 1)
        self.assertEqual(Solicitud.objects.count(), antes)
        self.assertEqual(Solicitud.objects.get(sg="SG-M-1").cliente_catalogo_id, unico.pk)
        self.assertIsNone(Solicitud.objects.get(sg="SG-M-2").cliente_catalogo_id)
        self.assertIsNone(Solicitud.objects.get(sg="SG-M-3").cliente_catalogo_id)

    def test_actualizacion_parcial_cotizaciones_conserva_destino_completo(self):
        admin = User.objects.create_superuser(username="admin-auditoria", password="pass")
        self.client.force_login(admin)
        self.cotizacion(1)
        respuesta = self.client.get(reverse("lista_solicitudes"), {
            "partial": "cot", "cot_q": "COT-U-1", "q": "solicitud",
        })
        html = unescape(respuesta.content.decode())
        self.assertIn('name="next" value="/solicitudes/?cot_q=COT-U-1&q=solicitud#cotizaciones-ref"', html)
        self.assertNotIn('name="next" value="/solicitudes/?partial=cot', html)

    def test_listado_no_agrega_consultas_por_fila(self):
        self.solicitud(1)
        self.cotizacion(1)
        with CaptureQueriesContext(connection) as consultas_una:
            self.client.get(reverse("lista_solicitudes"))
        for numero in range(2, 27):
            self.solicitud(numero)
            self.cotizacion(numero)
        with CaptureQueriesContext(connection) as consultas_muchas:
            self.client.get(reverse("lista_solicitudes"))
        self.assertEqual(len(consultas_muchas), len(consultas_una))

    def test_acceso_requiere_login_y_solo_lectura_no_puede_cambiar_estado(self):
        cotizacion = self.cotizacion(1)
        self.client.logout()
        for url, parametros in (
            (reverse("lista_solicitudes"), {}),
            (reverse("lista_solicitudes"), {"partial": "cot"}),
            (reverse("lista_cotizaciones"), {}),
        ):
            respuesta = self.client.get(url, parametros)
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn("/login/", respuesta.url)

        lector = User.objects.create_user(username="lector-auditoria", password="pass")
        lector.groups.add(Group.objects.get_or_create(name="SOLO_LECTURA")[0])
        self.client.force_login(lector)
        self.assertEqual(self.client.get(reverse("lista_solicitudes")).status_code, 200)
        cambio = self.client.post(reverse("cambiar_estado_cotizacion", args=[cotizacion.pk]))
        self.assertEqual(cambio.status_code, 403)
        cotizacion.refresh_from_db()
        self.assertEqual(cotizacion.estado, "Pendiente")

    def test_url_historica_preserva_filtros_y_exportaciones(self):
        self.solicitud(1)
        self.cotizacion(1)
        redireccion = self.client.get(reverse("lista_cotizaciones"), {
            "anio": 2026, "q": "PROSPECTO", "orden": "asc", "page": 2,
        })
        self.assertEqual(redireccion.status_code, 302)
        self.assertEqual(
            redireccion.url,
            "/solicitudes/?cot_anio=2026&cot_q=PROSPECTO&cot_orden=asc&cot_page=2#cotizaciones-ref",
        )
        for nombre in ("exportar_solicitudes_excel", "exportar_cotizaciones_excel"):
            respuesta = self.client.get(reverse(nombre), {"anio": 2026})
            self.assertEqual(respuesta.status_code, 200)
            self.assertIn("spreadsheetml", respuesta["Content-Type"])

    def test_creacion_desde_vista_guarda_cliente_seleccionado(self):
        respuesta = self.client.post(reverse("crear_solicitud"), {
            "anio": 2026,
            "cliente": str(self.otro),
            "cliente_catalogo_id": self.otro.pk,
            "fecha_recepcion": "2026-01-01",
            "tipo": "Importación aérea",
        })
        self.assertEqual(respuesta.status_code, 302)
        solicitud = Solicitud.objects.get()
        self.assertEqual(solicitud.cliente_catalogo_id, self.otro.pk)

    def test_catalogo_clasifica_sin_importar_anio_ni_papelera(self):
        anterior = self.solicitud(1)
        anterior.anio = 2025
        anterior.eliminado_en = timezone.now()
        anterior.save(update_fields=["anio", "eliminado_en"])
        actual = self.solicitud(2)
        respuesta = self.client.get(reverse("lista_solicitudes"), {"anio": 2026})
        self.assertEqual([sol.pk for sol in respuesta.context["solicitudes"]], [actual.pk])
        self.assertTrue(respuesta.context["solicitudes"][0].es_cliente_recurrente)
