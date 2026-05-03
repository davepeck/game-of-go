"""Project-level middleware."""

import typing as t

from django.conf import settings
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


class MaintenanceModeMiddleware:
    """Serve a maintenance page for every request when ``MAINTENANCE_MODE`` is on."""

    def __init__(self, get_response: t.Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        if getattr(settings, "MAINTENANCE_MODE", False):
            return render(request, "maintenance.html", status=503)
        return self.get_response(request)
