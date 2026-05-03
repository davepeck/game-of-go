web: gunicorn go.wsgi:application --bind 0.0.0.0:${PORT} --access-logfile -
release: python3 manage.py migrate --noinput
