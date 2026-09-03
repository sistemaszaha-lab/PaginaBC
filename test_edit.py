import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "solicitudes_app.settings")
import django.conf
django.conf.settings.ALLOWED_HOSTS = ['testserver']
django.setup()

from django.test import Client
from django.contrib.auth import get_user_model
from operaciones.models import Operacion, OperacionColumna
from clientes.models import Cliente
import json

User = get_user_model()
admin = User.objects.filter(username="admin_test").first()
if not admin:
    admin = User.objects.create_superuser('admin_test', 'admin@example.com', 'admin')

cliente = Cliente.objects.filter(nombre="Test Cliente").first()
if not cliente:
    cliente = Cliente.objects.create(nombre="Test Cliente")
    
columna = OperacionColumna.objects.filter(codigo="TEST_COL").first()
if not columna:
    columna = OperacionColumna.objects.create(nombre="Test Columna", codigo="TEST_COL", activa=True)
    
operacion = Operacion.objects.filter(titulo="Test").first()
if not operacion:
    operacion = Operacion.objects.create(titulo="Test", creado_por=admin, columna=columna, estado="TEST_COL")

c = Client()
c.force_login(admin)

print("--- Testing Quick Edit ---")
resp = c.post(f"/operaciones/rapida/{operacion.id}/", {
    "titulo": "Test Edited",
    "fecha_vencimiento": "2026-09-01",
    "eta": "2026-09-02",
    "asignados_present": "1"
}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
print(resp.status_code)
if resp.status_code == 400:
    print(json.loads(resp.content.decode('utf-8')).get('errors'))
else:
    print(resp.content.decode('utf-8')[:100])

print("\n--- Testing Inline Create ---")
resp2 = c.post("/operaciones/nueva/inline/", {
    "titulo": "New Inline",
    "estado": "TEST_COL",
}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
print(resp2.status_code)
if resp2.status_code == 400:
    print(json.loads(resp2.content.decode('utf-8')).get('errors'))
else:
    print(resp2.content.decode('utf-8')[:100])

print("\n--- Testing Edit ---")
resp3 = c.post(f"/operaciones/{operacion.id}/editar/", {
    "titulo": "Test Detailed Edit",
    "fecha_vencimiento": "2026-09-01",
    "asignados_present": "1"
}, HTTP_X_REQUESTED_WITH="XMLHttpRequest")
print(resp3.status_code)
if resp3.status_code == 400:
    try:
        print(json.loads(resp3.content.decode('utf-8')).get('errors'))
    except:
        print("Invalid response")
else:
    print(resp3.content.decode('utf-8')[:100])
