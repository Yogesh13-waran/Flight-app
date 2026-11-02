import random
from django.contrib.auth import authenticate
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework_simplejwt.tokens import RefreshToken

from .models import UserProfile, PriceAlert, NotificationLog
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    PriceAlertSerializer,
    NotificationLogSerializer,
)
from .permissions import IsAdminUser


class RegisterView(APIView):
    """
    POST /api/auth/register/
    Public endpoint to register a new user.
    Auto-creates UserProfile with role='user'.
    Returns 201 with username, JWT access token, and role.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        if serializer.is_valid():
            user = serializer.save()
            refresh = RefreshToken.for_user(user)
            return Response(
                {
                    "username": user.username,
                    "access": str(refresh.access_token),
                    "role": user.profile.role,
                },
                status=status.HTTP_201_CREATED
            )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginView(APIView):
    """
    POST /api/auth/login/
    Public endpoint to authenticate user and obtain JWT tokens.
    Returns 200 on success, 401 on invalid credentials.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        username = serializer.validated_data['username']
        password = serializer.validated_data['password']

        user = authenticate(request, username=username, password=password)
        if user is None:
            return Response(
                {"detail": "Invalid credentials"},
                status=status.HTTP_401_UNAUTHORIZED
            )

        refresh = RefreshToken.for_user(user)
        role = getattr(user.profile, 'role', UserProfile.Role.USER) if hasattr(user, 'profile') else UserProfile.Role.USER
        return Response(
            {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "username": user.username,
                "role": role,
            },
            status=status.HTTP_200_OK
        )


class AlertListCreateView(APIView):
    """
    GET /api/alerts/ - List alerts belonging to the logged-in user only.
    POST /api/alerts/ - Create a new price alert for the logged-in user.
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        alerts = PriceAlert.objects.filter(user=request.user).order_by('-created_at')
        serializer = PriceAlertSerializer(alerts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request):
        serializer = PriceAlertSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(user=request.user, status=PriceAlert.Status.ACTIVE)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class AlertDetailView(APIView):
    """
    DELETE /api/alerts/<id>/ - Soft-deactivates an alert.
    Never exposes existence of another user's alert (returns 404).
    """
    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        # Fetch alert scoped to request.user or return 404
        alert = get_object_or_404(PriceAlert, pk=pk)
        if alert.user != request.user:
            return Response({"detail": "Not found."}, status=status.HTTP_404_NOT_FOUND)

        alert.status = PriceAlert.Status.INACTIVE
        alert.save(update_fields=['status'])
        return Response({"status": "inactive"}, status=status.HTTP_200_OK)


# Mock price dataset for flight routes
MOCK_PRICES = {
    'DEL-BOM': (3000, 7000),
    'BLR-HYD': (1500, 4000),
    'DEL-BLR': (4000, 9000),
    'BOM-GOA': (2000, 5000),
}


class FlightPriceView(APIView):
    """
    GET /api/flights/price/?route=DEL-BOM
    Internal mock flight price feed.
    No authentication required.
    """
    authentication_classes = []
    permission_classes = [AllowAny]

    def get(self, request):
        route = request.GET.get('route', '').strip().upper()
        price_range = MOCK_PRICES.get(route)
        if not price_range:
            return Response({'error': 'Route not found'}, status=status.HTTP_404_NOT_FOUND)

        price = random.randint(*price_range)
        return Response({'route': route, 'price': price}, status=status.HTTP_200_OK)


class AdminSummaryView(APIView):
    """
    GET /api/admin/summary/
    Returns platform-wide statistics.
    Only accessible to users with role = ADMIN.
    Regular users receive 403 Forbidden.
    """
    permission_classes = [IsAdminUser]

    def get(self, request):
        # 1. PriceAlert aggregate counts using SQL aggregations
        alert_stats = PriceAlert.objects.aggregate(
            total_alerts=Count('id'),
            active_alerts=Count('id', filter=Q(status=PriceAlert.Status.ACTIVE)),
            triggered_alerts=Count('id', filter=Q(status=PriceAlert.Status.TRIGGERED)),
        )

        # 2. NotificationLog aggregate count
        notif_stats = NotificationLog.objects.aggregate(
            total_notifications=Count('id')
        )

        # 3. Top routes grouped via values().annotate()
        top_routes_qs = (
            PriceAlert.objects
            .values('origin', 'destination')
            .annotate(alert_count=Count('id'))
            .order_by('-alert_count')
        )

        top_routes = [
            {
                "route": f"{item['origin']}-{item['destination']}",
                "alert_count": item['alert_count']
            }
            for item in top_routes_qs
        ]

        data = {
            "total_alerts": alert_stats['total_alerts'] or 0,
            "active_alerts": alert_stats['active_alerts'] or 0,
            "triggered_alerts": alert_stats['triggered_alerts'] or 0,
            "total_notifications": notif_stats['total_notifications'] or 0,
            "top_routes": top_routes,
        }
        return Response(data, status=status.HTTP_200_OK)

