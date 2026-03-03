web: sh -c "python manage.py migrate && python manage.py collectstatic --noinput && python manage.py ensure_superuser && gunicorn solicitudes_app.wsgi --bind 0.0.0.0:${PORT:-8000} --log-file -"
