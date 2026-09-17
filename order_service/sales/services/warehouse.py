from django.db.models import Sum

from catalog.models import (
    StockBalance,
    Warehouse,
)


class OrderWarehouseError(Exception):
    """Ошибка определения склада заказа."""


class OrderWarehouseNotFoundError(
    OrderWarehouseError
):
    """Не найден склад с остатками товаров заказа."""


class MultipleOrderWarehousesError(
    OrderWarehouseError
):
    """Товары заказа обнаружены на нескольких складах."""


def find_order_warehouse(
    *,
    organization_id,
    product_ids,
):
    """
    Определяет склад для заказа.

    Бизнес-правило:
    товары одного бренда в рамках одной организации
    должны храниться только на одном складе.

    Возвращает:
        Warehouse

    Исключения:
        OrderWarehouseNotFoundError
        MultipleOrderWarehousesError
    """

    product_ids = {
        str(product_id)
        for product_id in product_ids
        if product_id
    }


    if not organization_id:

        raise OrderWarehouseNotFoundError(
            "Не указана организация заказа."
        )


    if not product_ids:

        raise OrderWarehouseNotFoundError(
            "В заказе отсутствуют товары."
        )


    # =========================================================
    # Активные склады организации
    # =========================================================

    warehouses = (
        Warehouse.objects
        .filter(
            organization_id=organization_id,
            is_active=True,
        )
    )


    if not warehouses.exists():

        raise OrderWarehouseNotFoundError(
            "Для организации не настроены "
            "активные склады."
        )


    # =========================================================
    # Остатки товаров заказа по каждому складу
    # =========================================================

    stock_rows = (
        StockBalance.objects
        .filter(
            warehouse__in=warehouses,
            product_id__in=product_ids,
            quantity__gt=0,
        )
        .values(
            "warehouse_id"
        )
        .annotate(
            total_quantity=Sum(
                "quantity"
            )
        )
        .order_by(
            "warehouse_id"
        )
    )


    warehouse_ids = [
        str(row["warehouse_id"])
        for row in stock_rows
        if (
            row["total_quantity"]
            and row["total_quantity"] > 0
        )
    ]


    # =========================================================
    # Ничего не найдено
    # =========================================================

    if not warehouse_ids:

        raise OrderWarehouseNotFoundError(
            "Не найден склад с остатками "
            "товаров заказа."
        )


    # =========================================================
    # Нарушено бизнес-правило
    # =========================================================

    if len(warehouse_ids) > 1:

        raise MultipleOrderWarehousesError(
            "Товары заказа обнаружены "
            "на нескольких складах организации: "
            + ", ".join(
                warehouse_ids
            )
        )


    # =========================================================
    # Единственный склад
    # =========================================================

    return warehouses.get(
        warehouse_id=warehouse_ids[0]
    )