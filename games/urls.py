from django.urls import path
from .views import game_list, game_prediction

urlpatterns = [
    path("games", game_list),
    path("games/<int:game_id>", game_prediction, name="game_prediction"),
]