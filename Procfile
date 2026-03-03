web: sh -c "python manage.py migrate && python manage.py collectstatic --noinput && gunicorn solicitudes_app.wsgi --bind 0.0.0.0:${PORT:-8000} --log-file -"
