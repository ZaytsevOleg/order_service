from sales.models import OrderLog


def log_order_event(
    *,
    order,
    event_type,
    message,
    level=OrderLog.LEVEL_INFO,
    user=None,
    details=None,
):

    return OrderLog.objects.create(
        order=order,
        event_type=event_type,
        level=level,
        message=message,
        user=user,
        details=details or {},
    )