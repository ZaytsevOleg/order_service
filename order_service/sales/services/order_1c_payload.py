
from decimal import Decimal
from uuid import UUID

from sales.models import Order, OrderItem


ZERO_GUID = "00000000-0000-0000-0000-000000000000"


class OrderPayloadError(ValueError):
    pass


def guid(value, field_name):
    """Проверяет и нормализует GUID объекта 1С."""
    if not value:
        raise OrderPayloadError(
            f"Не заполнено поле: {field_name}"
        )

    try:
        result = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise OrderPayloadError(
            f"Некорректный GUID в поле {field_name}: {value}"
        )

    if result == ZERO_GUID:
        raise OrderPayloadError(
            f"Пустой GUID в поле {field_name}"
        )

    return result


def money(value):
    """Преобразует Decimal в JSON-совместимое число."""
    return float(Decimal(str(value)).quantize(Decimal("0.01")))


def build_order_payload(order):
    """
    Формирует предварительную структуру
    Document_ЗаказКлиента для OData 1С УТ 11.5.

    Документ не отправляется в 1С.
    """

    if not order.customer_id:
        raise OrderPayloadError("Не выбран контрагент")

    if not order.contract_id:
        raise OrderPayloadError("Не выбран договор")

    if not order.shipping_date:
        raise OrderPayloadError("Не указана дата отгрузки")

    customer = order.customer
    contract = order.contract

    if contract.legal_entity_id != order.customer_id:
        raise OrderPayloadError(
            "Договор не соответствует контрагенту"
        )

    if not contract.manager_id:
        raise OrderPayloadError(
            "В договоре не указан менеджер"
        )

    if not contract.agreement_id:
        raise OrderPayloadError(
            "В договоре не указано соглашение"
        )

    items = list(
        OrderItem.objects.filter(order=order)
        .select_related("product")
        .order_by("line_number", "id")
    )

    if not items:
        raise OrderPayloadError("В заказе нет товаров")

    shipping_date = (
        order.shipping_date.isoformat() + "T00:00:00"
    )

    products = []

    for index, item in enumerate(items, start=1):
        if not item.product_id:
            raise OrderPayloadError(
                f"Не указана номенклатура в строке {index}"
            )

        if item.quantity <= 0:
            raise OrderPayloadError(
                f"Некорректное количество в строке {index}"
            )

        products.append({
            "LineNumber": str(index),
            "Номенклатура_Key": guid(
                item.product.product_id,
                f"Товар {index}"
            ),
            "Количество": float(item.quantity),
            "Цена": money(item.price),
            "Сумма": money(item.amount),
            "ДатаОтгрузки": shipping_date,
            "Отменено": False,
        })

    payload = {
        "Posted": False,
        "Партнер_Key": guid(
            customer.partner_id, "Партнёр"
        ),
        "Контрагент_Key": guid(
            customer.legal_entity_id, "Контрагент"
        ),
        "Договор_Key": guid(
            contract.contract_id, "Договор"
        ),
        "Организация_Key": guid(
            contract.organization_id, "Организация"
        ),
        "Менеджер_Key": guid(
            contract.manager.manager_id, "Менеджер"
        ),
        "Соглашение_Key": guid(
            contract.agreement.agreement_id, "Соглашение"
        ),
        "ДатаОтгрузки": shipping_date,
        "Комментарий": order.comment or "",
        "Товары": products,
    }

    return payload
