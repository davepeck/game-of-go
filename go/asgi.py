"""ASGI entry point (not currently used; kept for future use)."""

import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "go.settings")

application = get_asgi_application()
