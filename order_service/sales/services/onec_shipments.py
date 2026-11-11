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


from datetime import datetime
from decimal import Decimal


def build_shipment_payload(order):
    """
    Формирует JSON реализации на основании заказа 1С.
    Не выполняет запросов на создание документа.
    """

    if order.get("Posted") is not True:
        raise OneCShipmentError("Заказ не проведён")

    if order.get("Согласован") is not True:
        raise OneCShipmentError("Заказ не согласован")

    if order.get("Статус") != "КОтгрузке":
        raise OneCShipmentError(
            f"Некорректный статус заказа: {order.get('Статус')}"
        )

    order_ref = order["Ref_Key"]

    # Для документа используем текущую дату.
    document_date = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    shipping_date = datetime.fromisoformat(
        order["ДатаОтгрузки"]
    ).strftime("%d.%m.%Y")

    comment = (
        f"Отгрузка: {shipping_date} "
        f"{order.get('Комментарий', '')}"
    ).strip()

    items = []

    for item in order["Товары"]:
        if item.get("Отменено", False):
            continue

        if item.get("ВариантОбеспечения") != "Отгрузить":
            raise OneCShipmentError(
                f"Строка {item['LineNumber']} не предназначена "
                "для отгрузки"
            )

        shipment_item = {
            "LineNumber": item["LineNumber"],
            "Номенклатура_Key": item["Номенклатура_Key"],
            "Характеристика_Key": item["Характеристика_Key"],
            "Упаковка_Key": item["Упаковка_Key"],
            "Количество": item["Количество"],
            "КоличествоУпаковок": item["КоличествоУпаковок"],
            "ВидЦены_Key": item["ВидЦены_Key"],
            "Цена": item["Цена"],
            "Сумма": item["Сумма"],
            "СуммаСНДС": item["СуммаСНДС"],
            "СтавкаНДС_Key": item["СтавкаНДС_Key"],
            "СуммаНДС": item["СуммаНДС"],
            "КодСтроки": item["КодСтроки"],
            "КлючСвязи": item["КлючСвязи"],
            "СуммаРучнойСкидки": item["СуммаРучнойСкидки"],
            "СуммаАвтоматическойСкидки": item[
                "СуммаАвтоматическойСкидки"
            ],
            "ПроцентРучнойСкидки": item[
                "ПроцентРучнойСкидки"
            ],
            "ПроцентАвтоматическойСкидки": item[
                "ПроцентАвтоматическойСкидки"
            ],
            "Склад_Key": item["Склад_Key"],
            "ЗаказКлиента": order_ref,
            "ЗаказКлиента_Type": (
                "StandardODATA.Document_ЗаказКлиента"
            ),
            "СуммаВзаиморасчетов": item["СуммаСНДС"],
        }

        items.append(shipment_item)

    items_amount = sum(
        (Decimal(str(item["СуммаСНДС"])) for item in items),
        Decimal("0"),
    )

    document_amount = Decimal(str(order["СуммаДокумента"]))

    if items_amount != document_amount:
        raise OneCShipmentError(
            "Сумма товарных строк не совпадает с суммой заказа"
        )

    payload = {
        "Date": document_date,
        "Posted": False,
        "ЗаказКлиента": order_ref,
        "ЗаказКлиента_Type": (
            "StandardODATA.Document_ЗаказКлиента"
        ),
        "РеализацияПоЗаказам": True,
        "Организация_Key": order["Организация_Key"],
        "Контрагент_Key": order["Контрагент_Key"],
        "Партнер_Key": order["Партнер_Key"],
        "Договор_Key": order["Договор_Key"],
        "Соглашение_Key": order["Соглашение_Key"],
        "Менеджер_Key": order["Менеджер_Key"],
        "Подразделение_Key": order["Подразделение_Key"],
        "Склад_Key": order["Склад_Key"],
        "Валюта_Key": order["Валюта_Key"],
        "ВалютаВзаиморасчетов_Key": order["Валюта_Key"],
        "ХозяйственнаяОперация": order["ХозяйственнаяОперация"],
        "НалогообложениеНДС": order["НалогообложениеНДС"],
        "ЦенаВключаетНДС": order["ЦенаВключаетНДС"],
        "СкидкиРассчитаны": True,
        "СуммаДокумента": float(document_amount),
        "СуммаВзаиморасчетов": float(document_amount),
        "ПорядокРасчетов": order["ПорядокРасчетов"],
        "СпособДоставки": order["СпособДоставки"],
        "АдресДоставки": order.get("АдресДоставки", ""),
        "Комментарий": comment,
        "Статус": "Отгружено",
        "Товары": items,
    }

    return payload

