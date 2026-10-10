from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from .permissions import SOLO_LECTURA_GROUP


class SoloLecturaWriteProtectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user("consulta", password="UnaClaveSegura123!")
        group = Group.objects.get_or_create(name=SOLO_LECTURA_GROUP)[0]
        cls.user.groups.add(group)

    def test_post_de_negocio_retorna_403_json_y_no_crea(self):
        self.client.force_login(self.user)
        before = User.objects.count()
        response = self.client.post(
            reverse("crear_usuario"),
            {"username": "no-debe-crearse"},
            HTTP_X_REQUESTED_WITH="XMLHttpRequest",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.json()["error"], "solo_lectura")
        self.assertEqual(User.objects.count(), before)

    def test_put_y_delete_de_negocio_retorna_403(self):
        self.client.force_login(self.user)
        self.assertEqual(self.client.put("/clientes/1/", {}).status_code, 403)
        self.assertEqual(self.client.delete("/clientes/1/").status_code, 403)

    def test_consulta_get_sigue_disponible(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("inicio"))
        self.assertNotEqual(response.status_code, 403)
        self.assertContains(response, 'data-read-only="true"')
        self.assertContains(response, "Solo lectura")
        self.assertNotContains(response, "data-read-only-indicator")
        self.assertContains(response, ">Usuarios</a>")

    def test_listado_de_usuarios_es_consultable(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse("lista_usuarios"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.user.username)

    def test_formulario_crear_usuario_solo_lectura_solo_get(self):
        self.client.force_login(self.user)
        before = User.objects.count()

        get_response = self.client.get(reverse("crear_usuario"))
        self.assertEqual(get_response.status_code, 200)
        self.assertContains(get_response, 'data-read-only="true"')
        self.assertContains(get_response, 'method="post"')

        post_response = self.client.post(
            reverse("crear_usuario"),
            {"username": "no-debe-crearse"},
        )
        self.assertEqual(post_response.status_code, 403)
        self.assertEqual(User.objects.count(), before)

    def test_login_y_logout_no_se_bloquean(self):
        self.client.logout()
        self.assertEqual(self.client.post(reverse("login"), {"username": "consulta", "password": "UnaClaveSegura123!"}).status_code, 302)
        self.assertEqual(self.client.post(reverse("logout")).status_code, 302)
