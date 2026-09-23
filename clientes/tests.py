from datetime import date
from decimal import Decimal
from unittest.mock import Mock, patch

from django.contrib.messages import get_messages
from django.contrib.auth.models import User
from django.db import IntegrityError, connection
from django.db.models.deletion import PROTECT, ProtectedError
from django.http import HttpResponse
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import resolve, reverse

from clientes.forms import ClienteForm, MENSAJE_CLIENTE_DUPLICADO
from clientes.models import Cliente
from operaciones.models import Operacion
from solicitudes.models import Cotizacion, MovimientoReferencia, Referencia


class ClienteFormTests(TestCase):
    def test_utilidad_calcula_ingresos_menos_gastos(self):
        cliente = Cliente.objects.create(
            nombre="CLIENTE UTILIDAD",
            ingresos=1000,
            gastos=400,
        )

        self.assertEqual(cliente.utilidad, Decimal("0.00"))

    def test_utilidad_permite_resultado_negativo(self):
        cliente = Cliente.objects.create(
            nombre="CLIENTE UTILIDAD NEGATIVA",
            ingresos=400,
            gastos=1000,
        )

        usuario = User.objects.create_user(username="movimientos", password="pass")
        referencia = Referencia.objects.create(referencia="REF-NEGATIVA", consecutivo=1, cliente=cliente.nombre)
        MovimientoReferencia.objects.create(referencia=referencia, tipo=MovimientoReferencia.INGRESO, monto=Decimal("400"), registrado_por=usuario)
        MovimientoReferencia.objects.create(referencia=referencia, tipo=MovimientoReferencia.GASTO, monto=Decimal("1000"), registrado_por=usuario)
        self.assertEqual(cliente.utilidad, Decimal("-600.00"))

    def test_utilidad_default_es_cero_para_cliente_historico(self):
        cliente = Cliente.objects.create(nombre="CLIENTE HISTORICO")

        self.assertEqual(cliente.ingresos, 0)
        self.assertEqual(cliente.gastos, 0)
        self.assertEqual(cliente.utilidad, 0)

    def test_permite_crear_cliente_normal(self):
        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas",
                "empresa": "Logistica",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "cuentas_por_cobrar": "Credito 30 dias",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()

        self.assertEqual(cliente.nombre, "EMPRESA VARGAS")
        self.assertEqual(cliente.empresa, "LOGISTICA")
        self.assertEqual(cliente.contacto, "Ana")
        self.assertEqual(cliente.correo, "ana@example.com")
        self.assertEqual(cliente.cuentas_por_cobrar, "Credito 30 dias")

    def test_crear_cliente_nuevo_sin_nombre_es_invalido(self):
        form = ClienteForm(
            data={
                "nombre": "",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("nombre", form.errors)

    def test_crear_cliente_nuevo_sin_correo_es_invalido(self):
        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas",
                "contacto": "Ana",
                "correo": "",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("correo", form.errors)

    def test_crear_cliente_nuevo_sin_contacto_es_invalido(self):
        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas",
                "contacto": "",
                "correo": "ana@example.com",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertFalse(form.is_valid())
        self.assertIn("contacto", form.errors)

    def test_cuentas_por_cobrar_sigue_siendo_opcional_al_crear(self):
        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "cuentas_por_cobrar": "",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        self.assertEqual(cliente.cuentas_por_cobrar, "")

    def test_permite_crear_cliente_con_ingresos_y_gastos_validos(self):
        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "ingresos": "1000.50",
                "gastos": "400.25",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            requerir_datos_alta=True,
        )

        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        self.assertEqual(cliente.ingresos, Decimal("0.00"))
        self.assertEqual(cliente.gastos, Decimal("0.00"))
        self.assertEqual(cliente.utilidad, Decimal("0.00"))

    def test_utilidad_no_es_editable_directamente(self):
        form = ClienteForm()

        self.assertNotIn("utilidad", form.fields)

    def test_numero_no_es_campo_editable(self):
        form = ClienteForm()

        self.assertNotIn("numero", form.fields)
        self.assertNotIn("numero_cliente", form.fields)

    def test_rechaza_duplicado_exacto(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(data={"nombre": "EMPRESA VARGAS", "empresa": "LOGISTICA", "estado": Cliente.ESTADO_ACTIVO})

        self.assertFalse(form.is_valid())
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, form.non_field_errors())

    def test_rechaza_duplicado_por_minusculas(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(data={"nombre": "empresa vargas", "empresa": "logistica", "estado": Cliente.ESTADO_ACTIVO})

        self.assertFalse(form.is_valid())
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, form.non_field_errors())

    def test_rechaza_duplicado_por_espacios(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(data={"nombre": "  Empresa   Vargas  ", "empresa": "  Logistica  ", "estado": Cliente.ESTADO_ACTIVO})

        self.assertFalse(form.is_valid())
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, form.non_field_errors())

    def test_permite_mismo_nombre_con_empresa_distinta(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(data={"nombre": "Empresa Vargas", "empresa": "Aduanas", "estado": Cliente.ESTADO_ACTIVO})

        self.assertTrue(form.is_valid(), form.errors)

    def test_permite_distinto_nombre_con_misma_empresa(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(data={"nombre": "Transportes Vargas", "empresa": "Logistica", "estado": Cliente.ESTADO_ACTIVO})

        self.assertTrue(form.is_valid(), form.errors)

    def test_editar_sin_cambiar_identidad_no_falla(self):
        cliente = Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(
            data={"nombre": " empresa   vargas ", "empresa": " logistica ", "estado": Cliente.ESTADO_ACTIVO},
            instance=cliente,
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_editar_cliente_historico_sin_correo_ni_contacto_no_falla(self):
        cliente = Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        form = ClienteForm(
            data={
                "nombre": "Empresa Vargas Editada",
                "empresa": "Logistica",
                "contacto": "",
                "correo": "",
                "estado": Cliente.ESTADO_ACTIVO,
            },
            instance=cliente,
        )

        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()
        self.assertEqual(cliente.nombre, "EMPRESA VARGAS EDITADA")

    def test_editar_para_convertir_en_duplicado_es_rechazado(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")
        cliente = Cliente.objects.create(nombre="TRANSPORTES VARGAS", empresa="ADUANAS")

        form = ClienteForm(
            data={"nombre": "empresa vargas", "empresa": "logistica", "estado": Cliente.ESTADO_ACTIVO},
            instance=cliente,
        )

        self.assertFalse(form.is_valid())
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, form.non_field_errors())


class ClienteConstraintTests(TestCase):
    def test_restriccion_funciona_desde_orm(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        with self.assertRaises(IntegrityError):
            Cliente.objects.create(nombre=" empresa vargas ", empresa=" logistica ")

    def test_empresa_vacia_tambien_queda_protegida(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="")

        with self.assertRaises(IntegrityError):
            Cliente.objects.create(nombre="empresa vargas", empresa=" ")

    def test_no_modifica_clientes_existentes(self):
        cliente = Cliente.objects.create(
            nombre="EMPRESA VARGAS",
            empresa="LOGISTICA",
            representante_legal="ALDO",
            contacto="ANA",
        )

        self.assertEqual(cliente.representante_legal, "ALDO")
        self.assertEqual(cliente.contacto, "ANA")
        self.assertEqual(cliente.cuentas_por_cobrar, "")


class ClienteViewsTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="admin_clientes", password="admin123")
        self.client.login(username="admin_clientes", password="admin123")

    def test_vista_crear_muestra_error_si_ocurre_integrity_error_controlado(self):
        contexto = {}

        def fake_render(request, template_name, context):
            contexto.update(context)
            return HttpResponse("ok")

        with patch("clientes.views.ClienteForm.save", side_effect=IntegrityError('duplicate key value violates unique constraint "cliente_nombre_empresa_unicos"')):
            with patch("clientes.views.render", side_effect=fake_render):
                response = self.client.post(
                    reverse("cliente_crear"),
                    {
                        "nombre": "Empresa Vargas",
                        "empresa": "Logistica",
                        "contacto": "Ana",
                        "correo": "ana@example.com",
                        "estado": Cliente.ESTADO_ACTIVO,
                    },
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, contexto["form"].non_field_errors())
        self.assertFalse(Cliente.objects.exists())

    def test_vista_editar_muestra_error_si_ocurre_integrity_error_controlado(self):
        cliente = Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="LOGISTICA")

        contexto = {}

        def fake_render(request, template_name, context):
            contexto.update(context)
            return HttpResponse("ok")

        with patch("clientes.views.ClienteForm.save", side_effect=IntegrityError('duplicate key value violates unique constraint "cliente_nombre_empresa_unicos"')):
            with patch("clientes.views.render", side_effect=fake_render):
                response = self.client.post(
                    reverse("cliente_editar", args=[cliente.pk]),
                    {"nombre": "Empresa Vargas", "empresa": "Logistica", "estado": Cliente.ESTADO_ACTIVO},
                )

        self.assertEqual(response.status_code, 200)
        self.assertIn(MENSAJE_CLIENTE_DUPLICADO, contexto["form"].non_field_errors())

    def test_crear_cliente_redirige_a_next_interno_y_agrega_cliente(self):
        response = self.client.post(
            reverse("cliente_crear"),
            {
                "nombre": "Empresa Vargas",
                "empresa": "Logistica",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "estado": Cliente.ESTADO_ACTIVO,
                "next": "/solicitudes/editar/1/?next=/solicitudes/?page=2",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            response.url,
            "/solicitudes/editar/1/?next=%2Fsolicitudes%2F%3Fpage%3D2&cliente=EMPRESA+VARGAS+%28LOGISTICA%29",
        )

    def test_crear_cliente_rechaza_next_externo(self):
        response = self.client.post(
            reverse("cliente_crear"),
            {
                "nombre": "Empresa Vargas",
                "empresa": "Logistica",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "estado": Cliente.ESTADO_ACTIVO,
                "next": "//evil.test/phishing",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cliente_lista"))

    def test_cliente_sin_relaciones_se_elimina_con_post(self):
        cliente = Cliente.objects.create(nombre="Cliente eliminable")

        response = self.client.post(reverse("cliente_eliminar", args=[cliente.pk]), follow=True)

        self.assertRedirects(response, reverse("cliente_lista"))
        self.assertFalse(Cliente.objects.filter(pk=cliente.pk).exists())
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn("Cliente eliminado correctamente.", messages)

    def test_cliente_con_operacion_protegida_no_se_elimina_en_formulario_normal(self):
        cliente = Cliente.objects.create(nombre="Cliente protegido")
        operacion = Operacion.objects.create(
            titulo="Operacion protegida",
            cliente=cliente,
            creado_por=self.user,
        )

        response = self.client.post(reverse("cliente_eliminar", args=[cliente.pk]), follow=True)

        self.assertRedirects(response, reverse("cliente_lista"))
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())
        self.assertTrue(Operacion.objects.filter(pk=operacion.pk, cliente=cliente).exists())
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertIn(
            "No se puede eliminar el cliente porque tiene registros relacionados: 1 operacion.",
            messages,
        )

    def test_cliente_con_operacion_protegida_devuelve_409_en_fetch(self):
        cliente = Cliente.objects.create(nombre="Cliente protegido fetch")
        operacion = Operacion.objects.create(
            titulo="Operacion protegida fetch",
            cliente=cliente,
            creado_por=self.user,
        )

        response = self.client.post(
            reverse("cliente_eliminar", args=[cliente.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 409)
        data = response.json()
        self.assertFalse(data["ok"])
        self.assertEqual(data["error_code"], "CLIENT_PROTECTED")
        self.assertEqual(data["relations"], {"operaciones": 1})
        self.assertIn("1 operacion", data["message"])
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())
        self.assertTrue(Operacion.objects.filter(pk=operacion.pk, cliente=cliente).exists())

    def test_accept_json_basta_para_obtener_conflicto_json(self):
        cliente = Cliente.objects.create(nombre="Cliente protegido accept")
        Operacion.objects.create(
            titulo="Operacion protegida accept",
            cliente=cliente,
            creado_por=self.user,
        )

        response = self.client.post(
            reverse("cliente_eliminar", args=[cliente.pk]),
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.json()["error_code"], "CLIENT_PROTECTED")

    def test_vista_real_captura_protected_error(self):
        cliente = Cliente.objects.create(nombre="Cliente protected simulado")

        with patch.object(
            Cliente,
            "delete",
            side_effect=ProtectedError("protegido", set()),
        ):
            response = self.client.post(
                reverse("cliente_eliminar", args=[cliente.pk]),
                follow=True,
            )

        self.assertRedirects(response, reverse("cliente_lista"))
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())
        messages = [str(message) for message in get_messages(response.wsgi_request)]
        self.assertTrue(any("registros relacionados" in message for message in messages))

    def test_url_eliminar_resuelve_a_vista_real_y_fk_sigue_protect(self):
        url = reverse("cliente_eliminar", args=[7])
        match = resolve(url)

        self.assertEqual(url, "/clientes/7/eliminar/")
        self.assertEqual(match.func.__module__, "clientes.views")
        self.assertEqual(match.view_name, "cliente_eliminar")
        self.assertIs(Operacion._meta.get_field("cliente").remote_field.on_delete, PROTECT)

    def test_cliente_eliminar_fetch_exitoso_devuelve_json(self):
        cliente = Cliente.objects.create(nombre="Cliente eliminable fetch")

        response = self.client.post(
            reverse("cliente_eliminar", args=[cliente.pk]),
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
            HTTP_ACCEPT="application/json",
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {"ok": True, "message": "Cliente eliminado correctamente."},
        )
        self.assertFalse(Cliente.objects.filter(pk=cliente.pk).exists())

    def test_cliente_eliminar_solo_acepta_post(self):
        cliente = Cliente.objects.create(nombre="Cliente get no permitido")

        response = self.client.get(reverse("cliente_eliminar", args=[cliente.pk]))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())

    def test_usuario_anonimo_no_puede_eliminar_cliente(self):
        cliente = Cliente.objects.create(nombre="Cliente anonimo")
        self.client.logout()

        response = self.client.post(reverse("cliente_eliminar", args=[cliente.pk]))

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)
        self.assertTrue(Cliente.objects.filter(pk=cliente.pk).exists())


class ClientePaginationTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="paginacion_clientes",
            password="admin123",
        )
        self.client.force_login(self.user)

    def _crear_clientes(self, cantidad, prefijo="PAGINACION"):
        objetos = []
        for indice in range(cantidad):
            objetos.append(
                Cliente(
                    nombre=f"{prefijo} CLIENTE {indice:04d}",
                    empresa=f"{prefijo} EMPRESA {indice:04d}",
                    tipo_cliente=(
                        Cliente.TIPO_EXISTENTE
                        if indice % 2 == 0
                        else Cliente.TIPO_NUEVO
                    ),
                    fecha_alta=date(2026, 7, 1),
                )
            )
        Cliente.objects.bulk_create(objetos)

    def _clientes_renderizados(self, response):
        return list(response.context["clientes"])

    def test_volumenes_limite_renderizan_como_maximo_25(self):
        for cantidad in (0, 1, 25, 26, 50, 51, 100, 250):
            with self.subTest(cantidad=cantidad):
                Cliente.objects.all().delete()
                self._crear_clientes(cantidad)

                response = self.client.get(reverse("cliente_lista"))

                self.assertEqual(response.status_code, 200)
                self.assertLessEqual(
                    len(self._clientes_renderizados(response)),
                    25,
                )
                self.assertEqual(
                    len(self._clientes_renderizados(response)),
                    min(cantidad, 25),
                )
                self.assertEqual(
                    response.context["page_obj"].paginator.count,
                    cantidad,
                )

    def test_listado_principal_renderiza_una_sola_tabla(self):
        self._crear_clientes(26)

        primera = self.client.get(reverse("cliente_lista"))
        segunda = self.client.get(reverse("cliente_lista"), {"page": 2})

        self.assertNotContains(primera, "Clientes existentes")
        self.assertNotContains(primera, "Nuevos clientes")
        self.assertEqual(len(self._clientes_renderizados(primera)), 25)
        self.assertEqual(len(self._clientes_renderizados(segunda)), 1)

    def test_orden_es_alfabetico_por_nombre_y_pk(self):
        Cliente.objects.bulk_create(
            [
                Cliente(nombre="MARIO", empresa="UNO", fecha_alta=date(2026, 7, 1)),
                Cliente(nombre="ANA", empresa="DOS", fecha_alta=date(2026, 7, 1)),
                Cliente(nombre="CARLOS", empresa="TRES", fecha_alta=date(2026, 7, 1)),
                Cliente(nombre="ANA", empresa="CUATRO", fecha_alta=date(2026, 7, 1)),
            ]
        )

        primera = self.client.get(reverse("cliente_lista"))
        resultados = self._clientes_renderizados(primera)

        esperados = list(
            Cliente.objects.order_by("nombre", "pk")
        )
        self.assertEqual(
            [cliente.pk for cliente in resultados],
            [cliente.pk for cliente in esperados],
        )
        self.assertEqual(
            len({cliente.pk for cliente in resultados}),
            4,
        )

    def test_ranking_cl_solo_incluye_referencias_activas_y_desempata_por_nombre(self):
        for nombre, cantidad in (("ALFA", 5), ("BETA", 0), ("CHARLIE", 2), ("DELTA", 1)):
            Cliente.objects.create(nombre=nombre)
            for indice in range(cantidad):
                Referencia.objects.create(referencia=f"{nombre}-{indice}", consecutivo=indice + 1, cliente=nombre)
        response = self.client.get(reverse("cliente_lista"))
        por_nombre = {c.nombre: c.numero_cliente for c in self._clientes_renderizados(response)}
        self.assertEqual(por_nombre, {"ALFA": "CL-001", "BETA": "", "CHARLIE": "CL-002", "DELTA": "CL-003"})

    def test_empate_alfabetico_y_referencia_eliminada_no_dan_cl(self):
        alfa = Cliente.objects.create(nombre="ALFA")
        beta = Cliente.objects.create(nombre="BETA")
        sin_referencia_activa = Cliente.objects.create(nombre="GAMMA")
        for cliente in (alfa, beta):
            for indice in range(2):
                Referencia.objects.create(referencia=f"{cliente.nombre}-{indice}", consecutivo=indice + 1, cliente=cliente.nombre)
        Referencia.objects.create(referencia="GAMMA-1", consecutivo=1, cliente=sin_referencia_activa.nombre, eliminado_en=date(2026, 8, 1))
        response = self.client.get(reverse("cliente_lista"))
        por_nombre = {c.nombre: c.numero_cliente for c in self._clientes_renderizados(response)}
        self.assertEqual(por_nombre["ALFA"], "CL-001")
        self.assertEqual(por_nombre["BETA"], "CL-002")
        self.assertEqual(por_nombre["GAMMA"], "")

    def test_cliente_recibe_cl_al_crear_su_primera_referencia_activa(self):
        cliente = Cliente.objects.create(nombre="NUEVO")
        inicial = self.client.get(reverse("cliente_lista"))
        self.assertEqual(self._clientes_renderizados(inicial)[0].numero_cliente, "")
        Referencia.objects.create(referencia="NUEVO-1", consecutivo=1, cliente=cliente.nombre)
        actualizado = self.client.get(reverse("cliente_lista"))
        self.assertEqual(self._clientes_renderizados(actualizado)[0].numero_cliente, "CL-001")

    def test_ranking_cuenta_nombre_y_representacion_compuesta_sin_parciales(self):
        cliente = Cliente.objects.create(nombre="CLIENTE UNO", empresa="EMPRESA UNO")
        for indice in range(2):
            Referencia.objects.create(referencia=f"UNO-{indice}", consecutivo=indice, cliente=cliente.nombre)
        for indice in range(3):
            Referencia.objects.create(referencia=f"UNO-C-{indice}", consecutivo=10 + indice, cliente=str(cliente))
        Referencia.objects.create(referencia="UNO-DEL", consecutivo=99, cliente=str(cliente), eliminado_en=date(2026, 1, 1))
        Referencia.objects.create(referencia="UNO-PARCIAL", consecutivo=100, cliente="AMERICAN")

        response = self.client.get(reverse("cliente_lista"))
        renderizado = next(c for c in self._clientes_renderizados(response) if c.pk == cliente.pk)
        self.assertEqual(renderizado.referencias_count, 5)
        self.assertEqual(renderizado.numero_cliente, "CL-001")

    def test_empresa_vacia_no_reconoce_nombre_parentesis(self):
        cliente = Cliente.objects.create(nombre="ALDO", empresa="")
        Referencia.objects.create(referencia="ALDO-PARCIAL", consecutivo=1, cliente="ALDO ()")
        response = self.client.get(reverse("cliente_lista"))
        renderizado = next(c for c in self._clientes_renderizados(response) if c.pk == cliente.pk)
        self.assertEqual(renderizado.referencias_count, 0)
        self.assertEqual(renderizado.numero_cliente, "")

    def test_numero_es_primera_columna_y_sigue_orden_alfabetico(self):
        Cliente.objects.bulk_create(
            [
                Cliente(nombre="ALFA"),
                Cliente(nombre="COMERCIALIZADORA"),
                Cliente(nombre="TRANSPORTES"),
            ]
        )

        response = self.client.get(reverse("cliente_lista"))
        html = response.content.decode()

        self.assertContains(response, "<th>Número</th>", html=True)
        self.assertLess(html.index("<th>Número</th>"), html.index("<th>Cliente</th>"))
        self.assertLess(html.index("ALFA"), html.index("COMERCIALIZADORA"))
        self.assertEqual([c.numero_cliente for c in self._clientes_renderizados(response)], ["", "", ""])

    def test_numero_se_recorre_si_entra_cliente_antes_alfabeticamente(self):
        alfa = Cliente.objects.create(nombre="ALFA")
        comercializadora = Cliente.objects.create(nombre="COMERCIALIZADORA")
        Cliente.objects.create(nombre="TRANSPORTES")

        inicial = self.client.get(reverse("cliente_lista"))
        self.assertEqual(self._clientes_renderizados(inicial)[0].pk, alfa.pk)
        self.assertEqual(self._clientes_renderizados(inicial)[1].pk, comercializadora.pk)
        self.assertEqual(self._clientes_renderizados(inicial)[0].numero_cliente, "")

        aduanas = Cliente.objects.create(nombre="ADUANAS")
        actualizado = self.client.get(reverse("cliente_lista"))
        resultados = self._clientes_renderizados(actualizado)

        self.assertEqual(resultados[0].pk, aduanas.pk)
        self.assertEqual(resultados[1].pk, alfa.pk)
        self.assertEqual(resultados[2].pk, comercializadora.pk)
        self.assertEqual([r.numero_cliente for r in resultados[:3]], ["", "", ""])

    def test_numero_se_recalcula_al_renombrar_cliente(self):
        alfa = Cliente.objects.create(nombre="ALFA")
        beta = Cliente.objects.create(nombre="BETA")

        beta.nombre = "AARON"
        beta.save()
        response = self.client.get(reverse("cliente_lista"))
        resultados = self._clientes_renderizados(response)

        self.assertEqual(resultados[0].pk, beta.pk)
        self.assertEqual(resultados[1].pk, alfa.pk)
        self.assertEqual(resultados[0].numero_cliente, "")
        self.assertEqual(resultados[1].numero_cliente, "")

    def test_busqueda_se_aplica_antes_de_paginar_y_conserva_q(self):
        self._crear_clientes(30, prefijo="COINCIDE")
        self._crear_clientes(20, prefijo="OTRO")

        response = self.client.get(
            reverse("cliente_lista"),
            {"q": "  coincide  ", "page": 2},
        )

        self.assertEqual(response.context["query"], "coincide")
        self.assertEqual(response.context["page_obj"].paginator.count, 30)
        self.assertEqual(len(self._clientes_renderizados(response)), 5)
        self.assertContains(response, "?q=coincide&amp;page=1")
        self.assertContains(response, 'name="q"')
        self.assertNotContains(response, "OTRO CLIENTE")

    def test_busqueda_con_caracteres_especiales_se_codifica_y_escapa(self):
        Cliente.objects.create(
            nombre="CLIENTE & ESPECIAL",
            empresa="RAZON SOCIAL",
        )

        response = self.client.get(
            reverse("cliente_lista"),
            {"q": "& especial"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "CLIENTE &amp; ESPECIAL")
        self.assertContains(response, "q=%26+especial")

    def test_paginas_invalidas_siguen_reglas_seguras_de_get_page(self):
        self._crear_clientes(51)
        casos = {
            "texto": 1,
            "0": 3,
            "-4": 3,
            "999": 3,
        }

        for valor, pagina_esperada in casos.items():
            with self.subTest(page=valor):
                response = self.client.get(
                    reverse("cliente_lista"),
                    {"page": valor},
                )
                self.assertEqual(
                    response.context["page_obj"].number,
                    pagina_esperada,
                )

    def test_navegacion_es_compacta_y_accesible(self):
        self._crear_clientes(250)

        response = self.client.get(reverse("cliente_lista"), {"page": 5})

        self.assertContains(response, 'aria-label="Paginacion de clientes"')
        self.assertContains(response, 'aria-current="page"')
        self.assertContains(response, "Anterior")
        self.assertContains(response, "Siguiente")
        self.assertContains(response, "&hellip;", html=True)
        self.assertNotContains(response, "?page=8")

    def test_numero_continua_entre_paginas_y_no_limita_tres_digitos(self):
        self._crear_clientes(1000)

        primera = self.client.get(reverse("cliente_lista"))
        pagina_dos = self.client.get(reverse("cliente_lista"), {"page": 2})
        pagina_cuatro = self.client.get(reverse("cliente_lista"), {"page": 4})
        pagina_cuarenta = self.client.get(reverse("cliente_lista"), {"page": 40})

        self.assertTrue(all(not c.numero_cliente for c in self._clientes_renderizados(primera)))
        self.assertTrue(all(not c.numero_cliente for c in self._clientes_renderizados(pagina_dos)))
        self.assertTrue(all(not c.numero_cliente for c in self._clientes_renderizados(pagina_cuatro)))
        self.assertTrue(all(not c.numero_cliente for c in self._clientes_renderizados(pagina_cuarenta)))

    def test_consultas_del_get_son_constantes_entre_25_y_250(self):
        self._crear_clientes(25)
        with CaptureQueriesContext(connection) as consultas_25:
            response_25 = self.client.get(reverse("cliente_lista"))
        self._crear_clientes(225, prefijo="ESCALA")
        with CaptureQueriesContext(connection) as consultas_250:
            response_250 = self.client.get(reverse("cliente_lista"))

        self.assertEqual(response_25.status_code, 200)
        self.assertEqual(response_250.status_code, 200)
        self.assertEqual(len(consultas_25), len(consultas_250))
        self.assertEqual(len(consultas_250), len(consultas_25))

    def test_get_no_modifica_clientes(self):
        self._crear_clientes(51)
        antes = list(
            Cliente.objects.order_by("pk").values_list(
                "pk", "estado", "tipo_cliente"
            )
        )

        response = self.client.get(
            reverse("cliente_lista"),
            {"q": "PAGINACION", "page": 2},
        )

        despues = list(
            Cliente.objects.order_by("pk").values_list(
                "pk", "estado", "tipo_cliente"
            )
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(despues, antes)

    def test_acciones_renderizadas_incluyen_csrf_y_retorno(self):
        self._crear_clientes(26)
        retorno = "/clientes/?q=PAGINACION&page=2"

        response = self.client.get(
            reverse("cliente_lista"),
            {"q": "PAGINACION", "page": 2},
        )

        self.assertGreaterEqual(
            response.content.count(b'name="csrfmiddlewaretoken"'),
            3,
        )
        self.assertContains(response, 'name="next"', count=3)
        self.assertContains(
            response,
            'value="/clientes/?q=PAGINACION&amp;page=2"',
            count=3,
        )
        self.assertContains(
            response,
            "next=/clientes/%3Fq%3DPAGINACION%26page%3D2",
        )

    def test_crear_y_editar_regresan_a_busqueda_y_pagina(self):
        retorno = "/clientes/?q=PAGINACION&page=2"
        crear = self.client.post(
            reverse("cliente_crear"),
            {
                "nombre": "Cliente creado",
                "empresa": "Empresa",
                "contacto": "Ana",
                "correo": "ana@example.com",
                "cuentas_por_cobrar": "Saldo inicial",
                "estado": Cliente.ESTADO_ACTIVO,
                "next": retorno,
            },
        )
        cliente = Cliente.objects.get(nombre="CLIENTE CREADO")
        self.assertEqual(cliente.cuentas_por_cobrar, "Saldo inicial")
        editar = self.client.post(
            reverse("cliente_editar", args=[cliente.pk]),
            {
                "nombre": "Cliente editado",
                "empresa": "Empresa",
                "cuentas_por_cobrar": "Saldo actualizado",
                "estado": Cliente.ESTADO_ACTIVO,
                "next": retorno,
            },
        )

        self.assertRedirects(crear, retorno, fetch_redirect_response=False)
        self.assertRedirects(editar, retorno, fetch_redirect_response=False)
        cliente.refresh_from_db()
        self.assertEqual(cliente.nombre, "CLIENTE EDITADO")
        self.assertEqual(cliente.cuentas_por_cobrar, "Saldo actualizado")

    def test_listado_muestra_utilidades_entre_celular_y_status(self):
        cliente = Cliente.objects.create(
            nombre="CLIENTE UTILIDADES",
            celular="5551234",
            ingresos=999999,
            gastos=1,
        )
        referencia = Referencia.objects.create(
            referencia="REF-UTILIDADES",
            consecutivo=1,
            cliente=cliente.nombre,
        )
        MovimientoReferencia.objects.create(
            referencia=referencia,
            tipo=MovimientoReferencia.INGRESO,
            monto=Decimal("25000.00"),
            registrado_por=self.user,
        )
        MovimientoReferencia.objects.create(
            referencia=referencia,
            tipo=MovimientoReferencia.GASTO,
            monto=Decimal("5000.00"),
            registrado_por=self.user,
        )

        response = self.client.get(reverse("cliente_lista"))

        self.assertContains(response, "<th>Celular</th>", html=True)
        self.assertContains(response, "<th>Utilidades</th>", html=True)
        self.assertContains(response, "<th>Status</th>", html=True)
        contenido = response.content.decode()
        self.assertLess(contenido.index("<th>Celular</th>"), contenido.index("<th>Utilidades</th>"))
        self.assertLess(contenido.index("<th>Utilidades</th>"), contenido.index("<th>Status</th>"))
        self.assertContains(response, "Utilidad: $20000.00")

    def test_listado_muestra_cuentas_por_cobrar_entre_correo_y_telefono(self):
        Cliente.objects.create(
            nombre="CLIENTE CUENTAS",
            correo="cuentas@example.com",
            cuentas_por_cobrar="Factura 123",
            telefono="5551234",
        )

        response = self.client.get(reverse("cliente_lista"))

        self.assertContains(response, "<th>Correo</th>", html=True)
        self.assertContains(response, "<th>Cuentas por cobrar</th>", html=True)
        self.assertContains(response, "<th>Teléfono</th>", html=True)
        contenido = response.content.decode()
        self.assertLess(contenido.index("<th>Correo</th>"), contenido.index("<th>Cuentas por cobrar</th>"))
        self.assertLess(contenido.index("<th>Cuentas por cobrar</th>"), contenido.index("<th>Tel"))
        self.assertContains(response, "Factura 123")

    def test_busqueda_incluye_cuentas_por_cobrar(self):
        Cliente.objects.create(nombre="CLIENTE BUSQUEDA", cuentas_por_cobrar="Pendiente convenio")
        Cliente.objects.create(nombre="CLIENTE OCULTO", cuentas_por_cobrar="Sin saldo")

        response = self.client.get(reverse("cliente_lista"), {"q": "convenio"})

        self.assertContains(response, "CLIENTE BUSQUEDA")
        self.assertNotContains(response, "CLIENTE OCULTO")

    def test_estado_convertir_y_eliminar_regresan_a_pagina(self):
        retorno = "/clientes/?q=PAGINACION&page=2"
        estado = Cliente.objects.create(nombre="CLIENTE ESTADO")
        convertir = Cliente.objects.create(
            nombre="CLIENTE CONVERTIR",
            tipo_cliente=Cliente.TIPO_NUEVO,
        )
        eliminar = Cliente.objects.create(nombre="CLIENTE ELIMINAR")

        respuestas = [
            self.client.post(
                reverse("cliente_cambiar_estado", args=[estado.pk]),
                {"next": retorno},
            ),
            self.client.post(
                reverse("cliente_convertir_existente", args=[convertir.pk]),
                {"next": retorno},
            ),
            self.client.post(
                reverse("cliente_eliminar", args=[eliminar.pk]),
                {"next": retorno},
            ),
        ]

        for response in respuestas:
            self.assertRedirects(
                response,
                retorno,
                fetch_redirect_response=False,
            )
        estado.refresh_from_db()
        convertir.refresh_from_db()
        self.assertEqual(estado.estado, Cliente.ESTADO_INACTIVO)
        self.assertEqual(convertir.tipo_cliente, Cliente.TIPO_EXISTENTE)
        self.assertFalse(Cliente.objects.filter(pk=eliminar.pk).exists())

    def test_next_externo_se_rechaza_en_acciones(self):
        cliente = Cliente.objects.create(nombre="CLIENTE SEGURO")

        response = self.client.post(
            reverse("cliente_cambiar_estado", args=[cliente.pk]),
            {"next": "//evil.test/clientes/"},
        )

        self.assertRedirects(
            response,
            reverse("cliente_lista"),
            fetch_redirect_response=False,
        )

    def test_anonimo_no_accede_al_listado_paginado(self):
        self.client.logout()

        response = self.client.get(reverse("cliente_lista"), {"page": 2})

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)


class CotizacionClienteConstraintTests(TestCase):
    def setUp(self):
        self.ejecutivo = User.objects.create_user(username="ejec_dup_cliente", password="ejec123")

    def _crear_cotizacion(self, consecutivo, cliente):
        return Cotizacion.objects.create(
            anio=2026,
            consecutivo=consecutivo,
            cliente=cliente,
            fecha_solicitud=date(2026, 2, 10),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            tiempo_entrega="",
            aerea="Aérea",
            maritima="",
            terrestre="",
        )

    def test_creacion_automatica_reutiliza_cliente_existente(self):
        existente = Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="")

        cotizacion = self._crear_cotizacion("C26910", " empresa   vargas ")

        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(cotizacion.cliente, existente.nombre)

    def test_reintento_controlado_por_integrity_error_no_duplica_clientes(self):
        Cliente.objects.create(nombre="EMPRESA VARGAS", empresa="")
        original_filter = Cliente.objects.filter
        primera_busqueda = {"pendiente": True}

        def filter_con_lectura_desfasada(*args, **kwargs):
            queryset = original_filter(*args, **kwargs)
            if primera_busqueda["pendiente"]:
                primera_busqueda["pendiente"] = False
                falso = Mock()
                falso.first.return_value = None
                return falso
            return queryset

        with patch.object(Cliente.objects, "filter", side_effect=filter_con_lectura_desfasada):
            cotizacion = self._crear_cotizacion("C26911", "empresa vargas")

        self.assertEqual(Cliente.objects.count(), 1)
        self.assertEqual(Cliente.objects.get().nombre, "EMPRESA VARGAS")
        self.assertEqual(cotizacion.cliente, "EMPRESA VARGAS")
