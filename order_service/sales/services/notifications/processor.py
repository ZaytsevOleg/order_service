import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import OrderNotification, OrderLog
from sales.services.notifications.email_sender import send_email
from sales.services.notifications.bitrix_sender import send_bitrix_message

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_MINUTES = 5
PROCESSING_TIMEOUT_MINUTES = 10


def claim_notification(order_id=None):
    """Забрать одно доступное уведомление, при необходимости только данного заказа."""
    now = timezone.now()
    retry_before = now - timedelta(minutes=RETRY_DELAY_MINUTES)
    processing_before = now - timedelta(minutes=PROCESSING_TIMEOUT_MINUTES)

    with transaction.atomic():
        queryset = (
            OrderNotification.objects
            .select_for_update(skip_locked=True)
            .filter(attempts__lt=MAX_ATTEMPTS)
            .filter(
                Q(status=OrderNotification.STATUS_PENDING)
                | Q(
                    status=OrderNotification.STATUS_FAILED,
                    processing_started_at__lte=retry_before,
                )
                | Q(
                    status=OrderNotification.STATUS_PROCESSING,
                    processing_started_at__lt=processing_before,
                )
            )
        )
        if order_id is not None:
            queryset = queryset.filter(order_id=order_id)

        notification = queryset.order_by("created_at", "pk").first()
        if notification is None:
            return None

        notification.status = OrderNotification.STATUS_PROCESSING
        notification.processing_started_at = now
        notification.attempts += 1
        notification.save(update_fields=[
            "status", "processing_started_at", "attempts",
        ])
        return notification.pk, notification.attempts


def build_notification_message(notification):
    order = notification.order
    subject = f"Новый заказ {order.number}"
    message = (
        f"Новый заказ клиента: {order.number}\n"
        "Заказ успешно проведён в 1С.\n"
        "Статус: На согласовании.\n"
    )
    return subject, message


def _record_result(notification, claimed_attempt, error=None):
    """Сохранить итог и журнал атомарно; не перезаписать более новую попытку."""
    with transaction.atomic():
        current = (
            OrderNotification.objects.select_for_update()
            .get(pk=notification.pk)
        )
        if (
            current.status != OrderNotification.STATUS_PROCESSING
            or current.attempts != claimed_attempt
        ):
            logger.warning(
                "Уведомление ID=%s уже обработано другой попыткой",
                notification.pk,
            )
            return

        if error is None:
            current.status = OrderNotification.STATUS_SENT
            current.sent_at = timezone.now()
            current.last_error = ""
            current.processing_started_at = None
            event_type = OrderLog.EVENT_NOTIFICATION_SENT
            level = OrderLog.LEVEL_SUCCESS
            message = "Уведомление отправлено"
        else:
            current.status = OrderNotification.STATUS_FAILED
            current.last_error = str(error)[:2000]
            current.processing_started_at = timezone.now()
            event_type = OrderLog.EVENT_NOTIFICATION_ERROR
            level = OrderLog.LEVEL_ERROR
            message = "Ошибка отправки уведомления"

        current.save(update_fields=[
            "status", "sent_at", "last_error", "processing_started_at",
        ])
        details = {
            "notification_id": current.pk,
            "recipient_type": current.recipient_type,
            "channel": current.channel,
            "attempts": current.attempts,
        }
        if error is not None:
            details["error"] = str(error)[:2000]

        OrderLog.objects.create(
            order=current.order,
            event_type=event_type,
            level=level,
            message=(
                f"{message}: {current.get_recipient_type_display()}, "
                f"{current.get_channel_display()}"
            ),
            details=details,
        )


def process_one_notification(order_id=None):
    claimed = claim_notification(order_id=order_id)
    if claimed is None:
        return False

    notification_id, claimed_attempt = claimed
    notification = (
        OrderNotification.objects.select_related("order")
        .get(pk=notification_id)
    )

    try:
        subject, message = build_notification_message(notification)
        if notification.channel == OrderNotification.CHANNEL_EMAIL:
            send_email(
                to_email=notification.recipient,
                subject=subject,
                text=message,
            )
        elif notification.channel == OrderNotification.CHANNEL_BITRIX:
            send_bitrix_message(
                user_id=notification.recipient,
                text=message,
            )
        else:
            raise ValueError(f"Неизвестный канал: {notification.channel}")
    except Exception as exc:
        logger.exception("Ошибка уведомления ID=%s", notification.pk)
        _record_result(notification, claimed_attempt, error=exc)
    else:
        _record_result(notification, claimed_attempt)
        logger.info("Уведомление ID=%s отправлено", notification.pk)

    return True


def process_order_notifications(limit=20, order_id=None):
    if limit < 1:
        return 0

    processed = 0
    for _ in range(limit):
        if not process_one_notification(order_id=order_id):
            break
        processed += 1
    return processed
