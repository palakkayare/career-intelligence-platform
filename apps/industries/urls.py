from django.urls import path

from .views import IndustryListView

app_name = "industries"

urlpatterns = [
    path("", IndustryListView.as_view(), name="industry-list"),
]
