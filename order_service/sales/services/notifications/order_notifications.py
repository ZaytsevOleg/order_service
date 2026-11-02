from django.conf import settings
from django.db import transaction

from sales.models import OrderNotification


def enqueue_order_notifications(order):
    """
    Создаёт уведомления после успешного проведения
    заказа в 1С. Повторный вызов не создаёт дубликаты.
    """

    manager = order.contract.manager

    recipients = [
        (
            OrderNotification.RECIPIENT_MANAGER,
            OrderNotification.CHANNEL_EMAIL,
            manager.email if manager else "",
        ),
        (
            OrderNotification.RECIPIENT_MANAGER,
            OrderNotification.CHANNEL_BITRIX,
            manager.bitrix_id if manager else "",
        ),
        (
            OrderNotification.RECIPIENT_OPERATOR,
            OrderNotification.CHANNEL_EMAIL,
            settings.ORDER_OPERATOR_EMAIL,
        ),
        (
            OrderNotification.RECIPIENT_OPERATOR,
            OrderNotification.CHANNEL_BITRIX,
            settings.ORDER_OPERATOR_BITRIX_ID,
        ),
    ]

    created_count = 0

    with transaction.atomic():
        for recipient_type, channel, recipient in recipients:
            recipient = str(recipient or "").strip()

            if not recipient:
                continue

            _, created = OrderNotification.objects.get_or_create(
                order=order,
                recipient_type=recipient_type,
                channel=channel,
                defaults={
                    "recipient": recipient,
                    "status": OrderNotification.STATUS_PENDING,
                },
            )

            if created:
                created_count += 1

    return created_count