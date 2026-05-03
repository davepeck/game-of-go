web: gunicorn go.wsgi:application --bind 0.0.0.0:${PORT} --access-logfile - --access-logformat '%({cf-connecting-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
release: python3 manage.py migrate --noinput
