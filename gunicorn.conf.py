"""
Gunicorn configuration for production deployment.

Loaded explicitly via ``-c gunicorn.conf.py`` from the Procfile so the
access-log format string lives in Python, not a shell-quoted Procfile arg.
"""

import os

bind = f"0.0.0.0:{os.environ.get('PORT', '8000')}"
accesslog = "-"

# Default ``%(h)s`` is REMOTE_ADDR, which is dokku's Docker bridge gateway
# behind the proxy chain. Read the real client IP from the Cloudflare-set
# header instead; Cloudflare strips it from inbound requests, so it is
# trustworthy when the origin is only reachable via tunnel.
access_log_format = '%({cf-connecting-ip}i)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'
