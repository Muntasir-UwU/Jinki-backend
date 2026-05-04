from django.urls import path
from sync.views import health

urlpatterns = [
    path("health/", health),
]
