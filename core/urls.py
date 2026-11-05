"""URL routes for the core app."""

from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("explorer/", views.explorer, name="explorer"),
    path("explorer/game/<str:game_id>/", views.game_detail, name="game_detail"),
]
