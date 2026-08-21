from django.urls import path
from .views import home_page, game_list, game_prediction, pitcher_list, pitcher_detail, trends, export_csv, export_bullpen_csv, export_results_csv, export_hitters_csv

urlpatterns = [
    path("", home_page, name="home_page"),
    path("games/", game_list, name="game_list"),
    path("games/<int:game_id>/", game_prediction, name="game_prediction"),
    path("pitchers/", pitcher_list, name="pitcher_list"),
    path("pitchers/<int:mlb_id>/", pitcher_detail, name="pitcher_detail"),
    path("trends/", trends, name="trends"),
    path("export/", export_csv, name="export_csv"),
    path("export/bullpen/", export_bullpen_csv, name="export_bullpen_csv"),
    path("export/results/", export_results_csv, name="export_results_csv"),
    path("export/hitters/", export_hitters_csv, name="export_hitters_csv"),
]