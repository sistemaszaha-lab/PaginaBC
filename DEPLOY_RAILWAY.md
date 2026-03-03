# Deploy en Railway (produccion)

Esta guia deja la app operando 24/7 sin servidor local.

## 1) Subir proyecto a GitHub

Desde la carpeta `solicitudes_app`:

```powershell
git init
git add .
git commit -m "Preparar proyecto para deploy en Railway"
git branch -M main
git remote add origin <URL_DEL_REPO>
git push -u origin main
```

## 2) Crear proyecto en Railway

1. Entra a Railway y crea un proyecto desde GitHub.
2. Selecciona este repositorio.
3. Agrega un servicio PostgreSQL desde "Add Service" > "Database" > "PostgreSQL".

## 3) Variables de entorno (servicio web)

En el servicio de Django agrega:

- `DJANGO_SECRET_KEY`: una cadena larga aleatoria.
- `DJANGO_DEBUG`: `False`
- `DJANGO_ALLOWED_HOSTS`: dominio publico de Railway (ejemplo: `tuapp.up.railway.app`)
- `DJANGO_CSRF_TRUSTED_ORIGINS`: `https://tuapp.up.railway.app`

Railway inyecta `DATABASE_URL` automaticamente cuando conectas PostgreSQL.

## 4) Comandos de deploy

Railway usara por defecto:

- Install: `pip install -r requirements.txt`
- Start: `python manage.py migrate && python manage.py collectstatic --noinput && gunicorn solicitudes_app.wsgi --bind 0.0.0.0:$PORT --log-file -`

Si necesitas crear admin una sola vez (en Railway shell):

```bash
python manage.py createsuperuser
```

## 5) Migrar datos actuales de SQLite a PostgreSQL (opcional recomendado)

En local, antes del deploy final:

```powershell
..\venv\Scripts\python.exe manage.py dumpdata --exclude auth.permission --exclude contenttypes --indent 2 > data.json
```

Con el proyecto apuntando temporalmente a PostgreSQL (`DATABASE_URL`), carga:

```powershell
..\venv\Scripts\python.exe manage.py loaddata data.json
```

## 6) Checklist final

- Login funciona en el dominio publico.
- Archivos estaticos cargan correctamente.
- Alta/edicion/listado de solicitudes funciona.
- Existe al menos un usuario administrador.
- Se activa backup automatico de PostgreSQL en Railway.
