import logging
import requests
from celery import shared_task
from django.conf import settings
from .models import PriceAlert, NotificationLog

logger = logging.getLogger(__name__)


@shared_task(name='pulse.tasks.check_prices')
def check_prices():
    """
    Celery Beat scheduled task (runs every 60s).
    Wakes up, fetches current prices for all active alert routes via the internal
    flight price feed, and dispatches send_notification.delay() if threshold is hit.
    """
    active_alerts = PriceAlert.objects.filter(status=PriceAlert.Status.ACTIVE)
    routes = active_alerts.values_list('origin', 'destination').distinct()

    base_url = getattr(settings, 'PRICE_FEED_BASE_URL', 'http://127.0.0.1:8000').rstrip('/')
    endpoint = f"{base_url}/api/flights/price/"

    dispatched_count = 0

    for origin, destination in routes:
        route = f"{origin}-{destination}"
        try:
            response = requests.get(
                endpoint,
                params={'route': route},
                timeout=(3.0, 5.0)
            )
            if response.status_code != 200:
                logger.warning("Price feed returned status %s for route %s", response.status_code, route)
                continue

            current_price = response.json().get('price')
            if current_price is None:
                continue

            # Query all active alerts for this specific route
            route_alerts = active_alerts.filter(origin=origin, destination=destination)
            for alert in route_alerts:
                if float(current_price) <= float(alert.threshold_price):
                    # Fire asynchronously without blocking Beat or this worker loop
                    send_notification.delay(alert.id, current_price)
                    dispatched_count += 1
        except Exception as exc:
            logger.error("Failed to check price for route %s: %s", route, exc)
            continue

    return f"Checked {len(routes)} routes; dispatched {dispatched_count} notifications."


@shared_task(name='pulse.tasks.send_notification', acks_late=True)
def send_notification(alert_id, triggered_price):
    """
    Asynchronous notification task.
    Atomically creates a NotificationLog and marks the PriceAlert as TRIGGERED
    to prevent duplicate notification storms.
    """
    try:
        alert = PriceAlert.objects.get(id=alert_id)
    except PriceAlert.DoesNotExist:
        logger.error("PriceAlert id=%s does not exist.", alert_id)
        return f"Alert {alert_id} not found."

    # Idempotency guard: only notify if still ACTIVE
    if alert.status != PriceAlert.Status.ACTIVE:
        logger.info("PriceAlert id=%s is already %s. Skipping.", alert_id, alert.status)
        return f"Alert {alert_id} not active ({alert.status})."

    message = (
        f"Price alert triggered! {alert.origin}-{alert.destination} "
        f"is now ₹{triggered_price} - below your threshold of ₹{alert.threshold_price}"
    )

    NotificationLog.objects.create(
        alert=alert,
        triggered_price=triggered_price,
        message=message
    )

    # Mark as TRIGGERED so subsequent runs do not re-alert
    alert.status = PriceAlert.Status.TRIGGERED
    alert.save(update_fields=['status'])

    logger.info("Notification logged for alert %s at price %s", alert_id, triggered_price)
    return f"Notification logged for alert {alert_id} at price {triggered_price}."

