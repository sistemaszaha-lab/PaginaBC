from datetime import date

from django.contrib.auth.models import User
from django.test import TestCase
from django.urls import reverse

from .forms import CotizacionForm, SolicitudForm
from .models import Cotizacion, Referencia, Solicitud
from .views import _importar_referencias_desde_filas


class SeguridadPermisosTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(
            username="admin", password="admin123", is_superuser=True, is_staff=True
        )
        self.ejecutivo = User.objects.create_user(username="ejec", password="ejec123")
        self.otro = User.objects.create_user(username="otro", password="otro123")

        self.solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG-001",
            cliente="Cliente Demo",
            fecha_recepcion=date(2026, 1, 10),
            tipo="Operacion",
            aerea=True,
            estado_aereo="Pendiente",
            ejecutivo=self.ejecutivo,
        )
        self.cotizacion = Cotizacion.objects.create(
            anio=2026,
            consecutivo="COT-001",
            cliente="Prospecto Demo",
            fecha_solicitud=date(2026, 1, 12),
            tipo="Servicio Demo",
            ejecutivo=self.ejecutivo,
            tiempo_entrega="5 dias",
            aerea="Si",
            maritima="",
            terrestre="",
        )
        self.referencia = Referencia.objects.create(
            referencia="REF-INI",
            ejecutivo=self.ejecutivo,
            cliente="Cliente Ref",
            servicio="Servicio Ref",
            agencia_aduanal="Agencia Ref",
            fecha=date(2026, 1, 14),
        )

    def test_vista_protegida_redirige_sin_login(self):
        response = self.client.get(reverse("lista_solicitudes"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/login/", response.url)

    def test_lista_usuarios_solo_admin(self):
        self.client.login(username="ejec", password="ejec123")
        response = self.client.get(reverse("lista_usuarios"))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin", password="admin123")
        response = self.client.get(reverse("lista_usuarios"))
        self.assertEqual(response.status_code, 200)

    def test_editar_usuario_permisos(self):
        self.client.login(username="ejec", password="ejec123")
        response = self.client.get(reverse("editar_usuario", args=[self.otro.pk]))
        self.assertEqual(response.status_code, 403)

        response = self.client.post(
            reverse("editar_usuario", args=[self.ejecutivo.pk]),
            {
                "username": "ejec",
                "primer_nombre": "Ejecutivo",
                "segundo_nombre": "",
                "apellidos": "Editado",
                "email": "ejec_editado@example.com",
                "password1": "",
                "password2": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.ejecutivo.refresh_from_db()
        self.assertEqual(self.ejecutivo.first_name, "Ejecutivo")
        self.assertEqual(self.ejecutivo.last_name, "Editado")
        self.assertEqual(self.ejecutivo.email, "ejec_editado@example.com")

        self.client.login(username="admin", password="admin123")
        response = self.client.post(
            reverse("editar_usuario", args=[self.otro.pk]),
            {
                "username": "otro",
                "primer_nombre": "Otro",
                "segundo_nombre": "",
                "apellidos": "Editado",
                "email": "otro_editado@example.com",
                "rol": "usuario",
                "password1": "",
                "password2": "",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.otro.refresh_from_db()
        self.assertEqual(self.otro.first_name, "Otro")
        self.assertEqual(self.otro.last_name, "Editado")
        self.assertEqual(self.otro.email, "otro_editado@example.com")

    def test_cambiar_estado_permisos(self):
        url = reverse("cambiar_estado", args=[self.solicitud.pk, "aereo"])

        self.client.login(username="otro", password="otro123")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 403)

        self.client.login(username="ejec", password="ejec123")
        response = self.client.post(url)
        self.assertEqual(response.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.estado_aereo, "Cumplido")

    def test_cambiar_ejecutivo_solo_admin(self):
        url = reverse("cambiar_ejecutivo", args=[self.solicitud.pk])

        self.client.login(username="ejec", password="ejec123")
        response = self.client.post(url, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin", password="admin123")
        response = self.client.post(url, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 302)
        self.solicitud.refresh_from_db()
        self.assertEqual(self.solicitud.ejecutivo_id, self.otro.pk)

    def test_cambiar_ejecutivo_cotizacion_y_referencia_solo_admin(self):
        url_cot = reverse("cambiar_ejecutivo_cotizacion", args=[self.cotizacion.pk])
        url_ref = reverse("cambiar_ejecutivo_referencia", args=[self.referencia.pk])

        self.client.login(username="ejec", password="ejec123")
        response = self.client.post(url_cot, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 403)
        response = self.client.post(url_ref, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin", password="admin123")
        response = self.client.post(url_cot, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 302)
        response = self.client.post(url_ref, {"ejecutivo": self.otro.pk})
        self.assertEqual(response.status_code, 302)

        self.cotizacion.refresh_from_db()
        self.referencia.refresh_from_db()
        self.assertEqual(self.cotizacion.ejecutivo_id, self.otro.pk)
        self.assertEqual(self.referencia.ejecutivo_id, self.otro.pk)

    def test_no_permite_crear_mas_de_cuatro_administradores(self):
        User.objects.create_user(
            username="admin2", password="admin123", is_superuser=True, is_staff=True
        )
        User.objects.create_user(
            username="admin3", password="admin123", is_superuser=True, is_staff=True
        )
        User.objects.create_user(
            username="admin4", password="admin123", is_superuser=True, is_staff=True
        )
        self.client.login(username="admin", password="admin123")

        response = self.client.post(
            reverse("crear_usuario"),
            {
                "username": "admin5",
                "primer_nombre": "Admin",
                "segundo_nombre": "",
                "apellidos": "Cinco",
                "email": "admin5@example.com",
                "password1": "Admin12345!!",
                "password2": "Admin12345!!",
                "rol": "admin",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Solo se permiten 4 usuarios con rol Administrador.")
        self.assertFalse(User.objects.filter(username="admin5").exists())

    def test_crud_referencias_solo_admin_en_escritura(self):
        self.client.login(username="ejec", password="ejec123")
        response = self.client.get(reverse("crear_referencia"))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin", password="admin123")
        response = self.client.post(
            reverse("crear_referencia"),
            {
                "ejecutivo": self.ejecutivo.pk,
                "cliente": "Cliente R",
                "servicio": "importacion",
                "agencia_aduanal": "Agencia R",
                "fecha": "2026-01-15",
            },
        )
        self.assertEqual(response.status_code, 302)

        referencia = Referencia.objects.get(cliente="Cliente R")
        self.assertEqual(referencia.referencia, "BC261001")

        response = self.client.post(
            reverse("editar_referencia", args=[referencia.pk]),
            {
                "ejecutivo": self.ejecutivo.pk,
                "cliente": "Cliente R",
                "servicio": "exportacion",
                "agencia_aduanal": "Agencia R",
                "fecha": "2026-01-15",
            },
        )
        self.assertEqual(response.status_code, 302)
        referencia.refresh_from_db()
        self.assertEqual(referencia.referencia, "BC262001")

        self.client.login(username="ejec", password="ejec123")
        response = self.client.post(reverse("eliminar_referencia", args=[referencia.pk]))
        self.assertEqual(response.status_code, 403)

        self.client.login(username="admin", password="admin123")
        response = self.client.post(reverse("eliminar_referencia", args=[referencia.pk]))
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Referencia.objects.filter(pk=referencia.pk).exists())

    def test_lista_referencias_ordenamiento_por_id_segun_parametro(self):
        self.client.login(username="admin", password="admin123")
        Referencia.objects.create(referencia="BC261010", ejecutivo=self.ejecutivo)
        Referencia.objects.create(referencia="BC261001", ejecutivo=self.ejecutivo)
        Referencia.objects.create(referencia="BC261002", ejecutivo=self.ejecutivo)

        response = self.client.get(reverse("lista_referencias"))
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8")
        self.assertLess(contenido.find("BC261002"), contenido.find("BC261001"))
        self.assertLess(contenido.find("BC261001"), contenido.find("BC261010"))

        response = self.client.get(reverse("lista_referencias"), {"orden": "asc"})
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8")
        self.assertLess(contenido.find("BC261010"), contenido.find("BC261001"))
        self.assertLess(contenido.find("BC261001"), contenido.find("BC261002"))

        response = self.client.get(reverse("lista_referencias"), {"orden": "desc"})
        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode("utf-8")
        self.assertLess(contenido.find("BC261002"), contenido.find("BC261001"))
        self.assertLess(contenido.find("BC261001"), contenido.find("BC261010"))

    def test_descarga_excel_requiere_login_y_devuelve_archivo(self):
        export_urls = [
            reverse("exportar_solicitudes_excel") + "?anio=2026",
            reverse("exportar_cotizaciones_excel") + "?anio=2026",
            reverse("exportar_referencias_excel"),
        ]

        for url in export_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 302)
            self.assertIn("/login/", response.url)

        self.client.login(username="ejec", password="ejec123")
        for url in export_urls:
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertIn("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", response["Content-Type"])
            self.assertIn(".xlsx", response["Content-Disposition"])


class CotizacionFormTests(TestCase):
    def setUp(self):
        self.ejecutivo = User.objects.create_user(username="ejec_form", password="ejec123")

    def test_genera_consecutivo_automatico(self):
        form_1 = CotizacionForm(
            data={
                "anio": 2026,
                "consecutivo": "",
                "cliente": "Prospecto 1",
                "fecha_solicitud": "2026-02-01",
                "fecha_envio": "",
                "tipo": "Importación aérea",
                "ejecutivo": self.ejecutivo.pk,
                "tiempo_entrega": "5 dias",
                "aerea": "Si",
                "maritima": "",
                "terrestre": "",
            }
        )
        self.assertTrue(form_1.is_valid(), form_1.errors)
        cotizacion_1 = form_1.save()
        self.assertEqual(cotizacion_1.consecutivo, "C26001")

        form_2 = CotizacionForm(
            data={
                "anio": 2026,
                "consecutivo": "",
                "cliente": "Prospecto 2",
                "fecha_solicitud": "2026-02-02",
                "fecha_envio": "",
                "tipo": "Exportación aérea",
                "ejecutivo": self.ejecutivo.pk,
                "tiempo_entrega": "7 dias",
                "aerea": "",
                "maritima": "Si",
                "terrestre": "",
            }
        )
        self.assertTrue(form_2.is_valid(), form_2.errors)
        cotizacion_2 = form_2.save()
        self.assertEqual(cotizacion_2.consecutivo, "C26002")

    def test_ignora_consecutivos_invalidos_al_generar_nuevo(self):
        Cotizacion.objects.create(
            anio=2026,
            consecutivo="C26262014",
            cliente="Dato invalido",
            fecha_solicitud=date(2026, 1, 10),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            tiempo_entrega="",
            aerea="",
            maritima="",
            terrestre="",
        )
        Cotizacion.objects.create(
            anio=2026,
            consecutivo="C26014",
            cliente="Dato valido",
            fecha_solicitud=date(2026, 1, 11),
            tipo="Importación aérea",
            ejecutivo=self.ejecutivo,
            tiempo_entrega="",
            aerea="",
            maritima="",
            terrestre="",
        )

        form = CotizacionForm(
            data={
                "anio": 2026,
                "consecutivo": "",
                "cliente": "Prospecto nuevo",
                "fecha_solicitud": "2026-02-03",
                "fecha_envio": "",
                "tipo": "Exportación aérea",
                "ejecutivo": self.ejecutivo.pk,
                "tiempo_entrega": "",
                "aerea": "on",
                "maritima": "",
                "terrestre": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        cotizacion = form.save()
        self.assertEqual(cotizacion.consecutivo, "C26015")

    def test_tipo_debe_ser_una_opcion_valida(self):
        form = CotizacionForm(
            data={
                "anio": 2026,
                "consecutivo": "",
                "cliente": "Prospecto X",
                "fecha_solicitud": "2026-02-03",
                "fecha_envio": "",
                "tipo": "Tipo no valido",
                "ejecutivo": self.ejecutivo.pk,
                "tiempo_entrega": "4 dias",
                "aerea": "",
                "maritima": "",
                "terrestre": "Si",
            }
        )
        self.assertFalse(form.is_valid())
        self.assertIn("tipo", form.errors)

    def test_importar_referencias_normaliza_al_formato_de_pagina(self):
        filas = [
            ["Referencia", "Ejecutivo", "Cliente", "Servicio", "Agencia", "Fecha"],
            ["ABC-1", "ejec_form", "Cliente 1", "Servicio y transporte", "Agencia 1", "15/01/2026"],
            ["ABC-2", "", "Cliente 2", "Comercializadora exportación", "Agencia 2", "2026-01-16"],
        ]

        creados, actualizados, omitidos = _importar_referencias_desde_filas(filas)
        self.assertEqual((creados, actualizados, omitidos), (2, 0, 0))

        referencias = list(
            Referencia.objects.filter(cliente__in=["Cliente 1", "Cliente 2"]).order_by("cliente")
        )
        self.assertEqual(len(referencias), 2)
        self.assertRegex(referencias[0].referencia, r"^BC26[1-6]\d{3}$")
        self.assertRegex(referencias[1].referencia, r"^BC26[1-6]\d{3}$")
        self.assertEqual(referencias[0].servicio, "servicios_transporte")
        self.assertEqual(referencias[1].servicio, "comercializador_exportacion")


class SolicitudFormTests(TestCase):
    def setUp(self):
        self.ejecutivo = User.objects.create_user(username="ejec_sg", password="ejec123")

    def test_genera_sg_automatico_consecutivo(self):
        form_1 = SolicitudForm(
            data={
                "anio": 2026,
                "sg": "",
                "cliente": "Cliente 1",
                "fecha_recepcion": "2026-01-10",
                "fecha_entrega": "",
                "tipo": "Importación aérea",
                "ejecutivo": self.ejecutivo.pk,
                "aerea": True,
                "maritima": False,
                "terrestre": False,
            }
        )
        self.assertTrue(form_1.is_valid(), form_1.errors)
        solicitud_1 = form_1.save()
        self.assertEqual(solicitud_1.sg, "SG26001")

        form_2 = SolicitudForm(
            data={
                "anio": 2026,
                "sg": "",
                "cliente": "Cliente 2",
                "fecha_recepcion": "2026-01-11",
                "fecha_entrega": "",
                "tipo": "Importación aérea",
                "ejecutivo": self.ejecutivo.pk,
                "aerea": False,
                "maritima": True,
                "terrestre": False,
            }
        )
        self.assertTrue(form_2.is_valid(), form_2.errors)
        solicitud_2 = form_2.save()
        self.assertEqual(solicitud_2.sg, "SG26002")

    def test_sg_no_se_puede_manipular_en_edicion(self):
        solicitud = Solicitud.objects.create(
            anio=2026,
            sg="SG26001",
            cliente="Cliente Base",
            fecha_recepcion=date(2026, 1, 10),
            tipo="Operacion",
            aerea=True,
            estado_aereo="Pendiente",
            ejecutivo=self.ejecutivo,
        )

        form = SolicitudForm(
            data={
                "anio": 2026,
                "sg": "SG99999",
                "cliente": "Cliente Editado",
                "fecha_recepcion": "2026-01-10",
                "fecha_entrega": "",
                "tipo": "Operacion",
                "ejecutivo": self.ejecutivo.pk,
                "aerea": True,
                "maritima": False,
                "terrestre": False,
            },
            instance=solicitud,
        )
        self.assertTrue(form.is_valid(), form.errors)
        actualizado = form.save()
        self.assertEqual(actualizado.sg, "SG26001")
