from django.contrib.auth.decorators import login_required
from django.shortcuts import get_object_or_404, render

from catalog.models import UserLegalEntityAccess
from sales.models import Order

from .forms import OrderForm


STATUS_ICONS = {
    Order.STATUS_DRAFT: "bi-pencil",
    Order.STATUS_APPROVAL: "bi-clock-history",
    Order.STATUS_CONFIRMED: "bi-check2-square",
    Order.STATUS_SHIPPING: "bi-truck",
    Order.STATUS_COMPLETED: "bi-patch-check-fill",
}


@login_required
def home(request):
    return render(
        request,
        "orders/home.html",
    )


@login_required
def order_list(request):
    allowed_legal_entities = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            is_active=True,
            legal_entity__is_active=True,
        )
        .values_list(
            "legal_entity_id",
            flat=True,
        )
    )

    orders = (
        Order.objects
        .filter(
            customer_id__in=allowed_legal_entities,
        )
        .select_related(
            "customer",
            "contract",
            "price_type",
            "delivery_address",
            "user",
        )
        .order_by("-created_at")
    )

    order_rows = []

    for order in orders:
        order_rows.append(
            {
                "order_id": order.pk,
                "order_number": order.number,
                "Number": order.number,
                "customer": order.customer.name,
                "creation_date": order.created_at,
                "status": order.get_status_display(),
                "status_value": order.status,
                "status_icon": STATUS_ICONS.get(
                    order.status,
                    "bi-question-circle",
                ),
                "shipping_date": None,
                "shipping_type": order.shipping_type,
                "total_amount": order.amount,
            }
        )

    return render(
        request,
        "orders/order_list.html",
        {
            "orders": order_rows,
        },
    )


@login_required
def order_detail(request, order_id):
    allowed_legal_entities = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            is_active=True,
            legal_entity__is_active=True,
        )
        .values_list(
            "legal_entity_id",
            flat=True,
        )
    )

    order = get_object_or_404(
        Order.objects
        .select_related(
            "customer",
            "contract",
            "price_type",
            "delivery_address",
            "user",
        )
        .prefetch_related(
            "items__product",
        ),
        pk=order_id,
        customer_id__in=allowed_legal_entities,
    )

    products = []

    for item in order.items.all():
        products.append(
            {
                "line_number": item.line_number,
                "product_name": item.product_name,
                "product_article": item.article,
                "quantity": item.quantity,
                "price": item.price,
                "amount": item.amount,
                "discount": item.discount_percent,
            }
        )

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "products": products,
            "status_text": order.get_status_display(),
            "status_icon": STATUS_ICONS.get(
                order.status,
                "bi-question-circle",
            ),
        },
    )


@login_required
def order_create(request):
    return render(
        request,
        "orders/order_create.html",
    )