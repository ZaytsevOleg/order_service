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
        order.status = 3

        order.save(update_fields=[
            "one_c_order_id",
            "number",
            "one_c_order_date",
            "sent_to_1c_at",
            "status",
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
    Синхронизирует один заказ Django с 1С.
    """
    with order_sync_lock(order_id):
        order = Order.objects.get(pk=order_id)

        if order.one_c_order_id:
            raise OrderSyncError(
                "Заказ уже отправлен в 1С"
            )

        # Проверяем, не был ли документ создан
        # при предыдущей попытке отправки.
        existing = find_onec_order(order)

        if existing:
            return save_onec_result(order, existing)

        # Создаём новый документ.
        result = create_onec_order(order)

        return save_onec_result(order, result)