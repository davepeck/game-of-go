"""Project-level URL routing: admin + the game app."""

from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("go.game.urls")),
]
