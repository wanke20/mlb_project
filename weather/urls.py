from django.urls import path
from .views import weather

urlpatterns = [
    path("weather/", weather, name="weather"),
]
