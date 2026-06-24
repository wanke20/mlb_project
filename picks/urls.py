from django.urls import path

from .views import assistant_api, dashboard, delete_pick, make_pick

urlpatterns = [
    path("dashboard/", dashboard, name="dashboard"),
    path("picks/<int:game_id>/", make_pick, name="make_pick"),
    path("picks/<int:game_id>/delete/", delete_pick, name="delete_pick"),
    path("assistant/", assistant_api, name="assistant_api"),
]
