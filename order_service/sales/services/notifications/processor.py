import logging
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from sales.models import OrderNotification
from sales.services.notifications.email_sender import send_email
from sales.services.notifications.bitrix_sender import send_bitrix_message


logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
RETRY_DELAY_MINUTES = 5
PROCESSING_TIMEOUT_MINUTES = 10


def claim_notification():
    """Атомарно забирает одно доступное уведомление."""

    now = timezone.now()

    retry_before = now - timedelta(
        minutes=RETRY_DELAY_MINUTES
    )
    processing_before = now - timedelta(
        minutes=PROCESSING_TIMEOUT_MINUTES
    )

    with transaction.atomic():
        notification = (
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
            .order_by("created_at", "pk")
            .first()
        )

        if notification is None:
            return None

        notification.status = OrderNotification.STATUS_PROCESSING
        notification.processing_started_at = now
        notification.attempts += 1

        notification.save(
            update_fields=[
                "status",
                "processing_started_at",
                "attempts",
            ]
        )

        return notification.pk


def build_notification_message(notification):
    order = notification.order

    subject = f"Новый заказ {order.number}"

    text = (
        f"Новый заказ клиента: {order.number}\n"
        f"Заказ успешно проведён в 1С.\n"
        f"Статус: На согласовании.\n"
    )

    return subject, text


def process_one_notification():
    notification_id = claim_notification()

    if notification_id is None:
        return False

    notification = (
        OrderNotification.objects
        .select_related("order")
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
            raise ValueError(
                f"Неизвестный канал: {notification.channel}"
            )

    except Exception as exc:
        logger.exception(
            "Ошибка уведомления ID=%s",
            notification.pk,
        )

        OrderNotification.objects.filter(
            pk=notification.pk,
            status=OrderNotification.STATUS_PROCESSING,
        ).update(
            status=OrderNotification.STATUS_FAILED,
            last_error=str(exc)[:2000],
            processing_started_at=timezone.now(),
        )

    else:
        OrderNotification.objects.filter(
            pk=notification.pk,
            status=OrderNotification.STATUS_PROCESSING,
        ).update(
            status=OrderNotification.STATUS_SENT,
            sent_at=timezone.now(),
            last_error="",
            processing_started_at=None,
        )

        logger.info(
            "Уведомление ID=%s отправлено",
            notification.pk,
        )

    return True


def process_order_notifications(limit=20):
    processed = 0

    for _ in range(limit):
        if not process_one_notification():
            break

        processed += 1

    return processed