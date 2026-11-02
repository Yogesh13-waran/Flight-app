from rest_framework import serializers
from django.contrib.auth.models import User
from rest_framework_simplejwt.tokens import RefreshToken
from .models import UserProfile, PriceAlert, NotificationLog

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, required=True, min_length=6)
    email = serializers.EmailField(required=False, default="")

    class Meta:
        model = User
        fields = ('username', 'password', 'email')

    def create(self, validated_data):
        # Create user (UserProfile is automatically created via post_save signal with role='user')
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data.get('email', ''),
            password=validated_data['password']
        )
        return user


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField(required=True)
    password = serializers.CharField(required=True, write_only=True)


class PriceAlertSerializer(serializers.ModelSerializer):
    class Meta:
        model = PriceAlert
        fields = ['id', 'origin', 'destination', 'threshold_price', 'status', 'created_at']
        read_only_fields = ['id', 'status', 'created_at']

    def validate_origin(self, value):
        val = value.strip().upper()
        if not val:
            raise serializers.ValidationError("Origin cannot be empty.")
        return val

    def validate_destination(self, value):
        val = value.strip().upper()
        if not val:
            raise serializers.ValidationError("Destination cannot be empty.")
        return val

    def validate(self, attrs):
        origin = attrs.get('origin', getattr(self.instance, 'origin', None))
        destination = attrs.get('destination', getattr(self.instance, 'destination', None))
        if origin and destination and origin.upper() == destination.upper():
            raise serializers.ValidationError("Origin and destination cannot be identical.")
        threshold_price = attrs.get('threshold_price')
        if threshold_price is not None and threshold_price <= 0:
            raise serializers.ValidationError({"threshold_price": "Threshold price must be greater than 0."})
        return attrs


class NotificationLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationLog
        fields = ['id', 'alert', 'triggered_price', 'message', 'notified_at']
        read_only_fields = ['id', 'alert', 'triggered_price', 'message', 'notified_at']

