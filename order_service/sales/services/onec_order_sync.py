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
import logging

from sales.services.notifications.order_notifications import (
    enqueue_order_notifications,
)
from sales.services.notifications.processor import (
    process_order_notifications,
)
from sales.services.onec_shipments import (
    find_onec_shipments,
    create_onec_shipment,
    post_onec_shipment,
)

from sales.services.onec_invoices import (
    find_onec_invoices,
    create_onec_invoice,
    post_onec_invoice,
)

logger = logging.getLogger(__name__)

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

            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)

                if order.status == Order.STATUS_DRAFT:
                    order.status = Order.STATUS_APPROVAL
                    order.save(update_fields=["status", "updated_at"])

            # Документ успешно проведён в 1С.
            # Создаём задания для отправки уведомлений.
            try:
                order = Order.objects.select_related(
                    "contract__manager"
                ).get(pk=order_id)

                created_count = enqueue_order_notifications(order)

                logger.info(
                    "Заказ %s: создано уведомлений %s",
                    order.number,
                    created_count,
                )

                processed_count = process_order_notifications(
                    order_id=order.pk,
                    limit=4,
                )

                logger.info(
                    "Заказ %s: обработано уведомлений %s",
                    order.number,
                    processed_count,
                )

            except Exception:
                # Ошибка очереди не должна превращать
                # успешное проведение документа в ошибку синхронизации.
                logger.exception(
                    "Не удалось создать уведомления для заказа %s",
                    order_id,
                )

        elif order.onec_shipping_mode == Order.ONEC_MODE_FULL_SHIPMENT:

            # 1. Ищем существующие реализации
            shipments = find_onec_shipments(ref_key)

            active_shipments = [
                shipment
                for shipment in shipments
                if not shipment.get("DeletionMark")
            ]

            if len(active_shipments) > 1:
                raise OrderSyncError(
                    "В 1С найдено несколько действующих реализаций "
                    f"по заказу {ref_key}"
                )

            if active_shipments:
                shipment_ref = active_shipments[0]["Ref_Key"]

                logger.info(
                    "Заказ %s: найдена реализация %s",
                    order.number,
                    shipment_ref,
                )

            else:
                # 2. Создаём реализацию
                shipment = create_onec_shipment(ref_key)

                shipment_ref = shipment["ref_key"]

                logger.info(
                    "Заказ %s: создана реализация %s",
                    order.number,
                    shipment_ref,
                )

            # 3. Проводим реализацию
            shipment_result = post_onec_shipment(shipment_ref)

            if not shipment_result.get("posted"):
                raise OrderSyncError(
                    "1С не подтвердила проведение реализации"
                )

            logger.info(
                "Заказ %s: реализация %s проведена",
                order.number,
                shipment_ref,
            )

            # Статус 3 пока не устанавливаем.
            # 4. Ищем существующие счета-фактуры
            invoices = find_onec_invoices(shipment_ref)

            active_invoices = [
                invoice
                for invoice in invoices
                if not invoice.get("DeletionMark")
            ]

            if len(active_invoices) > 1:
                raise OrderSyncError(
                    "В 1С найдено несколько действующих счетов-фактур "
                    f"по реализации {shipment_ref}"
                )

            if active_invoices:
                invoice_ref = active_invoices[0]["Ref_Key"]

                logger.info(
                    "Заказ %s: найден счёт-фактура %s",
                    order.number,
                    invoice_ref,
                )

            else:
                # 5. Создаём счёт-фактуру
                invoice_result = create_onec_invoice(shipment_ref)
                invoice_ref = invoice_result["ref_key"]

                logger.info(
                    "Заказ %s: создан счёт-фактура %s",
                    order.number,
                    invoice_ref,
                )

            # 6. Проводим счёт-фактуру
            invoice_result = post_onec_invoice(invoice_ref)

            if not invoice_result.get("posted"):
                raise OrderSyncError(
                    "1С не подтвердила проведение счёта-фактуры"
                )

            logger.info(
                "Заказ %s: счёт-фактура %s проведён",
                order.number,
                invoice_ref,
            )

            # 7. Все три документа успешно проведены.
            # Устанавливаем статус 3 — Оформлен.
            with transaction.atomic():
                order = Order.objects.select_for_update().get(pk=order_id)

                if order.status in (
                    Order.STATUS_DRAFT,
                    Order.STATUS_APPROVAL,
                ):
                    order.status = Order.STATUS_CONFIRMED
                    order.save(update_fields=["status", "updated_at"])

            logger.info(
                "Заказ %s: full_shipment завершён, статус %s",
                order.number,
                order.status,
            )

            # 8. Уведомления менеджеру и оператору.
            try:
                order = Order.objects.select_related(
                    "contract__manager"
                ).get(pk=order_id)

                created_count = enqueue_order_notifications(order)

                logger.info(
                    "Заказ %s: создано уведомлений %s",
                    order.number,
                    created_count,
                )

                processed_count = process_order_notifications(
                    order_id=order.pk,
                    limit=4,
                )

                logger.info(
                    "Заказ %s: обработано уведомлений %s",
                    order.number,
                    processed_count,
                )

            except Exception:
                # Ошибка уведомлений не отменяет успешное
                # создание документов в 1С.
                logger.exception(
                    "Не удалось отправить уведомления для заказа %s",
                    order_id,
                )

        else:
            raise OrderSyncError(
                f"Неизвестный режим отправки: {order.onec_shipping_mode}"
            )

        return Order.objects.get(pk=order_id)

    