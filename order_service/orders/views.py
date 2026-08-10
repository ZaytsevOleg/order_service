from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q
from django.http import JsonResponse

from catalog.models import (
    Contract,
    LegalEntityDeliveryAddress,
    Price,
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


@login_required
def customer_products(request, customer_id):
    contract_id = (
        request.GET.get("contract_id", "")
        .strip()
    )

    search = (
        request.GET.get("q", "")
        .strip()
    )

    if not contract_id:
        return JsonResponse(
            {
                "error": "Не указан договор.",
            },
            status=400,
        )

    # ---------------------------------------------------------
    # Проверяем доступ пользователя к клиенту
    # ---------------------------------------------------------

    access = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity_id=customer_id,
            is_active=True,
            legal_entity__is_active=True,
        )
        .select_related(
            "price_type",
        )
        .first()
    )

    if access is None:
        return JsonResponse(
            {
                "error": "Клиент недоступен.",
            },
            status=403,
        )

    if access.price_type_id is None:
        return JsonResponse(
            {
                "error": (
                    "Для клиента не назначен "
                    "тип цен."
                ),
            },
            status=400,
        )

    # ---------------------------------------------------------
    # Проверяем договор
    # ---------------------------------------------------------

    contract = (
        Contract.objects
        .filter(
            pk=contract_id,
            legal_entity_id=customer_id,
            is_active=True,
        )
        .first()
    )

    if contract is None:
        return JsonResponse(
            {
                "error": (
                    "Договор не найден "
                    "или недоступен."
                ),
            },
            status=404,
        )

    if not contract.brand:
        return JsonResponse(
            {
                "error": (
                    "У договора не указан бренд."
                ),
            },
            status=400,
        )

    # ---------------------------------------------------------
    # Берём товары именно через Price.
    #
    # Благодаря этому товар без цены для назначенного
    # пользователю PriceType вообще не попадёт в выдачу.
    # ---------------------------------------------------------

    prices = (
        Price.objects
        .filter(
            price_type_id=access.price_type_id,
            product__brand_id=contract.brand,
            product__is_active=True,
            product__is_customer_selectable=True,
        )
        .select_related(
            "product",
            "product__brand",
            "price_type",
        )
        .order_by(
            "product__name",
        )
    )

    if search:
        prices = prices.filter(
            Q(
                product__name__icontains=search
            )
            | Q(
                product__article__icontains=search
            )
        )

    # На первом этапе не отдаём браузеру тысячи строк.
    prices = prices[:200]

    discount_percent = (
        access.discount_percent
        or Decimal("0.00")
    )

    hundred = Decimal("100.00")

    products = []

    for price_row in prices:
        base_price = price_row.price

        final_price = (
            base_price
            * (
                hundred
                - discount_percent
            )
            / hundred
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        product = price_row.product

        products.append(
            {
                "product_id": (
                    str(product.pk)
                ),
                "name": product.name,
                "article": product.article or "",
                "brand_id": contract.brand,
                "base_price": str(base_price),
                "discount_percent": str(
                    discount_percent
                ),
                "final_price": str(
                    final_price
                ),
            }
        )

    return JsonResponse(
        {
            "customer_id": str(customer_id),
            "contract_id": str(contract.pk),
            "brand_id": contract.brand,
            "brand_name": (
                contract.get_brand_display()
            ),
            "price_type": {
                "id": access.price_type_id,
                "name": access.price_type.name,
            },
            "discount_percent": str(
                discount_percent
            ),
            "count": len(products),
            "products": products,
        }
    )