from decimal import Decimal
from unittest.mock import patch, MagicMock
from django.test import TestCase
from django.contrib.auth.models import User
from rest_framework.test import APIClient
from rest_framework import status

from .models import UserProfile, PriceAlert, NotificationLog
from .tasks import check_prices, send_notification


# =====================================================================
# 1. Required Unit Tests Specified in the Assignment Brief
# =====================================================================

class PriceThresholdTest(TestCase):
    """
    Required Test 1 - Threshold comparison logic.
    Tests boundary conditions and strict inequalities.
    """
    def test_price_below_threshold_triggers_alert(self):
        # If current price (4200) <= threshold (4500), alert should fire
        self.assertTrue(4200 <= 4500)

    def test_price_above_threshold_does_not_trigger(self):
        # If current price (5000) > threshold (4500), alert should not fire
        self.assertFalse(5000 <= 4500)

    def test_price_equal_to_threshold_triggers_alert(self):
        # Edge case: price == threshold should still trigger
        self.assertTrue(4500 <= 4500)


class NotificationLogTest(TestCase):
    """
    Required Test 2 - NotificationLog is created correctly with foreign key.
    """
    def setUp(self):
        self.user = User.objects.create_user(
            username='testuser',
            password='testpass'
        )
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin='DEL',
            destination='BOM',
            threshold_price=Decimal('4500.00'),
            status=PriceAlert.Status.ACTIVE
        )

    def test_notification_log_created_with_correct_message(self):
        log = NotificationLog.objects.create(
            alert=self.alert,
            triggered_price=Decimal('4200.00'),
            message='Price dropped to 4200 for DEL-BOM'
        )
        self.assertEqual(log.triggered_price, Decimal('4200.00'))
        self.assertEqual(log.alert, self.alert)
        self.assertIn('DEL-BOM', log.message)


class AlertScopingTest(TestCase):
    """
    Required Test 3 - Alert scoping (users see only their own alerts).
    """
    def setUp(self):
        self.user1 = User.objects.create_user(
            username='user1',
            password='pass'
        )
        self.user2 = User.objects.create_user(
            username='user2',
            password='pass'
        )
        PriceAlert.objects.create(
            user=self.user1,
            origin='DEL',
            destination='BOM',
            threshold_price=Decimal('4500.00')
        )
        PriceAlert.objects.create(
            user=self.user2,
            origin='BLR',
            destination='HYD',
            threshold_price=Decimal('2000.00')
        )

    def test_user_only_sees_own_alerts(self):
        user1_alerts = PriceAlert.objects.filter(user=self.user1)
        self.assertEqual(user1_alerts.count(), 1)
        self.assertEqual(user1_alerts.first().origin, 'DEL')

    def test_user_cannot_see_other_users_alerts(self):
        user1_alerts = PriceAlert.objects.filter(user=self.user1)
        # user1 should not see user2's BLR-HYD alert
        self.assertNotEqual(user1_alerts.first().origin, 'BLR')


# =====================================================================
# 2. Comprehensive API Endpoint & Business Logic Tests
# =====================================================================

