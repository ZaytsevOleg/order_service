from datetime import timedelta

from django.utils import timezone

from sales.models import (
    ShippingSettings,
    WorkCalendarException,
)


def get_shipping_settings():
    settings = ShippingSettings.objects.first()

    if settings is None:
        raise RuntimeError(
            "Не заполнены настройки отгрузки."
        )

    return settings


def is_working_day(check_date):
    """
    Определяет, является ли дата рабочим днём.

    Приоритет:
    1. Явное исключение в производственном календаре.
    2. Пн-Пт — рабочие.
    3. Сб-Вс — нерабочие.
    """

    exception = (
        WorkCalendarException.objects
        .filter(date=check_date)
        .first()
    )

    if exception:
        return (
            exception.day_type
            == WorkCalendarException.DAY_TYPE_WORKING
        )

    return check_date.weekday() < 5


def next_working_day(check_date):
    """
    Возвращает следующий рабочий день,
    не включая переданную дату.
    """

    current_date = check_date

    while True:
        current_date += timedelta(days=1)

        if is_working_day(current_date):
            return current_date


def add_working_days(start_date, days):
    """
    Добавляет указанное количество рабочих дней.

    start_date не считается первым добавленным днём.
    """

    current_date = start_date
    added_days = 0

    while added_days < days:
        current_date += timedelta(days=1)

        if is_working_day(current_date):
            added_days += 1

    return current_date


def get_delivery_min_date(
    current_datetime=None,
):
    settings = get_shipping_settings()

    if current_datetime is None:
        current_datetime = timezone.localtime()

    current_date = current_datetime.date()
    current_time = current_datetime.time()

    # Заказ оформлен в нерабочий день.
    if not is_working_day(current_date):
        base_date = next_working_day(
            current_date
        )

    # Заказ оформлен после времени отсечения.
    elif (
        current_time
        >= settings.delivery_cutoff_time
    ):
        base_date = next_working_day(
            current_date
        )

    else:
        base_date = current_date

    return add_working_days(
        base_date,
        settings.delivery_working_days,
    )


def get_pickup_min_date(
    current_datetime=None,
):
    settings = get_shipping_settings()

    if current_datetime is None:
        current_datetime = timezone.localtime()

    current_date = current_datetime.date()
    current_time = current_datetime.time()

    # В нерабочий день самовывоз невозможен.
    if not is_working_day(current_date):
        return next_working_day(
            current_date
        )

    # Самовывоз в день заказа отключён.
    if not settings.pickup_same_day_enabled:
        return next_working_day(
            current_date
        )

    # До времени отсечения можно забрать сегодня.
    if (
        current_time
        < settings.pickup_same_day_cutoff
    ):
        return current_date

    # После времени отсечения —
    # следующий рабочий день.
    return next_working_day(
        current_date
    )


def get_min_shipping_date(
    shipping_type,
    current_datetime=None,
):
    if shipping_type == "delivery":
        return get_delivery_min_date(
            current_datetime=current_datetime,
        )

    if shipping_type == "pickup":
        return get_pickup_min_date(
            current_datetime=current_datetime,
        )

    raise ValueError(
        "Неизвестный способ отгрузки."
    )