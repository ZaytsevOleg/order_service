from django.contrib import admin

from sales.models import (
    Order,
    OrderItem,
)


class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

    fields = (
        "line_number",
        "product",
        "product_name",
        "article",
        "quantity",
        "price",
        "discount_percent",
        "amount",
    )

    readonly_fields = (
        "product_name",
        "article",
        "amount",
    )

    autocomplete_fields = (
        "product",
    )


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = (
        "number",
        "customer",
        "user",
        "status",
        "payment_method",
        "amount",
        "created_at",
        "sent_to_1c_at",
    )

    list_filter = (
        "status",
        "payment_method",
        "shipping_type",
        "created_at",
    )

    search_fields = (
        "number",
        "one_c_order_id",
        "customer__name",
        "customer__inn",
        "user__username",
        "user__email",
    )

    autocomplete_fields = (
        "user",
        "customer",
        "contract",
        "price_type",
        "delivery_address",
    )

    readonly_fields = (
        "id",
        "created_at",
        "updated_at",
        "sent_to_1c_at",
        "amount",
    )

    list_select_related = (
        "user",
        "customer",
        "contract",
        "price_type",
        "delivery_address",
    )

    inlines = [
        OrderItemInline,
    ]

    ordering = (
        "-created_at",
    )


@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        "order",
        "line_number",
        "product",
        "product_name",
        "quantity",
        "price",
        "discount_percent",
        "amount",
    )

    search_fields = (
        "order__number",
        "product__name",
        "product__article",
        "product_name",
        "article",
    )

    autocomplete_fields = (
        "order",
        "product",
    )

    list_select_related = (
        "order",
        "product",
    )