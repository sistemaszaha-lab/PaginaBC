from django.contrib.auth.models import Group, Permission, User
from django.test import TestCase

from .forms import CrearUsuarioForm, EditarUsuarioForm
from .permissions import SOLO_LECTURA_GROUP, es_admin, es_ejecutivo, es_solo_lectura, puede_escribir, puede_ver_todo


class RolesUsuarioTests(TestCase):
    def test_migration_group_exists_and_is_idempotent(self):
        self.assertTrue(Group.objects.filter(name=SOLO_LECTURA_GROUP).exists())
        Group.objects.get_or_create(name=SOLO_LECTURA_GROUP)
        self.assertEqual(Group.objects.filter(name=SOLO_LECTURA_GROUP).count(), 1)

    def _data(self, **extra):
        data = {
            "username": "lectura",
            "primer_nombre": "Solo",
            "segundo_nombre": "",
            "apellidos": "Lectura",
            "email": "lectura@example.com",
            "password1": "UnaClaveSegura123!",
            "password2": "UnaClaveSegura123!",
            "rol": "solo_lectura",
        }
        data.update(extra)
        return data

    def test_crear_usuario_solo_lectura(self):
        form = CrearUsuarioForm(data=self._data())
        self.assertTrue(form.is_valid(), form.errors)
        user = form.save()
        self.assertTrue(es_solo_lectura(user))
        self.assertFalse(es_admin(user))
        self.assertFalse(es_ejecutivo(user))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.is_superuser)
        self.assertFalse(puede_escribir(user))
        self.assertTrue(puede_ver_todo(user))
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [SOLO_LECTURA_GROUP])

    def test_solo_lectura_limpia_grupos_y_permisos_directos(self):
        user = User.objects.create_user("existente", password="x")
        legacy_group = Group.objects.create(name="LEGACY_WRITE")
        user.groups.add(legacy_group)
        user.user_permissions.add(Permission.objects.first())
        form = EditarUsuarioForm(data={
            "username": user.username, "primer_nombre": "Usuario", "segundo_nombre": "",
            "apellidos": "Prueba", "email": "", "rol": "solo_lectura",
            "password1": "", "password2": "",
        }, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertTrue(es_solo_lectura(user))
        self.assertFalse(user.is_staff)
        self.assertFalse(user.user_permissions.exists())
        self.assertEqual(list(user.groups.values_list("name", flat=True)), [SOLO_LECTURA_GROUP])

    def test_cambio_a_ejecutivo_y_admin(self):
        user = User.objects.create_user("cambio", password="x")
        solo_data = {"username": "cambio", "primer_nombre": "Usuario", "segundo_nombre": "", "apellidos": "Prueba", "email": "", "rol": "solo_lectura", "password1": "", "password2": ""}
        form = EditarUsuarioForm(data=solo_data, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        form = EditarUsuarioForm(data={**solo_data, "rol": "usuario"}, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertTrue(es_ejecutivo(user))
        self.assertFalse(user.groups.filter(name=SOLO_LECTURA_GROUP).exists())
        form = EditarUsuarioForm(data={**solo_data, "rol": "admin"}, instance=user)
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        user.refresh_from_db()
        self.assertTrue(es_admin(user))
        self.assertTrue(user.is_staff)
        self.assertFalse(user.groups.filter(name=SOLO_LECTURA_GROUP).exists())

    def test_usuario_existente_sin_grupo_sigue_siendo_ejecutivo(self):
        user = User.objects.create_user("normal", password="x")
        self.assertTrue(es_ejecutivo(user))
        self.assertTrue(puede_escribir(user))
