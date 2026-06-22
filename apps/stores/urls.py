from django.urls import path
from . import views
from apps.orders.views import OrderListView

urlpatterns = [
    path("stores/<int:store_id>/inventory/", views.InventoryListView.as_view(), name="store-inventory"),
    path("stores/<int:store_id>/orders/", OrderListView.as_view(), name="store-orders"),
]
