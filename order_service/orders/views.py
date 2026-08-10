from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from django.http import JsonResponse

from catalog.models import (
    Contract,
    LegalEntityDeliveryAddress,
    UserLegalEntityAccess,
)
from sales.models import Order

from .forms import OrderCreateForm


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

    return render(
        request,
        "orders/order_list.html",
        {
            "orders": orders,
            "status_icons": STATUS_ICONS,
        },
    )


@login_required
def order_detail(request, order_id):
    allowed_legal_entities = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            is_active=True,
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

    return render(
        request,
        "orders/order_detail.html",
        {
            "order": order,
            "products": order.items.all(),
            "status_icon": STATUS_ICONS.get(
                order.status,
                "bi-question-circle",
            ),
        },
    )


@login_required
def order_create(request):
    if request.method == "POST":
        form = OrderCreateForm(
            request.POST,
            user=request.user,
        )

        if form.is_valid():
            order = form.save(commit=False)

            access = get_object_or_404(
                UserLegalEntityAccess.objects
                .select_related("price_type"),
                user=request.user,
                legal_entity=order.customer,
                is_active=True,
            )

            order.user = request.user
            order.price_type = access.price_type
            order.discount_percent = (
                access.discount_percent
            )

            order.save()

            return redirect(
                "order_detail",
                order_id=order.pk,
            )

    else:
        form = OrderCreateForm(
            user=request.user,
        )

    return render(
        request,
        "orders/order_create.html",
        {
            "form": form,
        },
    )

@login_required
def customer_options(request, customer_id):
    access = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity_id=customer_id,
            is_active=True,
            legal_entity__is_active=True,
        )
        .select_related("price_type")
        .first()
    )

    if access is None:
        return JsonResponse(
            {
                "error": "Клиент недоступен",
            },
            status=403,
        )

    contracts = (
        Contract.objects
        .filter(
            legal_entity_id=customer_id,
            is_active=True,
        )
        .order_by(
            "brand",
            "contract_name",
        )
    )

    addresses = (
        LegalEntityDeliveryAddress.objects
        .filter(
            legal_entity_id=customer_id,
            is_active=True,
        )
        .order_by("address")
    )

    return JsonResponse(
        {
            "price_type": {
                "id": (
                    access.price_type_id
                    if access.price_type_id
                    else None
                ),
                "name": (
                    access.price_type.name
                    if access.price_type
                    else None
                ),
            },
            "discount_percent": str(
                access.discount_percent
            ),
            "contracts": [
                {
                    "id": contract.pk,
                    "name": contract.contract_name,
                    "brand_id": contract.brand,
                    "brand_name": contract.get_brand_display(),
                }
                for contract in contracts
            ],
            "addresses": [
                {
                    "id": address.pk,
                    "address": address.address,
                }
                for address in addresses
            ],
        }
    )