def find_onec_shipments(order_ref):
    """
    Поиск реализаций по заказу клиента через OData.
    Фильтрация выполняется на стороне 1С.
    Только GET.
    """
    from uuid import UUID

    try:
        order_ref = str(UUID(str(order_ref)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OneCShipmentError(
            "Некорректный Ref_Key заказа"
        ) from exc

    connection = get_onec_connection()

    url = (
        connection.base_url.rstrip("/")
        + "/Document_РеализацияТоваровУслуг"
        + "?&$format=json"
        + "&$filter=ЗаказКлиента eq "
        + f"cast(guid'{order_ref}','Document_ЗаказКлиента')"
    )

    try:
        response = requests.get(
            url,
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            headers={"Accept": "application/json"},
            timeout=connection.timeout,
        )

        if not response.ok:
            raise OneCShipmentError(
                f"Ошибка поиска реализаций "
                f"HTTP {response.status_code}: "
                f"{response.text[:1500]}"
            )

        data = response.json()
        documents = data.get("value", [])

    except (requests.RequestException, ValueError) as exc:
        raise OneCShipmentError(
            f"Ошибка поиска реализаций: {exc}"
        ) from exc

    for document in documents:
        if (
            str(document.get("ЗаказКлиента", "")).lower()
            != order_ref
            or document.get("ЗаказКлиента_Type")
            != "StandardODATA.Document_ЗаказКлиента"
        ):
            raise OneCShipmentError(
                "1С вернула реализацию другого заказа"
            )

    if data.get("odata.nextLink") or data.get("@odata.nextLink"):
        raise OneCShipmentError(
            "Результат поиска неполный: обнаружена следующая страница OData"
        )

    return documents


def create_onec_shipment(order_ref):
    """
    Создаёт непроведённую реализацию по заказу клиента.

    ВНИМАНИЕ: выполняет реальный POST в 1С.
    """

    # Проверяем, не существует ли реализация.
    existing = find_onec_shipments(order_ref)

    if existing:
        raise OneCShipmentError(
            "По заказу уже существует реализация: "
            + ", ".join(
                doc.get("Number", doc["Ref_Key"])
                for doc in existing
            )
        )

    # Получаем заказ из 1С.
    order = get_onec_order_for_shipment(order_ref)

    # Формируем документ.
    payload = build_shipment_payload(order)

    connection = get_onec_connection()

    url = (
        connection.base_url.rstrip("/")
        + "/Document_РеализацияТоваровУслуг"
    )

    try:
        response = requests.post(
            url,
            json=payload,
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=connection.timeout,
        )

    except requests.RequestException as exc:
        raise OneCShipmentError(
            "Не удалось получить подтверждение создания реализации. "
            "Перед повторной отправкой необходимо проверить "
            "существование документа в 1С."
        ) from exc

    if not response.ok:
        raise OneCShipmentError(
            f"Ошибка создания реализации "
            f"HTTP {response.status_code}: "
            f"{response.text[:2000]}"
        )

    try:
        data = response.json()
        ref_key = data["Ref_Key"]

    except (ValueError, KeyError, TypeError) as exc:
        raise OneCShipmentError(
            "1С ответила успешно, но не вернула Ref_Key. "
            "Необходимо проверить документ в 1С."
        ) from exc

    if (
        str(data.get("ЗаказКлиента", "")).lower()
        != str(order_ref).lower()
    ):
        raise OneCShipmentError(
            "Созданная реализация ссылается на другой заказ. "
            "Требуется проверка в 1С."
        )

    return {
        "ref_key": ref_key,
        "number": data.get("Number"),
        "posted": data.get("Posted"),
        "status": data.get("Статус"),
        "amount": data.get("СуммаДокумента"),
        "items_count": len(data.get("Товары", [])),
        "stock_types_count": len(data.get("ВидыЗапасов", [])),
        "payment_schedule_count": len(
            data.get("ЭтапыГрафикаОплаты", [])
        ),
    }