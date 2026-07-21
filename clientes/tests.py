from datetime import date
from unittest.mock import Mock, patch

from django.contrib.auth.models import User
from django.db import IntegrityError
from django.http import HttpResponse
from django.test import TestCase
from django.urls import reverse

from clientes.forms import ClienteForm, MENSAJE_CLIENTE_DUPLICADO
from clientes.models import Cliente
from solicitudes.models import Cotizacion


class ClienteFormTests(TestCase):
    def test_permite_crear_cliente_normal(self):
        form = ClienteForm(data={"nombre": "Empresa Vargas", "empresa": "Logistica", "estado": Cliente.ESTADO_ACTIVO})

        self.assertTrue(form.is_valid(), form.errors)
        cliente = form.save()

        self.assertEqual(cliente.nombre, "EMPRESA VARGAS")
        self.assertEqual(cliente.empresa, "LOGISTICA")

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
                    {"nombre": "Empresa Vargas", "empresa": "Logistica", "estado": Cliente.ESTADO_ACTIVO},
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
                "estado": Cliente.ESTADO_ACTIVO,
                "next": "//evil.test/phishing",
            },
        )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("cliente_lista"))


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
