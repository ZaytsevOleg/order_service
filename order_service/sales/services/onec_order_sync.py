import hashlib
import uuid
from contextlib import contextmanager
from datetime import datetime

from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from sales.models import Order, OrderLog
from sales.services.onec_orders import (
    create_onec_order,
    find_onec_order,
    OneCOrderError,
    post_onec_order
)


class OrderSyncError(Exception):
    pass


def lock_key(order_id):
    digest = hashlib.sha256(
        str(order_id).encode("utf-8")
    ).digest()

    return int.from_bytes(
        digest[:8],
        byteorder="big",
        signed=True,
    )


@contextmanager
def order_sync_lock(order_id):
    """
    PostgreSQL session-level advisory lock.

    Удерживается во время запроса к 1С.
    """
    key = lock_key(order_id)

    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_try_advisory_lock(%s)",
            [key],
        )
        acquired = cursor.fetchone()[0]

    if not acquired:
        raise OrderSyncError(
            "Этот заказ уже отправляется в 1С"
        )

    try:
        yield
    finally:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT pg_advisory_unlock(%s)",
                [key],
            )


def parse_onec_date(value):
    if not value:
        return None

    result = parse_datetime(value)

    if result is None:
        raise OrderSyncError(
            f"Некорректная дата документа 1С: {value}"
        )

    if timezone.is_naive(result):
        result = timezone.make_aware(
            result,
            timezone.get_current_timezone(),
        )

    return result


def save_onec_result(order, data):
    """
    Сохраняет подтверждённый результат обмена.
    """
    ref_key = data.get("Ref_Key") or data.get("ref_key")

    if not ref_key:
        raise OrderSyncError(
            "1С не вернула идентификатор документа"
        )

    with transaction.atomic():
        order = Order.objects.select_for_update().get(
            pk=order.pk
        )

        if order.one_c_order_id:
            if str(order.one_c_order_id) != str(ref_key):
                raise OrderSyncError(
                    "Заказ уже связан с другим документом 1С"
                )
            return order

        order.one_c_order_id = uuid.UUID(str(ref_key))
        order.number = data.get("Number") or data.get("number") or ""
        order.one_c_order_date = parse_onec_date(
            data.get("Date") or data.get("date")
        )
        order.sent_to_1c_at = timezone.now()

        order.save(update_fields=[
            "one_c_order_id",
            "number",
            "one_c_order_date",
            "sent_to_1c_at",
            "updated_at",
        ])

        OrderLog.objects.create(
            order=order,
            event_type=OrderLog.EVENT_1C_SUCCESS,
            level=OrderLog.LEVEL_SUCCESS,
            message="Заказ успешно связан с документом 1С",
            details={
                "ref_key": str(ref_key),
                "number": order.number,
            },
        )

    return order

def sync_order_to_onec(order_id):
    """
    Синхронизирует заказ Django с 1С.
    Создаёт документ при необходимости и проводит его.
    """
    with order_sync_lock(order_id):
        order = Order.objects.get(pk=order_id)

        if order.one_c_order_id:
            ref_key = str(order.one_c_order_id)

        else:
            existing = find_onec_order(order)

            if existing:
                order = save_onec_result(order, existing)
            else:
                result = create_onec_order(order)
                order = save_onec_result(order, result)

            ref_key = str(order.one_c_order_id)

        # Проводим заказ клиента.
        result = post_onec_order(ref_key)

        if not result.get("posted"):
            raise OrderSyncError(
                "1С не подтвердила проведение заказа клиента"
            )

        if order.onec_shipping_mode == Order.ONEC_MODE_RESERVE:
            # Пока только фиксируем завершение проведения.
            # Уведомление оператору подключим отдельно.
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)

                if order.status == Order.STATUS_DRAFT:
                    order.status = Order.STATUS_APPROVAL
                    order.save(update_fields=["status", "updated_at"])

        elif order.onec_shipping_mode == Order.ONEC_MODE_FULL_SHIPMENT:
            # Реализацию и счёт-фактуру добавим следующим этапом.
            # Статус 3 пока не устанавливаем.
            pass

        else:
            raise OrderSyncError(
                f"Неизвестный режим отправки: {order.onec_shipping_mode}"
            )

        return result

    