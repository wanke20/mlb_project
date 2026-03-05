from django.urls import path
from .views import home_page, game_list, game_prediction

urlpatterns = [
    path("", home_page, name="home_page"),
    path("games/", game_list, name="game_list"),
    path("games/<int:game_id>/", game_prediction, name="game_prediction"),
]