from django.urls import path
from .views import ProductSearchView, AutocompleteView

urlpatterns = [
    path("products/", ProductSearchView.as_view(), name="product-search"),
    path("suggest/", AutocompleteView.as_view(), name="autocomplete"),
]
