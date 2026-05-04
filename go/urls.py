"""Project-level URL routing: admin + the game app."""

from django.urls import include, path

from .admin import admin_site

urlpatterns = [
    path("admin/", admin_site.urls),
    path("", include("go.game.urls")),
]
