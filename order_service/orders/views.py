from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Q, Sum
from django.http import JsonResponse

from catalog.models import (
    Contract,
    LegalEntityDeliveryAddress,
    Price,
    UserLegalEntityAccess,
    CurrencyRate,
    Warehouse,
    StockBalance,
)
from sales.models import Order

from .forms import OrderCreateForm
from django.utils import timezone



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
            contract__brand=request.brand.brand_id,
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
        contract__brand=request.brand.brand_id,
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
            brand=request.brand,
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
            brand=request.brand,
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
            brand=request.brand.brand_id,
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
            brand=request.brand.brand_id,
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

    if not contract.organization_id:
        return JsonResponse(
            {
                "error": (
                    "Для договора не указана "
                    "организация."
                ),
            },
            status=400,
        )

    warehouse_ids = list(
        Warehouse.objects
        .filter(
            organization_id=(
                contract.organization_id
            ),
            is_active=True,
        )
        .values_list(
            "warehouse_id",
            flat=True,
        )
    )

    if not warehouse_ids:
        return JsonResponse(
            {
                "error": (
                    "Для организации договора "
                    "не настроены активные склады."
                ),
            },
            status=400,
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
                product__name_translation__icontains=search
            )
            | Q(
                product__article__icontains=search
            )        
        )

    # На первом этапе не отдаём браузеру тысячи строк.
    price_rows = list(
        prices[:200]
    )


    product_ids = [
        price_row.product_id
        for price_row in price_rows
    ]

    stock_rows = (
        StockBalance.objects
        .filter(
            warehouse_id__in=warehouse_ids,
            product_id__in=product_ids,
        )
        .values(
            "product_id"
        )
        .annotate(
            total_quantity=Sum(
                "quantity"
            )
        )
    )

    stock_by_product = {
        str(row["product_id"]):
            (
                row["total_quantity"]
                or Decimal("0")
            )
        for row in stock_rows
    }

    discount_percent = (
        access.discount_percent
        or Decimal("0.00")
    )

    hundred = Decimal("100.00")

    today = timezone.localdate()

    currency_rate_row = (
        CurrencyRate.objects
        .filter(
            currency_code="YE",
            valid_from__lte=today,
        )
        .order_by(
            "-valid_from",
            "-id",
        )
        .first()
    )

    if currency_rate_row is None:
        return JsonResponse(
            {
                "error": (
                    "Не найден действующий курс валюты YE."
                ),
            },
            status=500,
        )

    currency_rate = currency_rate_row.rate

    products = []

    for price_row in price_rows:
        base_price_ye = price_row.price

        base_price_rub = (
            base_price_ye
            * currency_rate
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

        final_price_rub = (
            base_price_rub
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

        stock_quantity = (
            stock_by_product.get(
                str(product.pk),
                Decimal("0"),
            )
        )        

        products.append(
            {
                "product_id": str(product.pk),

                "article": (
                    product.article
                    or ""
                ),

                "name": (
                    product.name
                    or ""
                ),

                "name_translation": (
                    product.name_translation
                    or ""
                ),

                "category": (
                    product.category
                    or ""
                ),

                "subcategory": (
                    product.subcategory
                    or ""
                ),

                "level_2": (
                    product.level_2
                    or ""
                ),

                "level_3": (
                    product.level_3
                    or ""
                ),

                "level_4": (
                    product.level_4
                    or ""
                ),

                "brand_id": contract.brand,

                "price_currency": "YE",

                "base_price_ye": str(
                    base_price_ye
                ),

                "currency_rate": str(
                    currency_rate
                ),

                "base_price": str(
                    base_price_rub
                ),

                "discount_percent": str(
                    discount_percent
                ),

                "final_price": str(
                    final_price_rub
                ),
                "stock_quantity": str(
                    stock_quantity
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

            "currency": {
                "code": "YE",
                "rate": str(currency_rate),
                "valid_from": (
                    currency_rate_row
                    .valid_from
                    .isoformat()
                ),
            },
            
            "stock": {
                "organization_id": (
                    contract.organization_id
                ),
                "warehouse_ids": [
                    str(warehouse_id)
                    for warehouse_id
                    in warehouse_ids
                ],
            },            

            "discount_percent": str(
                discount_percent
            ),

            "count": len(products),
            "products": products,
        }
    )