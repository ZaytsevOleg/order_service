from decimal import Decimal
from uuid import UUID

import requests

from sales.services.onec_orders import (
    get_onec_connection,
)
from sales.services.onec_credentials import decrypt_password


class OneCShipmentError(Exception):
    pass


def get_onec_order_for_shipment(ref_key):
    """
    Получает проведённый заказ клиента из 1С.
    Только чтение, без создания документов.
    """

    try:
        ref_key = str(UUID(str(ref_key)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OneCShipmentError(
            "Некорректный Ref_Key заказа"
        ) from exc

    connection = get_onec_connection()

    url = (
        connection.base_url.rstrip("/")
        + f"/Document_ЗаказКлиента(guid'{ref_key}')"
    )

    try:
        response = requests.get(
            url,
            params={"$format": "json"},
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            headers={"Accept": "application/json"},
            timeout=connection.timeout,
        )
        response.raise_for_status()
        document = response.json()

    except (requests.RequestException, ValueError) as exc:
        raise OneCShipmentError(
            f"Ошибка получения заказа из 1С: {exc}"
        ) from exc

    if document.get("Posted") is not True:
        raise OneCShipmentError(
            "Нельзя создать реализацию: заказ не проведён"
        )

    if document.get("Согласован") is not True:
        raise OneCShipmentError(
            "Нельзя создать реализацию: заказ не согласован"
        )

    items = [
        item
        for item in document.get("Товары", [])
        if not item.get("Отменено", False)
    ]

    if not items:
        raise OneCShipmentError(
            "В заказе отсутствуют товары для отгрузки"
        )

    return document


def inspect_onec_order_for_shipment(ref_key):
    """
    Возвращает основные реквизиты и товарные строки
    для проверки будущей реализации.
    """

    order = get_onec_order_for_shipment(ref_key)

    items = [
        {
            "line": item.get("LineNumber"),
            "product": item.get("Номенклатура_Key"),
            "quantity": item.get("Количество"),
            "price": item.get("Цена"),
            "amount": item.get("СуммаСНДС"),
            "vat": item.get("СуммаНДС"),
            "warehouse": item.get("Склад_Key"),
            "link_key": item.get("КлючСвязи"),
        }
        for item in order.get("Товары", [])
        if not item.get("Отменено", False)
    ]

    total = sum(
        (
            Decimal(str(item["amount"]))
            for item in items
        ),
        Decimal("0"),
    )

    return {
        "order_ref": order["Ref_Key"],
        "order_number": order["Number"],
        "organization": order["Организация_Key"],
        "customer": order["Контрагент_Key"],
        "partner": order["Партнер_Key"],
        "contract": order["Договор_Key"],
        "warehouse": order["Склад_Key"],
        "document_amount": str(order["СуммаДокумента"]),
        "items_amount": str(total),
        "amount_matches": (
            total == Decimal(str(order["СуммаДокумента"]))
        ),
        "items_count": len(items),
        "items": items,
    }