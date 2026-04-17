from django.urls import path

from . import views

app_name = "bookmarks"

urlpatterns = [
    path("", views.index, name="index"),
    path("list/", views.list_bookmarks, name="list"),
    path("cmd/", views.cmd_palette, name="cmd"),
    path("opensearch.xml", views.opensearch, name="opensearch"),
    path("search/", views.search_redirect, name="search"),
    path("api/status/", views.bookmark_status, name="status"),
    path("api/suggestions/", views.search_suggestions, name="suggestions"),
    path("api/history/", views.command_history, name="history"),
    path("health", views.health_check, name="health_check"),
    path("<str:key>/", views.redirect_bookmark, name="redirect"),
]
