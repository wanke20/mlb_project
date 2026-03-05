from django.urls import path
from .views import game_list, game_prediction

urlpatterns = [
    path("", game_list),
    path("<int:game_id>", game_prediction, name="game_prediction"),
]