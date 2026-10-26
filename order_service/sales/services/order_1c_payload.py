from collections import defaultdict
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import UUID

from sales.models import OrderItem

ZERO_GUID = "00000000-0000-0000-0000-000000000000"
CENT = Decimal("0.01")
HUNDRED = Decimal("100")
GIFT_DISCOUNT = Decimal("99")


class OrderPayloadError(ValueError):
    pass


def guid(value, field_name):
    if not value:
        raise OrderPayloadError(f"Не заполнено поле: {field_name}")
    try:
        result = str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OrderPayloadError(
            f"Некорректный GUID в поле {field_name}: {value}"
        ) from exc
    if result == ZERO_GUID:
        raise OrderPayloadError(f"Пустой GUID в поле {field_name}")
    return result


def decimal_value(value, field_name):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise OrderPayloadError(f"Некорректное число в поле {field_name}: {value}") from exc
    if not result.is_finite():
        raise OrderPayloadError(f"Некорректное число в поле {field_name}: {value}")
    return result


def cents(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def money(value):
    return float(cents(decimal_value(value, "Сумма")))


def build_order_payload(order):
    """Предварительный OData payload. Никаких запросов в 1С не выполняет."""
    if not order.customer_id:
        raise OrderPayloadError("Не выбран контрагент")
    if not order.contract_id:
        raise OrderPayloadError("Не выбран договор")
    if not order.shipping_date:
        raise OrderPayloadError("Не указана дата отгрузки")

    customer = order.customer
    contract = order.contract
    if contract.legal_entity_id != order.customer_id:
        raise OrderPayloadError("Договор не соответствует контрагенту")
    if not contract.manager_id:
        raise OrderPayloadError("В договоре не указан менеджер")
    if not contract.agreement_id:
        raise OrderPayloadError("В договоре не указано соглашение")

    items = list(
        OrderItem.objects.filter(order=order)
        .select_related("product")
        .order_by("line_number", "id")
    )
    if not items:
        raise OrderPayloadError("В заказе нет товаров")

    shipping_date = order.shipping_date.isoformat() + "T00:00:00"
    rows = []
    paid_by_promo = defaultdict(list)
    gift_compensation = defaultdict(lambda: Decimal("0.00"))
    django_total = Decimal("0.00")

    for index, item in enumerate(items, start=1):
        if not item.product_id:
            raise OrderPayloadError(f"Не указана номенклатура в строке {index}")
        quantity = decimal_value(item.quantity, f"Количество строки {index}")
        if quantity <= 0:
            raise OrderPayloadError(f"Некорректное количество в строке {index}")
        if item.base_price is None:
            raise OrderPayloadError(
                f"Не сохранена базовая цена товара {item.article or index}. "
                "Пересохраните состав заказа."
            )
        base_price = cents(decimal_value(item.base_price, f"Базовая цена строки {index}"))
        if base_price <= 0:
            raise OrderPayloadError(f"Неположительная базовая цена строки {index}")
        base_total = cents(base_price * quantity)
        customer_amount = cents(decimal_value(item.amount, f"Сумма строки {index}"))
        if customer_amount < 0:
            raise OrderPayloadError(f"Отрицательная сумма строки {index}")
        django_total += customer_amount

        is_gift = bool(item.is_promo_gift)
        is_paid_promo = bool(item.is_promo_product)
        if is_gift and is_paid_promo:
            raise OrderPayloadError(f"Строка {index} одновременно товар и подарок")
        if (is_gift or is_paid_promo) and not item.promo_id:
            raise OrderPayloadError(f"У промо-строки {index} отсутствует promo_id")

        if is_gift:
            if customer_amount != 0:
                raise OrderPayloadError(f"Подарок в строке {index} имеет ненулевую сумму Django")
            discount = cents(base_total * GIFT_DISCOUNT / HUNDRED)
            final_amount = base_total - discount
            if final_amount <= 0:
                raise OrderPayloadError(
                    f"Подарок в строке {index} после скидки 99% имеет нулевую сумму"
                )
            gift_compensation[str(item.promo_id)] += final_amount
        else:
            final_amount = customer_amount
            if final_amount <= 0 or final_amount > base_total:
                raise OrderPayloadError(
                    f"Некорректная стоимость платного товара в строке {index}"
                )
            if is_paid_promo:
                paid_by_promo[str(item.promo_id)].append(len(rows))

        raw_percent = GIFT_DISCOUNT if is_gift else decimal_value(
            item.discount_percent, f"Процент скидки строки {index}"
        )
        if raw_percent != raw_percent.to_integral_value():
            raise OrderPayloadError(
                f"Процент скидки в строке {index} должен быть целым: {raw_percent}"
            )
        if raw_percent < 0 or raw_percent > 100:
            raise OrderPayloadError(f"Некорректный процент скидки строки {index}")
        if is_paid_promo and not is_gift and raw_percent == 100:
            raise OrderPayloadError(f"Платный промо-товар {index} имеет скидку 100%")

        rows.append({
            "percent": int(raw_percent),
            "original_amount": customer_amount,
            "index": index,
            "item": item,
            "quantity": quantity,
            "base_price": base_price,
            "base_total": base_total,
            "final_amount": final_amount,
            "is_gift": is_gift,
        })

    for promo_id, compensation in gift_compensation.items():
        paid_indices = paid_by_promo.get(promo_id, [])
        if not paid_indices:
            raise OrderPayloadError(
                f"Для подарков промо {promo_id} нет платных промо-товаров"
            )
        # Компенсацию распределяем только между платными строками этой акции.
        # Оставляем не менее 0.01 руб. итоговой суммы в каждой строке.
        remaining = compensation
        for row_index in paid_indices:
            row = rows[row_index]
            capacity = row["final_amount"] - CENT
            if capacity <= 0:
                continue
            take = min(capacity, remaining)
            row["final_amount"] -= take
            remaining -= take
            if remaining == 0:
                break
        if remaining != 0:
            raise OrderPayloadError(
                f"Недостаточная стоимость платных товаров промо {promo_id} "
                f"для компенсации подарков ({compensation} руб.)"
            )

    products = []
    exported_total = Decimal("0.00")
    for row in rows:
        base_total = row["base_total"]
        final_amount = row["final_amount"]
        # Ручная скидка — только исходная скидка строки, без компенсации подарка.
        # Компенсация уже учтена исключительно в поле "Сумма".
        discount = (
            cents(base_total * GIFT_DISCOUNT / HUNDRED)
            if row["is_gift"]
            else base_total - row["original_amount"]
        )
        if final_amount <= 0 or discount < 0:
            raise OrderPayloadError(f"Некорректная сумма после скидки в строке {row['index']}")
        percent = row["percent"]
        exported_total += final_amount
        products.append({
            "LineNumber": row["index"],
            "Номенклатура_Key": guid(
                row["item"].product.product_id, f"Товар {row['index']}"
            ),
            "Количество": float(row["quantity"]),
            "Цена": money(row["base_price"]),
            "ПроцентРучнойСкидки": percent,
            "СуммаРучнойСкидки": money(discount),
            "Сумма": money(final_amount),
            "ДатаОтгрузки": shipping_date,
            "Отменено": False,
        })

    if exported_total != django_total:
        raise OrderPayloadError(
            f"Не совпадают суммы: Django {django_total}, 1С {exported_total}"
        )
    order_total = cents(decimal_value(order.amount, "Сумма заказа"))
    if exported_total != order_total:
        raise OrderPayloadError(
            f"Сумма строк {exported_total} не совпадает с Order.amount {order_total}"
        )

    return {
        "Posted": False,
        "НомерПоДаннымКлиента": str(order.id),
        "Партнер_Key": guid(customer.partner_id, "Партнёр"),
        "Контрагент_Key": guid(customer.legal_entity_id, "Контрагент"),
        "Договор_Key": guid(contract.contract_id, "Договор"),
        "Организация_Key": guid(contract.organization_id, "Организация"),
        "Менеджер_Key": guid(contract.manager.manager_id, "Менеджер"),
        "Соглашение_Key": guid(contract.agreement.agreement_id, "Соглашение"),
        "ДатаОтгрузки": shipping_date,
        "Комментарий": order.comment or "",
        "Товары": products,
    }