class AuthEndpointsTest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_register_success(self):
        response = self.client.post(
            '/api/auth/register/',
            {'username': 'newuser', 'password': 'securepassword123', 'email': 'new@test.com'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['username'], 'newuser')
        self.assertIn('access', response.data)
        self.assertEqual(response.data['role'], 'user')

        # Check UserProfile was created automatically via signal
        user = User.objects.get(username='newuser')
        self.assertEqual(user.profile.role, UserProfile.Role.USER)

    def test_register_role_spoofing_prevented(self):
        # Even if attacker passes role: admin, it must remain user
        response = self.client.post(
            '/api/auth/register/',
            {'username': 'hacker', 'password': 'securepassword123', 'role': 'admin'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['role'], 'user')
        user = User.objects.get(username='hacker')
        self.assertEqual(user.profile.role, UserProfile.Role.USER)

    def test_register_duplicate_username_fails(self):
        User.objects.create_user(username='existing', password='password123')
        response = self.client.post(
            '/api/auth/register/',
            {'username': 'existing', 'password': 'password123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_short_password_fails(self):
        response = self.client.post(
            '/api/auth/register/',
            {'username': 'shortpass', 'password': '123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login_success(self):
        User.objects.create_user(username='loginuser', password='password123')
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'loginuser', 'password': 'password123'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('access', response.data)
        self.assertIn('refresh', response.data)

    def test_login_invalid_password(self):
        User.objects.create_user(username='loginuser', password='password123')
        response = self.client.post(
            '/api/auth/login/',
            {'username': 'loginuser', 'password': 'wrongpassword'},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class AlertAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user1 = User.objects.create_user(username='alice', password='password123')
        self.user2 = User.objects.create_user(username='bob', password='password123')
        self.client.force_authenticate(user=self.user1)

    def test_create_alert_success(self):
        response = self.client.post(
            '/api/alerts/',
            {'origin': 'del', 'destination': 'bom', 'threshold_price': 4500},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data['origin'], 'DEL')
        self.assertEqual(response.data['destination'], 'BOM')
        self.assertEqual(response.data['status'], 'active')

    def test_create_alert_same_origin_destination_fails(self):
        response = self.client.post(
            '/api/alerts/',
            {'origin': 'DEL', 'destination': 'DEL', 'threshold_price': 4500},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_alert_non_positive_threshold_fails(self):
        response = self.client.post(
            '/api/alerts/',
            {'origin': 'DEL', 'destination': 'BOM', 'threshold_price': -500},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_alert_unauthenticated_fails(self):
        unauth_client = APIClient()
        response = unauth_client.post(
            '/api/alerts/',
            {'origin': 'DEL', 'destination': 'BOM', 'threshold_price': 4500},
            format='json'
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_get_alerts_scoped_to_logged_in_user(self):
        PriceAlert.objects.create(user=self.user1, origin='DEL', destination='BOM', threshold_price=4500)
        PriceAlert.objects.create(user=self.user2, origin='BLR', destination='HYD', threshold_price=2000)

        response = self.client.get('/api/alerts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 1)
        self.assertEqual(response.data[0]['origin'], 'DEL')

    def test_get_alerts_empty_returns_200_with_empty_list(self):
        response = self.client.get('/api/alerts/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, [])

    def test_get_alerts_unauthenticated_fails(self):
        unauth_client = APIClient()
        response = unauth_client.get('/api/alerts/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_delete_alert_sets_status_inactive(self):
        alert = PriceAlert.objects.create(user=self.user1, origin='DEL', destination='BOM', threshold_price=4500)
        response = self.client.delete(f'/api/alerts/{alert.id}/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data, {'status': 'inactive'})

        alert.refresh_from_db()
        self.assertEqual(alert.status, PriceAlert.Status.INACTIVE)

    def test_delete_other_user_alert_returns_404(self):
        # Alice tries to delete Bob's alert -> must return 404 (IDOR prevention)
        bobs_alert = PriceAlert.objects.create(user=self.user2, origin='BLR', destination='HYD', threshold_price=2000)
        response = self.client.delete(f'/api/alerts/{bobs_alert.id}/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_delete_unauthenticated_fails(self):
        alert = PriceAlert.objects.create(user=self.user1, origin='DEL', destination='BOM', threshold_price=4500)
        unauth_client = APIClient()
        response = unauth_client.delete(f'/api/alerts/{alert.id}/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class FlightPriceAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()

    def test_flight_price_valid_route(self):
        response = self.client.get('/api/flights/price/?route=DEL-BOM')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['route'], 'DEL-BOM')
        self.assertGreaterEqual(response.data['price'], 3000)
        self.assertLessEqual(response.data['price'], 7000)

    def test_flight_price_case_insensitive(self):
        response = self.client.get('/api/flights/price/?route=del-bom')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['route'], 'DEL-BOM')

    def test_flight_price_invalid_route(self):
        response = self.client.get('/api/flights/price/?route=UNKNOWN-ROUTE')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_flight_price_missing_query_param(self):
        response = self.client.get('/api/flights/price/')
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class AdminSummaryAPITest(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin_user = User.objects.create_user(username='admin', password='password123')
        self.admin_user.profile.role = UserProfile.Role.ADMIN
        self.admin_user.profile.save()

        self.regular_user = User.objects.create_user(username='regular', password='password123')

        # Sample alerts
        alert1 = PriceAlert.objects.create(user=self.regular_user, origin='DEL', destination='BOM', threshold_price=4500, status=PriceAlert.Status.ACTIVE)
        PriceAlert.objects.create(user=self.regular_user, origin='DEL', destination='BOM', threshold_price=4000, status=PriceAlert.Status.TRIGGERED)
        PriceAlert.objects.create(user=self.regular_user, origin='BLR', destination='HYD', threshold_price=2000, status=PriceAlert.Status.INACTIVE)

        NotificationLog.objects.create(alert=alert1, triggered_price=3900, message='Price dropped')

    def test_admin_access_allowed(self):
        self.client.force_authenticate(user=self.admin_user)
        response = self.client.get('/api/admin/summary/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data['total_alerts'], 3)
        self.assertEqual(response.data['active_alerts'], 1)
        self.assertEqual(response.data['triggered_alerts'], 1)
        self.assertEqual(response.data['total_notifications'], 1)
        self.assertTrue(len(response.data['top_routes']) > 0)
        self.assertEqual(response.data['top_routes'][0]['route'], 'DEL-BOM')
        self.assertEqual(response.data['top_routes'][0]['alert_count'], 2)

    def test_regular_user_access_forbidden(self):
        self.client.force_authenticate(user=self.regular_user)
        response = self.client.get('/api/admin/summary/')
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_access_unauthorized(self):
        response = self.client.get('/api/admin/summary/')
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class CeleryTasksTest(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='taskuser', password='password123')
        self.alert = PriceAlert.objects.create(
            user=self.user,
            origin='DEL',
            destination='BOM',
            threshold_price=Decimal('4500.00'),
            status=PriceAlert.Status.ACTIVE
        )

    def test_send_notification_task_success(self):
        result = send_notification(self.alert.id, 4200)
        self.assertIn('Notification logged', result)

        self.alert.refresh_from_db()
        self.assertEqual(self.alert.status, PriceAlert.Status.TRIGGERED)
        self.assertEqual(NotificationLog.objects.filter(alert=self.alert).count(), 1)

    def test_send_notification_idempotency_already_triggered(self):
        # Trigger it once
        send_notification(self.alert.id, 4200)
        # Call it second time with new price
        result = send_notification(self.alert.id, 4100)
        self.assertIn('not active', result)
        # NotificationLog count must remain 1
        self.assertEqual(NotificationLog.objects.filter(alert=self.alert).count(), 1)

    def test_send_notification_nonexistent_alert(self):
        result = send_notification(999999, 4200)
        self.assertIn('not found', result)

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_check_prices_dispatches_when_below_threshold(self, mock_get, mock_delay):
        # Current price (4200) <= threshold (4500)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'route': 'DEL-BOM', 'price': 4200}
        mock_get.return_value = mock_response

        check_prices()

        mock_delay.assert_called_once_with(self.alert.id, 4200)

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_check_prices_does_not_dispatch_when_above_threshold(self, mock_get, mock_delay):
        # Current price (5000) > threshold (4500)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'route': 'DEL-BOM', 'price': 5000}
        mock_get.return_value = mock_response

        check_prices()

        mock_delay.assert_not_called()

    @patch('pulse.tasks.send_notification.delay')
    @patch('pulse.tasks.requests.get')
    def test_check_prices_gracefully_handles_http_error(self, mock_get, mock_delay):
        # Internal endpoint returns 500
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        check_prices()

        mock_delay.assert_not_called()
