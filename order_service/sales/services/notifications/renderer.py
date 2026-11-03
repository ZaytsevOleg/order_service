from django.template.loader import render_to_string

from sales.models import Order


def render_order_notification(notification):
    order = notification.order

    if order.onec_shipping_mode not in (
        Order.ONEC_MODE_RESERVE,
        Order.ONEC_MODE_FULL_SHIPMENT,
    ):
        raise ValueError(
            f"Неизвестный режим заказа: {order.onec_shipping_mode}"
        )

    if notification.recipient_type not in ("manager", "operator"):
        raise ValueError(
            f"Неизвестный получатель: {notification.recipient_type}"
        )

    template_name = (
        "sales/notifications/"
        f"{order.onec_shipping_mode}/"
        f"{notification.recipient_type}.txt"
    )

    subject = f"Заказ клиента № {order.number}"

    message = render_to_string(
        template_name,
        {"order": order},
    ).strip()

    return subject, message