from django.urls import path
from .views import (
    RegisterView,
    LoginView,
    AlertListCreateView,
    AlertDetailView,
    FlightPriceView,
    AdminSummaryView,
)

urlpatterns = [
    # Auth
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', LoginView.as_view(), name='auth-login'),

    # Alerts
    path('alerts/', AlertListCreateView.as_view(), name='alerts-list-create'),
    path('alerts/<int:pk>/', AlertDetailView.as_view(), name='alerts-detail'),

    # Mock Price Feed (Internal)
    path('flights/price/', FlightPriceView.as_view(), name='flight-price-feed'),

    # Admin Analytics
    path('admin/summary/', AdminSummaryView.as_view(), name='admin-summary'),
]

