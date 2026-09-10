from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.db.models import Q, Prefetch, Sum
from django.db import transaction
from django.http import JsonResponse, Http404
from django.urls import reverse
from catalog.models import (
    Contract,
    LegalEntity,
    LegalEntityDeliveryAddress,
    Price,
    UserLegalEntityAccess,
    CurrencyRate,
    Warehouse,
    StockBalance,
    PromoAction,
    PromoActionProduct,
    PromoGiftProduct,
)
from sales.models import Order, OrderItem, WorkCalendarException
import json
from .forms import OrderCreateForm
from django.utils import timezone
from datetime import (
    datetime,
    timedelta,
)
from django.views.decorators.http import require_POST, require_GET

from orders.services.promo_engine import PromoEngine
from sales.shipping.shipping_calendar import (
    get_delivery_min_date,
    get_pickup_min_date,
    get_shipping_settings,
    is_working_day,
)


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
            "orders":
                orders,

            "status_icons":
                STATUS_ICONS,

            "draft_status":
                Order.STATUS_DRAFT,
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



def customer_promotions(request, customer_id):

    contract_id = (
        request.GET.get(
            "contract_id",
            "",
        )
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

    access_exists = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity_id=customer_id,
            is_active=True,
            legal_entity__is_active=True,
        )
        .exists()
    )

    if not access_exists:
        return JsonResponse(
            {
                "error": "Клиент недоступен.",
            },
            status=403,
        )

    # ---------------------------------------------------------
    # Проверяем договор и бренд
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
    # Действующие промо
    # ---------------------------------------------------------

    now = timezone.now()

    promotions = (
        PromoAction.objects
        .filter(
            brand_id=contract.brand,
            is_active=True,
        )
        .filter(
            Q(valid_from__isnull=True)
            | Q(valid_from__lte=now)
        )
        .filter(
            Q(valid_to__isnull=True)
            | Q(valid_to__gte=now)
        )
        .prefetch_related(
            Prefetch(
                "condition_products",
                queryset=(
                    PromoActionProduct.objects
                    .select_related("product")
                    .order_by(
                        "product__name"
                    )
                ),
            ),
            Prefetch(
                "gift_products",
                queryset=(
                    PromoGiftProduct.objects
                    .select_related("product")
                    .order_by(
                        "product__name"
                    )
                ),
            ),
        )
        .order_by(
            "priority",
            "-valid_from",
            "name",
        )
    )

    result = []

    for promo in promotions:

        condition_products = []

        for row in promo.condition_products.all():

            condition_products.append(
                {
                    "product_id": str(
                        row.product_id
                    ),
                    "article": (
                        row.product.article
                        or ""
                    ),
                    "name": (
                        row.product.name
                        or ""
                    ),
                    "quantity": (
                        row.quantity
                    ),
                }
            )

        gift_products = []

        for row in promo.gift_products.all():

            gift_products.append(
                {
                    "product_id": str(
                        row.product_id
                    ),
                    "article": (
                        row.product.article
                        or ""
                    ),
                    "name": (
                        row.product.name
                        or ""
                    ),
                    "quantity": (
                        row.quantity
                    ),
                }
            )

        image_url = ""

        if promo.image:
            try:
                image_url = promo.image.url
            except ValueError:
                image_url = ""

        result.append(
            {
                "promo_id": str(
                    promo.pk
                ),

                "name": promo.name,

                "short_description": (
                    promo.short_description
                    or ""
                ),

                "description": (
                    promo.description
                    or ""
                ),

                "image_url": image_url,

                "condition_type": (
                    promo.condition_type
                ),

                "condition_type_name": (
                    promo.get_condition_type_display()
                ),

                "threshold_quantity": (
                    promo.threshold_quantity
                ),

                "threshold_amount": (
                    str(promo.threshold_amount)
                    if promo.threshold_amount
                    is not None
                    else None
                ),

                "reward_type": (
                    promo.reward_type
                ),

                "reward_type_name": (
                    promo.get_reward_type_display()
                ),

                "discount_percent": (
                    str(promo.discount_percent)
                    if promo.discount_percent
                    is not None
                    else None
                ),

                "show_progress": (
                    promo.show_progress
                ),

                "progress_threshold_percent": (
                    promo.progress_threshold_percent
                ),

                "priority": promo.priority,

                "valid_from": (
                    promo.valid_from.isoformat()
                    if promo.valid_from
                    else None
                ),

                "valid_to": (
                    promo.valid_to.isoformat()
                    if promo.valid_to
                    else None
                ),

                "condition_products": (
                    condition_products
                ),

                "gift_products": (
                    gift_products
                ),
            }
        )

    return JsonResponse(
        {
            "customer_id": str(
                customer_id
            ),

            "contract_id": str(
                contract.contract_id
            ),

            "brand_id": (
                contract.brand
            ),

            "count": len(result),

            "promotions": result,
        }
    )

@login_required
@require_POST
def evaluate_promotions(
    request,
    customer_id,
):

    # =========================================================
    # Читаем JSON
    # =========================================================

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error": (
                    "Некорректный JSON."
                ),
            },
            status=400,
        )


    contract_id = str(
        payload.get(
            "contract_id",
            "",
        )
    ).strip()

    raw_items = (
        payload.get("items")
        or []
    )


    if not contract_id:

        return JsonResponse(
            {
                "error": (
                    "Не указан договор."
                ),
            },
            status=400,
        )


    if not isinstance(
        raw_items,
        list,
    ):

        return JsonResponse(
            {
                "error": (
                    "Некорректный состав корзины."
                ),
            },
            status=400,
        )


    # =========================================================
    # Проверяем доступ пользователя к клиенту
    # =========================================================

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
                "error": (
                    "Клиент недоступен."
                ),
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


    # =========================================================
    # Проверяем договор
    # =========================================================

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


    if not contract.brand:

        return JsonResponse(
            {
                "error": (
                    "У договора не указан бренд."
                ),
            },
            status=400,
        )


    # =========================================================
    # Нормализуем корзину
    #
    # Если один product_id каким-либо образом пришёл
    # несколько раз — складываем количество.
    # =========================================================

    quantities_by_product = {}


    for item in raw_items:

        if not isinstance(
            item,
            dict,
        ):
            continue


        product_id = str(
            item.get(
                "product_id",
                "",
            )
        ).strip()


        try:
            quantity = int(
                item.get(
                    "quantity",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            quantity = 0


        if (
            not product_id
            or quantity <= 0
        ):
            continue


        quantities_by_product[
            product_id
        ] = (
            quantities_by_product.get(
                product_id,
                0,
            )
            + quantity
        )


    product_ids = list(
        quantities_by_product.keys()
    )


    # =========================================================
    # Берём актуальный курс YE
    # =========================================================

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
                    "Не найден действующий "
                    "курс валюты YE."
                ),
            },
            status=500,
        )


    currency_rate = (
        currency_rate_row.rate
    )


    # =========================================================
    # Получаем базовые цены самостоятельно
    # =========================================================

    prices = (
        Price.objects
        .filter(
            price_type_id=(
                access.price_type_id
            ),
            product_id__in=(
                product_ids
            ),
            product__brand_id=(
                contract.brand
            ),
            product__is_active=True,
        )
        .select_related(
            "product",
        )
    )


    prices_by_product = {
        str(price.product_id):
            price
        for price in prices
    }


    # =========================================================
    # Готовим корзину для PromoEngine
    # =========================================================

    cart_items = []


    for (
        product_id,
        quantity,
    ) in quantities_by_product.items():

        price_row = (
            prices_by_product.get(
                product_id
            )
        )


        # Товар без актуальной цены
        # не участвует в расчёте промо.
        if price_row is None:
            continue


        base_price_rub = (
            Decimal(
                str(
                    price_row.price
                )
            )
            * Decimal(
                str(
                    currency_rate
                )
            )
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        cart_items.append(
            {
                "product_id":
                    product_id,

                "quantity":
                    quantity,

                "base_price":
                    base_price_rub,
            }
        )


    # =========================================================
    # Получаем только действующие акции бренда
    # =========================================================

    now = timezone.now()


    promotions = (
        PromoAction.objects
        .filter(
            brand_id=contract.brand,
            is_active=True,
        )
        .filter(
            Q(valid_from__isnull=True)
            | Q(valid_from__lte=now)
        )
        .filter(
            Q(valid_to__isnull=True)
            | Q(valid_to__gte=now)
        )
        .prefetch_related(
            Prefetch(
                "condition_products",
                queryset=(
                    PromoActionProduct.objects
                    .select_related(
                        "product"
                    )
                ),
            ),

            Prefetch(
                "gift_products",
                queryset=(
                    PromoGiftProduct.objects
                    .select_related(
                        "product"
                    )
                ),
            ),
        )
        .order_by(
            "priority",
            "-valid_from",
            "name",
        )
    )


    # =========================================================
    # Оцениваем акции
    # =========================================================

    evaluations = []


    for promo in promotions:

        evaluation = (
            PromoEngine.evaluate(
                promo,
                cart_items,
            )
        )


        eligible = bool(
            evaluation.get(
                "eligible",
                False,
            )
        )


        progress = (
            evaluation.get(
                "progress"
            )
        )

        missing = (
            evaluation.get(
                "missing"
            )
            or []
        )

        progress_percent = (
            evaluation.get(
                "progress_percent",
                0,
            )
        )        


        # -----------------------------------------------------
        # Администратор может запретить клиенту видеть,
        # сколько ему не хватает до акции.
        #
        # Сам факт eligible backend всё равно знает.
        # -----------------------------------------------------

        if (
            not eligible
            and not promo.show_progress
        ):
            progress = None
            missing = []


        evaluations.append(
            {
                "promo_id": str(
                    promo.pk
                ),

                "eligible":
                    eligible,

                "show_progress":
                    promo.show_progress,

                "condition_type":
                    promo.condition_type,

                "reward_type":
                    promo.reward_type,

                "progress":
                    progress,

                "missing":
                    missing,
                "progress_percent":
                    progress_percent,
            }
        )


    return JsonResponse(
        {
            "customer_id": str(
                customer_id
            ),

            "contract_id": str(
                contract.contract_id
            ),

            "currency": {
                "code": "YE",

                "rate": str(
                    currency_rate
                ),

                "valid_from": (
                    currency_rate_row
                    .valid_from
                    .isoformat()
                ),
            },

            "count": len(
                evaluations
            ),

            "promotions":
                evaluations,
        }
    )


@login_required
@require_POST
def apply_promotion(
    request,
    customer_id,
):

    # =========================================================
    # JSON
    # =========================================================

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error": "Некорректный JSON.",
            },
            status=400,
        )


    contract_id = str(
        payload.get(
            "contract_id",
            "",
        )
    ).strip()

    promo_id = str(
        payload.get(
            "promo_id",
            "",
        )
    ).strip()


    try:
        promo_quantity = int(
            payload.get(
                "quantity",
                1,
            )
        )

    except (
        TypeError,
        ValueError,
    ):
        promo_quantity = 0


    if not contract_id:
        return JsonResponse(
            {
                "error": "Не указан договор.",
            },
            status=400,
        )


    if not promo_id:
        return JsonResponse(
            {
                "error": "Не указана промо акция.",
            },
            status=400,
        )


    if promo_quantity <= 0:
        return JsonResponse(
            {
                "error": (
                    "Количество промо должно "
                    "быть больше нуля."
                ),
            },
            status=400,
        )


    # =========================================================
    # Доступ пользователя
    # =========================================================

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


    # =========================================================
    # Договор
    # =========================================================

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


    # =========================================================
    # Действующая акция
    # =========================================================

    now = timezone.now()


    promo = (
        PromoAction.objects
        .filter(
            pk=promo_id,
            brand_id=contract.brand,
            is_active=True,
        )
        .filter(
            Q(valid_from__isnull=True)
            | Q(valid_from__lte=now)
        )
        .filter(
            Q(valid_to__isnull=True)
            | Q(valid_to__gte=now)
        )
        .prefetch_related(
            Prefetch(
                "condition_products",
                queryset=(
                    PromoActionProduct.objects
                    .select_related(
                        "product"
                    )
                    .order_by(
                        "product__name"
                    )
                ),
            ),

            Prefetch(
                "gift_products",
                queryset=(
                    PromoGiftProduct.objects
                    .select_related(
                        "product"
                    )
                    .order_by(
                        "product__name"
                    )
                ),
            ),
        )
        .first()
    )


    if promo is None:
        return JsonResponse(
            {
                "error": (
                    "Промо акция недоступна "
                    "или срок её действия истёк."
                ),
            },
            status=404,
        )


    # =========================================================
    # Автоматически можно добавить только fixed_set
    # =========================================================

    if (
        promo.condition_type
        != PromoAction.CONDITION_FIXED_SET
    ):
        return JsonResponse(
            {
                "error": (
                    "Эта промо акция требует "
                    "самостоятельного выбора товаров."
                ),

                "condition_type":
                    promo.condition_type,
            },
            status=409,
        )


    # =========================================================
    # Проверяем состав fixed_set
    # =========================================================

    condition_rows = list(
        promo.condition_products.all()
    )


    if not condition_rows:
        return JsonResponse(
            {
                "error": (
                    "Для промо акции "
                    "не задан состав товаров."
                ),
            },
            status=500,
        )


    for row in condition_rows:

        if (
            row.quantity is None
            or row.quantity <= 0
        ):
            return JsonResponse(
                {
                    "error": (
                        "Для одного из товаров "
                        "промо акции не указано "
                        "необходимое количество."
                    ),
                },
                status=500,
            )


    # =========================================================
    # Базовые цены товаров промо
    #
    # Не доверяем frontend.
    # =========================================================

    product_ids = [
        str(row.product_id)
        for row in condition_rows
    ]


    prices = (
        Price.objects
        .filter(
            price_type_id=(
                access.price_type_id
            ),
            product_id__in=product_ids,
            product__brand_id=contract.brand,
            product__is_active=True,
        )
        .select_related(
            "product",
        )
    )


    prices_by_product = {
        str(row.product_id):
            row
        for row in prices
    }


    missing_price_products = [
        row.product.name
        for row in condition_rows
        if str(row.product_id)
        not in prices_by_product
    ]


    if missing_price_products:
        return JsonResponse(
            {
                "error": (
                    "Для части товаров промо "
                    "не найдены актуальные цены."
                ),

                "products":
                    missing_price_products,
            },
            status=409,
        )


    # =========================================================
    # Курс YE
    # =========================================================

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
                    "Не найден действующий "
                    "курс валюты YE."
                ),
            },
            status=500,
        )


    currency_rate = Decimal(
        str(
            currency_rate_row.rate
        )
    )


    # =========================================================
    # Формируем платный состав промо
    # =========================================================

    products = []


    for row in condition_rows:

        price_row = (
            prices_by_product[
                str(row.product_id)
            ]
        )


        base_price_rub = (
            Decimal(
                str(
                    price_row.price
                )
            )
            * currency_rate
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        # Обычная скидка клиента.
        #
        # Для подарочной акции она остаётся обычной.
        # Для скидочной акции ниже заменим её
        # на промо-скидку.
        customer_discount = (
            access.discount_percent
            or Decimal("0.00")
        )


        applied_discount = (
            customer_discount
        )


        if (
            promo.reward_type
            == PromoAction.REWARD_DISCOUNT
        ):

            applied_discount = (
                promo.discount_percent
                or Decimal("0.00")
            )


        final_price = (
            base_price_rub
            * (
                Decimal("100.00")
                - applied_discount
            )
            / Decimal("100.00")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        products.append(
            {
                "product_id": str(
                    row.product_id
                ),

                "article": (
                    row.product.article
                    or ""
                ),

                "name": (
                    row.product.name
                    or ""
                ),

                "quantity": (
                    row.quantity
                    * promo_quantity
                ),

                "base_price": str(
                    base_price_rub
                ),

                "discount_percent": str(
                    applied_discount
                ),

                "final_price": str(
                    final_price
                ),

                "promo_id": str(
                    promo.pk
                ),

                "promo_name":
                    promo.name,

                "is_promo_product":
                    True,
            }
        )


    # =========================================================
    # Подарки
    # =========================================================

    gifts = []


    if (
        promo.reward_type
        == PromoAction.REWARD_GIFT
    ):

        for row in (
            promo.gift_products.all()
        ):

            gifts.append(
                {
                    "product_id": str(
                        row.product_id
                    ),

                    "article": (
                        row.product.article
                        or ""
                    ),

                    "name": (
                        row.product.name
                        or ""
                    ),

                    "quantity": (
                        row.quantity
                        * promo_quantity
                    ),

                    "price":
                        "0.00",

                    "base_price":
                        "0.00",

                    "discount_percent":
                        "0.00",

                    "final_price":
                        "0.00",

                    "is_promo_gift":
                        True,

                    "promo_id": str(
                        promo.pk
                    ),

                    "promo_name":
                        promo.name,
                }
            )


    # =========================================================
    # Ответ
    # =========================================================

    return JsonResponse(
        {
            "promo_id": str(
                promo.pk
            ),

            "promo_name":
                promo.name,

            "promo_quantity":
                promo_quantity,

            "condition_type":
                promo.condition_type,

            "reward_type":
                promo.reward_type,

            "discount_percent": (
                str(
                    promo.discount_percent
                )
                if promo.discount_percent
                is not None
                else None
            ),

            "products":
                products,

            "gifts":
                gifts,
        }
    )

@login_required
@require_GET
def shipping_options(
    request,
    customer_id,
):

    contract_id = str(
        request.GET.get(
            "contract_id",
            "",
        )
    ).strip()

    order_amount_raw = str(
        request.GET.get(
            "order_amount",
            "0",
        )
    ).strip()

    if not contract_id:

        return JsonResponse(
            {
                "error":
                    "Не указан договор.",
            },
            status=400,
        )

    try:

        order_amount = Decimal(
            order_amount_raw
        )

    except (
        InvalidOperation,
        ValueError,
    ):

        return JsonResponse(
            {
                "error":
                    "Некорректная сумма заказа.",
            },
            status=400,
        )

    if order_amount < 0:

        return JsonResponse(
            {
                "error":
                    "Сумма заказа не может быть отрицательной.",
            },
            status=400,
        )

    access = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity_id=customer_id,
            is_active=True,
            legal_entity__is_active=True,
        )
        .first()
    )

    if access is None:
        return JsonResponse(
            {
                "error":
                    "Клиент недоступен.",
            },
            status=403,
        )

    contract = (
        Contract.objects
        .select_related(
            "manager",
            "manager__department",
        )
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
                "error":
                    "Договор не найден или недоступен.",
            },
            status=404,
        )

    manager = contract.manager

    if manager is None:

        return JsonResponse(
            {
                "error":
                    "Для договора не указан менеджер.",
                "pickup_available":
                    True,
                "delivery_available":
                    False,
            },
            status=200,
        )

    department = manager.department

    if department is None:

        return JsonResponse(
            {
                "error":
                    "Для менеджера не указано подразделение.",
                "pickup_available":
                    True,
                "delivery_available":
                    False,
            },
            status=200,
        )

    if not department.is_active:

        return JsonResponse(
            {
                "error":
                    "Подразделение не участвует "
                    "в автоматическом расчёте доставки.",
                "pickup_available":
                    True,
                "delivery_available":
                    False,

                "manager": {
                    "id":
                        str(
                            manager.manager_id
                        ),

                    "name":
                        manager.name,
                },

                "department": {
                    "id":
                        str(
                            department.department_id
                        ),

                    "name":
                        department.name,
                },
            },
            status=200,
        )

    min_delivery_amount = (
        department.min_delivery_amount
        or Decimal("0.00")
    )

    delivery_available = (
        order_amount
        >= min_delivery_amount
    )

    amount_to_delivery = max(
        Decimal("0.00"),
        min_delivery_amount
        - order_amount,
    )

    delivery_min_date = get_delivery_min_date()
    pickup_min_date = get_pickup_min_date()

    shipping_settings = get_shipping_settings()

    today = timezone.localdate()

    booking_max_date = (
        today
        + timedelta(
            days=shipping_settings.booking_horizon_days
        )
    )

    calendar_exceptions = {
        exception.date.isoformat():
            exception.day_type

        for exception in (
            WorkCalendarException.objects
            .filter(
                date__gte=today,
                date__lte=booking_max_date,
            )
            .order_by("date")
        )
    }

    return JsonResponse(
        {
            "contract_id":
                str(
                    contract.contract_id
                ),

            "manager": {
                "id":
                    str(
                        manager.manager_id
                    ),

                "name":
                    manager.name,

                "email":
                    manager.email or "",

                "phone":
                    manager.phone or "",
            },

            "department": {
                "id":
                    str(
                        department.department_id
                    ),

                "name":
                    department.name,
            },

            "pickup_available":
                True,

            "delivery_available":
                delivery_available,

            "order_amount":
                str(
                    order_amount
                ),

            "min_delivery_amount":
                str(
                    min_delivery_amount
                ),

            "amount_to_delivery":
                str(
                    amount_to_delivery
                ),

            "delivery_min_date": (
                delivery_min_date.isoformat()
            ),

            "pickup_min_date": (
                pickup_min_date.isoformat()
            ),
            
            "booking_horizon_days": (
                shipping_settings.booking_horizon_days
            ),

            "booking_max_date": (
                booking_max_date.isoformat()
            ),

            "calendar_exceptions": (
                calendar_exceptions
            ),
        }
    )

@login_required
def available_customers(request):

    payment_method = (
        request.GET.get(
            "payment_method",
            "",
        )
        .strip()
    )

    if payment_method not in {
        Order.PAYMENT_CASH,
        Order.PAYMENT_CASHLESS,
    }:
        return JsonResponse(
            {
                "error":
                    "Некорректная форма оплаты.",
            },
            status=400,
        )

    accesses = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            is_active=True,
            legal_entity__is_active=True,
        )
    )

    customers = (
        LegalEntity.objects
        .filter(
            customer_accesses__in=accesses,
            contracts__brand=request.brand.brand_id,
            contracts__is_active=True,
        )
        .distinct()
    )

    if payment_method == Order.PAYMENT_CASH:

        customers = customers.filter(
            client_type=
                LegalEntity.CLIENT_TYPE_PERSON,
        )

    elif payment_method == Order.PAYMENT_CASHLESS:

        customers = customers.filter(
            client_type__in=[
                LegalEntity.CLIENT_TYPE_LLC,
                LegalEntity.CLIENT_TYPE_IE,
            ],
        )

    customers = customers.order_by(
        "name",
    )

    return JsonResponse(
        {
            "customers": [
                {
                    "id":
                        str(customer.pk),

                    "name":
                        customer.display_name,

                    "client_type":
                        customer.client_type,

                    "client_type_name":
                        customer.get_client_type_display(),
                }
                for customer in customers
            ],
        }
    )

@login_required
@require_POST
def create_order_draft(request):

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error": "Некорректный JSON.",
            },
            status=400,
        )


    customer_id = str(
        payload.get(
            "customer_id",
            "",
        )
    ).strip()

    contract_id = str(
        payload.get(
            "contract_id",
            "",
        )
    ).strip()

    payment_method = str(
        payload.get(
            "payment_method",
            "",
        )
    ).strip()


    if not customer_id:
        return JsonResponse(
            {
                "error": "Не указан клиент.",
            },
            status=400,
        )

    if not contract_id:
        return JsonResponse(
            {
                "error": "Не указан договор.",
            },
            status=400,
        )

    if payment_method not in {
        Order.PAYMENT_CASH,
        Order.PAYMENT_CASHLESS,
    }:
        return JsonResponse(
            {
                "error": "Некорректная форма оплаты.",
            },
            status=400,
        )


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
            "legal_entity",
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


    customer = access.legal_entity


    if (
        customer.allowed_payment_method
        != payment_method
    ):
        return JsonResponse(
            {
                "error": (
                    "Выбранная форма оплаты "
                    "недоступна для этого клиента."
                ),
            },
            status=400,
        )


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


    draft = Order.objects.create(
        user=request.user,
        customer=customer,
        contract=contract,
        price_type=access.price_type,
        payment_method=payment_method,
        shipping_type=Order.SHIPPING_PICKUP,
        status=Order.STATUS_DRAFT,
        discount_percent=(
            access.discount_percent
            or Decimal("0.00")
        ),
        amount=Decimal("0.00"),
        current_step=2,
    )


    return JsonResponse(
        {
            "order_id": str(
                draft.pk
            ),
            "status": draft.status,
            "current_step": (
                draft.current_step
            ),
        },
        status=201,
    )

@login_required
@require_POST
def save_draft_items(
    request,
    order_id,
):

    # =========================================================
    # Черновик
    # =========================================================

    order = (
        Order.objects
        .select_related(
            "customer",
            "contract",
            "price_type",
        )
        .filter(
            pk=order_id,
            user=request.user,
            status=Order.STATUS_DRAFT,
            contract__brand=request.brand.brand_id,
        )
        .first()
    )

    if order is None:
        return JsonResponse(
            {
                "error":
                    "Черновик заказа не найден "
                    "или недоступен.",
            },
            status=404,
        )


    # =========================================================
    # JSON
    # =========================================================

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error":
                    "Некорректный JSON.",
            },
            status=400,
        )


    raw_items = (
        payload.get("items")
        or []
    )

    if not isinstance(
        raw_items,
        list,
    ):
        return JsonResponse(
            {
                "error":
                    "Некорректный состав корзины.",
            },
            status=400,
        )


    # =========================================================
    # Проверяем доступ к клиенту
    # =========================================================

    access = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity=order.customer,
            is_active=True,
            legal_entity__is_active=True,
        )
        .select_related(
            "price_type"
        )
        .first()
    )

    if access is None:
        return JsonResponse(
            {
                "error":
                    "Клиент недоступен.",
            },
            status=403,
        )

    if access.price_type_id is None:
        return JsonResponse(
            {
                "error":
                    "Для клиента не назначен тип цен.",
            },
            status=400,
        )


    # =========================================================
    # Договор
    # =========================================================

    contract = order.contract

    if (
        not contract.is_active
        or contract.brand
        != request.brand.brand_id
    ):
        return JsonResponse(
            {
                "error":
                    "Договор недоступен.",
            },
            status=400,
        )

    if not contract.organization_id:
        return JsonResponse(
            {
                "error":
                    "Для договора не указана организация.",
            },
            status=400,
        )


    # =========================================================
    # Нормализуем товары
    # =========================================================

    quantities = {}

    for item in raw_items:

        if not isinstance(
            item,
            dict,
        ):
            continue

        product_id = str(
            item.get(
                "product_id",
                "",
            )
        ).strip()

        try:
            quantity = Decimal(
                str(
                    item.get(
                        "quantity",
                        0,
                    )
                )
            )

        except (
            InvalidOperation,
            TypeError,
            ValueError,
        ):
            quantity = Decimal("0")

        if (
            not product_id
            or quantity <= 0
        ):
            continue

        quantities[
            product_id
        ] = (
            quantities.get(
                product_id,
                Decimal("0"),
            )
            + quantity
        )


    product_ids = list(
        quantities.keys()
    )


    # =========================================================
    # Если корзина очищена
    # =========================================================

    if not product_ids:

        with transaction.atomic():

            OrderItem.objects.filter(
                order=order,
                is_promo_product=False,
                is_promo_gift=False,
            ).delete()

            promo_amount = (
                OrderItem.objects
                .filter(
                    order=order,
                )
                .aggregate(
                    total=Sum("amount")
                )["total"]
                or Decimal("0.00")
            )

            order.amount = promo_amount
            order.current_step = max(
                order.current_step,
                2,
            )

            order.save(
                update_fields=[
                    "amount",
                    "current_step",
                    "updated_at",
                ]
            )

        return JsonResponse(
            {
                "order_id": str(order.pk),
                "items_count": 0,
                "amount": str(order.amount),
            }
        )


    # =========================================================
    # Курс YE
    # =========================================================

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
                "error":
                    "Не найден действующий курс валюты YE.",
            },
            status=500,
        )

    currency_rate = Decimal(
        str(
            currency_rate_row.rate
        )
    )


    # =========================================================
    # Цены
    # =========================================================

    prices = (
        Price.objects
        .filter(
            price_type_id=access.price_type_id,
            product_id__in=product_ids,
            product__brand_id=contract.brand,
            product__is_active=True,
            product__is_customer_selectable=True,
        )
        .select_related(
            "product"
        )
    )

    prices_by_product = {
        str(row.product_id):
            row
        for row in prices
    }


    missing_product_ids = [
        product_id
        for product_id
        in product_ids
        if product_id
        not in prices_by_product
    ]

    if missing_product_ids:
        return JsonResponse(
            {
                "error":
                    "Для части товаров отсутствует "
                    "актуальная цена.",
            },
            status=400,
        )


    # =========================================================
    # Остатки по складам организации
    # =========================================================

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
                "error":
                    "Для организации договора "
                    "не настроены активные склады.",
            },
            status=400,
        )


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


    shortages = []

    for (
        product_id,
        quantity,
    ) in quantities.items():

        stock_quantity = (
            stock_by_product.get(
                product_id,
                Decimal("0"),
            )
        )

        if quantity > stock_quantity:

            product = (
                prices_by_product[
                    product_id
                ].product
            )

            shortages.append(
                {
                    "product_id":
                        product_id,

                    "name":
                        product.name,

                    "requested":
                        str(quantity),

                    "available":
                        str(stock_quantity),
                }
            )


    if shortages:
        return JsonResponse(
            {
                "error":
                    "Недостаточно товара на складе.",
                "shortages":
                    shortages,
            },
            status=409,
        )


    # =========================================================
    # Формируем строки
    # =========================================================

    customer_discount = Decimal(
        str(
            access.discount_percent
            or "0.00"
        )
    )

    promo_max_line = (
        OrderItem.objects
        .filter(
            order=order,
        )
        .filter(
            Q(is_promo_product=True)
            | Q(is_promo_gift=True)
        )
        .order_by(
            "-line_number"
        )
        .values_list(
            "line_number",
            flat=True,
        )
        .first()
        or 0
    )

    prepared_items = []

    total_amount = Decimal("0.00")


    for (
        line_number,
        (
            product_id,
            quantity,
        ),
    ) in enumerate(
        quantities.items(),
        start=(
            promo_max_line + 1
        ),
    ):

        price_row = (
            prices_by_product[
                product_id
            ]
        )

        product = (
            price_row.product
        )


        base_price = (
            Decimal(
                str(
                    price_row.price
                )
            )
            * currency_rate
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        final_price = (
            base_price
            * (
                Decimal("100.00")
                - customer_discount
            )
            / Decimal("100.00")
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        line_amount = (
            final_price
            * quantity
        ).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )


        total_amount += (
            line_amount
        )


        prepared_items.append(
            OrderItem(
                order=order,

                product=product,

                line_number=(
                    line_number
                ),

                product_name=(
                    product.name
                    or ""
                ),

                product_name_translation=(
                    product.name_translation
                    or ""
                ),

                article=(
                    product.article
                    or ""
                ),

                quantity=quantity,

                price=final_price,

                discount_percent=(
                    customer_discount
                ),

                amount=line_amount,

                promo_id=None,
                promo_name="",

                is_promo_product=False,
                is_promo_gift=False,
            )
        )


    # =========================================================
    # Сохраняем атомарно
    # =========================================================

    with transaction.atomic():

        OrderItem.objects.filter(
            order=order,
            is_promo_product=False,
            is_promo_gift=False,
        ).delete()


        OrderItem.objects.bulk_create(
            prepared_items
        )


        promo_amount = (
            OrderItem.objects
            .filter(
                order=order,
            )
            .aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )


        order.amount = (
            promo_amount
        )

        order.current_step = max(
            order.current_step,
            2,
        )

        order.price_type = (
            access.price_type
        )

        order.discount_percent = (
            customer_discount
        )

        order.save(
            update_fields=[
                "amount",
                "current_step",
                "price_type",
                "discount_percent",
                "updated_at",
            ]
        )


    return JsonResponse(
        {
            "order_id":
                str(order.pk),

            "items_count":
                len(prepared_items),

            "amount":
                str(order.amount),

            "current_step":
                order.current_step,
        }
    )

@login_required
@require_POST
def save_draft_promotions(
    request,
    order_id,
):

    # =========================================================
    # Черновик
    # =========================================================

    order = (
        Order.objects
        .select_related(
            "customer",
            "contract",
            "price_type",
        )
        .filter(
            pk=order_id,
            user=request.user,
            status=Order.STATUS_DRAFT,
            contract__brand=request.brand.brand_id,
        )
        .first()
    )

    if order is None:
        return JsonResponse(
            {
                "error":
                    "Черновик заказа не найден "
                    "или недоступен.",
            },
            status=404,
        )


    # =========================================================
    # JSON
    # =========================================================

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error": "Некорректный JSON.",
            },
            status=400,
        )


    raw_promotions = (
        payload.get("promotions")
        or []
    )

    if not isinstance(
        raw_promotions,
        list,
    ):
        return JsonResponse(
            {
                "error":
                    "Некорректный список промоакций.",
            },
            status=400,
        )


    # =========================================================
    # Доступ клиента
    # =========================================================

    access = (
        UserLegalEntityAccess.objects
        .filter(
            user=request.user,
            legal_entity=order.customer,
            is_active=True,
            legal_entity__is_active=True,
        )
        .select_related(
            "price_type"
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
                "error":
                    "Для клиента не назначен тип цен.",
            },
            status=400,
        )


    contract = order.contract

    if (
        not contract.is_active
        or contract.brand
        != request.brand.brand_id
    ):
        return JsonResponse(
            {
                "error": "Договор недоступен.",
            },
            status=400,
        )


    # =========================================================
    # Нормализуем список промо
    # =========================================================

    promotions_to_save = {}

    for item in raw_promotions:

        if not isinstance(
            item,
            dict,
        ):
            continue

        promo_id = str(
            item.get(
                "promo_id",
                "",
            )
        ).strip()

        try:
            quantity = int(
                item.get(
                    "quantity",
                    0,
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            quantity = 0

        if (
            not promo_id
            or quantity <= 0
        ):
            continue

        promotions_to_save[
            promo_id
        ] = quantity


    # =========================================================
    # Если все промо удалены
    # =========================================================

    if not promotions_to_save:

        with transaction.atomic():

            OrderItem.objects.filter(
                order=order,
            ).filter(
                Q(is_promo_product=True)
                | Q(is_promo_gift=True)
            ).delete()


            order.amount = (
                OrderItem.objects
                .filter(
                    order=order,
                )
                .aggregate(
                    total=Sum("amount")
                )["total"]
                or Decimal("0.00")
            )

            order.current_step = max(
                order.current_step,
                3,
            )

            order.save(
                update_fields=[
                    "amount",
                    "current_step",
                    "updated_at",
                ]
            )


        return JsonResponse(
            {
                "order_id":
                    str(order.pk),

                "promotions_count":
                    0,

                "promo_items_count":
                    0,

                "amount":
                    str(order.amount),

                "current_step":
                    order.current_step,
            }
        )


    # =========================================================
    # Курс YE
    # =========================================================

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
                "error":
                    "Не найден действующий курс валюты YE.",
            },
            status=500,
        )

    currency_rate = Decimal(
        str(
            currency_rate_row.rate
        )
    )

    customer_discount = Decimal(
        str(
            access.discount_percent
            or "0.00"
        )
    )


    # =========================================================
    # Получаем действующие промо
    # =========================================================

    now = timezone.now()

    promotions = (
        PromoAction.objects
        .filter(
            pk__in=list(
                promotions_to_save.keys()
            ),
            brand_id=contract.brand,
            is_active=True,
        )
        .filter(
            Q(valid_from__isnull=True)
            | Q(valid_from__lte=now)
        )
        .filter(
            Q(valid_to__isnull=True)
            | Q(valid_to__gte=now)
        )
        .prefetch_related(
            Prefetch(
                "condition_products",
                queryset=(
                    PromoActionProduct.objects
                    .select_related(
                        "product"
                    )
                ),
            ),
            Prefetch(
                "gift_products",
                queryset=(
                    PromoGiftProduct.objects
                    .select_related(
                        "product"
                    )
                ),
            ),
        )
    )


    promotions_by_id = {
        str(promo.pk):
            promo
        for promo in promotions
    }


    missing_promotions = [
        promo_id
        for promo_id
        in promotions_to_save
        if promo_id
        not in promotions_by_id
    ]

    if missing_promotions:
        return JsonResponse(
            {
                "error":
                    "Одна из выбранных промоакций "
                    "больше недоступна.",
            },
            status=409,
        )


    # =========================================================
    # Готовим строки
    # =========================================================

    prepared_items = []


    for (
        promo_id,
        promo_quantity,
    ) in promotions_to_save.items():

        promo = (
            promotions_by_id[
                promo_id
            ]
        )


        # Пока сохраняем только fixed_set.
        if (
            promo.condition_type
            != PromoAction.CONDITION_FIXED_SET
        ):
            return JsonResponse(
                {
                    "error": (
                        f'Промо "{promo.name}" '
                        "пока не поддерживается "
                        "для сохранения черновика."
                    ),
                },
                status=409,
            )


        condition_rows = list(
            promo.condition_products.all()
        )

        if not condition_rows:
            return JsonResponse(
                {
                    "error": (
                        f'Для промо "{promo.name}" '
                        "не задан состав товаров."
                    ),
                },
                status=500,
            )


        # -----------------------------------------------------
        # Цены платных товаров промо
        # -----------------------------------------------------

        promo_product_ids = [
            row.product_id
            for row
            in condition_rows
        ]


        price_rows = (
            Price.objects
            .filter(
                price_type_id=(
                    access.price_type_id
                ),
                product_id__in=(
                    promo_product_ids
                ),
                product__brand_id=(
                    contract.brand
                ),
                product__is_active=True,
            )
            .select_related(
                "product"
            )
        )


        prices_by_product = {
            str(row.product_id):
                row
            for row
            in price_rows
        }


        missing_prices = [
            row.product.name
            for row
            in condition_rows
            if str(row.product_id)
            not in prices_by_product
        ]


        if missing_prices:
            return JsonResponse(
                {
                    "error": (
                        f'Для товаров промо "{promo.name}" '
                        "не найдены актуальные цены."
                    ),
                },
                status=409,
            )


        # -----------------------------------------------------
        # Платный состав
        # -----------------------------------------------------

        for row in condition_rows:

            price_row = (
                prices_by_product[
                    str(row.product_id)
                ]
            )

            product = (
                price_row.product
            )


            base_price = (
                Decimal(
                    str(
                        price_row.price
                    )
                )
                * currency_rate
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            applied_discount = (
                customer_discount
            )

            if (
                promo.reward_type
                == PromoAction.REWARD_DISCOUNT
            ):
                applied_discount = Decimal(
                    str(
                        promo.discount_percent
                        or "0.00"
                    )
                )


            final_price = (
                base_price
                * (
                    Decimal("100.00")
                    - applied_discount
                )
                / Decimal("100.00")
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            quantity = (
                Decimal(
                    str(
                        row.quantity
                    )
                )
                * Decimal(
                    str(
                        promo_quantity
                    )
                )
            )


            line_amount = (
                final_price
                * quantity
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            prepared_items.append(
                {
                    "product":
                        product,

                    "quantity":
                        quantity,

                    "price":
                        final_price,

                    "discount_percent":
                        applied_discount,

                    "amount":
                        line_amount,

                    "promo_id":
                        promo_id,

                    "promo_name":
                        promo.name,

                    "is_promo_product":
                        True,

                    "is_promo_gift":
                        False,
                }
            )


        # -----------------------------------------------------
        # Подарки
        # -----------------------------------------------------

        if (
            promo.reward_type
            == PromoAction.REWARD_GIFT
        ):

            for row in (
                promo.gift_products.all()
            ):

                product = (
                    row.product
                )

                quantity = (
                    Decimal(
                        str(
                            row.quantity
                        )
                    )
                    * Decimal(
                        str(
                            promo_quantity
                        )
                    )
                )


                prepared_items.append(
                    {
                        "product":
                            product,

                        "quantity":
                            quantity,

                        "price":
                            Decimal("0.00"),

                        "discount_percent":
                            Decimal("0.00"),

                        "amount":
                            Decimal("0.00"),

                        "promo_id":
                            promo_id,

                        "promo_name":
                            promo.name,

                        "is_promo_product":
                            False,

                        "is_promo_gift":
                            True,
                    }
                )


    # =========================================================
    # Запись
    # =========================================================

    with transaction.atomic():

        # Полностью заменяем только промо-строки.
        # Обычные товары шага 2 остаются нетронутыми.

        OrderItem.objects.filter(
            order=order,
        ).filter(
            Q(is_promo_product=True)
            | Q(is_promo_gift=True)
        ).delete()


        # Продолжаем нумерацию после обычных строк.

        max_regular_line = (
            OrderItem.objects
            .filter(
                order=order,
                is_promo_product=False,
                is_promo_gift=False,
            )
            .order_by(
                "-line_number"
            )
            .values_list(
                "line_number",
                flat=True,
            )
            .first()
            or 0
        )


        order_items = []

        line_number = (
            max_regular_line
            + 1
        )


        for item in prepared_items:

            product = (
                item["product"]
            )


            order_items.append(
                OrderItem(
                    order=order,

                    product=product,

                    line_number=(
                        line_number
                    ),

                    product_name=(
                        product.name
                        or ""
                    ),

                    product_name_translation=(
                        product.name_translation
                        or ""
                    ),

                    article=(
                        product.article
                        or ""
                    ),

                    quantity=(
                        item["quantity"]
                    ),

                    price=(
                        item["price"]
                    ),

                    discount_percent=(
                        item[
                            "discount_percent"
                        ]
                    ),

                    amount=(
                        item["amount"]
                    ),

                    promo_id=(
                        item["promo_id"]
                    ),

                    promo_name=(
                        item["promo_name"]
                    ),

                    is_promo_product=(
                        item[
                            "is_promo_product"
                        ]
                    ),

                    is_promo_gift=(
                        item[
                            "is_promo_gift"
                        ]
                    ),
                )
            )

            line_number += 1


        OrderItem.objects.bulk_create(
            order_items
        )


        order.amount = (
            OrderItem.objects
            .filter(
                order=order,
            )
            .aggregate(
                total=Sum("amount")
            )["total"]
            or Decimal("0.00")
        )


        order.current_step = max(
            order.current_step,
            3,
        )


        order.save(
            update_fields=[
                "amount",
                "current_step",
                "updated_at",
            ]
        )


    return JsonResponse(
        {
            "order_id":
                str(order.pk),

            "promotions_count":
                len(
                    promotions_to_save
                ),

            "promo_items_count":
                len(
                    order_items
                ),

            "amount":
                str(order.amount),

            "current_step":
                order.current_step,
        }
    )

def renumber_order_items(order):

    items = list(
        OrderItem.objects
        .filter(order=order)
        .order_by(
            "is_promo_product",
            "is_promo_gift",
            "line_number",
            "id",
        )
    )

    for index, item in enumerate(
        items,
        start=1,
    ):
        item.line_number = index

    OrderItem.objects.bulk_update(
        items,
        ["line_number"],
    )    


@login_required
@require_POST
def save_draft_shipping(
    request,
    order_id,
):

    # =========================================================
    # Черновик
    # =========================================================

    order = (
        Order.objects
        .select_related(
            "customer",
            "contract",
            "contract__manager",
            "contract__manager__department",
        )
        .filter(
            pk=order_id,
            user=request.user,
            status=Order.STATUS_DRAFT,
            contract__brand=request.brand.brand_id,
        )
        .first()
    )

    if order is None:
        return JsonResponse(
            {
                "error":
                    "Черновик заказа не найден "
                    "или недоступен.",
            },
            status=404,
        )


    # =========================================================
    # JSON
    # =========================================================

    try:
        payload = json.loads(
            request.body.decode("utf-8")
        )

    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
    ):
        return JsonResponse(
            {
                "error":
                    "Некорректный JSON.",
            },
            status=400,
        )


    shipping_type = str(
        payload.get(
            "shipping_type",
            "",
        )
    ).strip()

    shipping_date_raw = str(
        payload.get(
            "shipping_date",
            "",
        )
    ).strip()

    delivery_address_id = str(
        payload.get(
            "delivery_address_id",
            "",
        )
        or ""
    ).strip()

    comment = str(
        payload.get(
            "comment",
            "",
        )
        or ""
    ).strip()


    # =========================================================
    # Способ отгрузки
    # =========================================================

    if shipping_type not in {
        Order.SHIPPING_PICKUP,
        Order.SHIPPING_DELIVERY,
    }:
        return JsonResponse(
            {
                "error":
                    "Некорректный способ отгрузки.",
            },
            status=400,
        )


    # =========================================================
    # Дата
    # =========================================================

    try:
        shipping_date = (
            datetime.strptime(
                shipping_date_raw,
                "%Y-%m-%d",
            ).date()
        )

    except ValueError:
        return JsonResponse(
            {
                "error":
                    "Некорректная дата отгрузки.",
            },
            status=400,
        )


    # =========================================================
    # Проверяем минимальную разрешённую дату
    # =========================================================

    if (
        shipping_type
        == Order.SHIPPING_PICKUP
    ):

        min_shipping_date = (
            get_pickup_min_date()
        )

    else:

        min_shipping_date = (
            get_delivery_min_date()
        )


    if shipping_date < min_shipping_date:

        return JsonResponse(
            {
                "error": (
                    "Выбранная дата отгрузки "
                    "недоступна."
                ),

                "min_date":
                    min_shipping_date.isoformat(),
            },
            status=400,
        )


    # =========================================================
    # Проверяем, что выбранный день рабочий
    # =========================================================

    if not is_working_day(
        shipping_date
    ):
        return JsonResponse(
            {
                "error":
                    "Отгрузка в выбранный день "
                    "недоступна.",
            },
            status=400,
        )


    # =========================================================
    # Адрес / доставка
    # =========================================================

    delivery_address = None


    if (
        shipping_type
        == Order.SHIPPING_DELIVERY
    ):

        if not delivery_address_id:
            return JsonResponse(
                {
                    "error":
                        "Не указан адрес доставки.",
                },
                status=400,
            )


        delivery_address = (
            LegalEntityDeliveryAddress.objects
            .filter(
                pk=delivery_address_id,
                legal_entity=order.customer,
                is_active=True,
            )
            .first()
        )


        if delivery_address is None:
            return JsonResponse(
                {
                    "error":
                        "Адрес доставки недоступен.",
                },
                status=400,
            )


        # =====================================================
        # Проверяем возможность доставки по сумме
        # =====================================================

        manager = (
            order.contract.manager
        )


        if manager is None:
            return JsonResponse(
                {
                    "error":
                        "Для договора не указан менеджер.",
                },
                status=400,
            )


        department = (
            manager.department
        )


        if (
            department is None
            or not department.is_active
        ):
            return JsonResponse(
                {
                    "error":
                        "Для заказа недоступна доставка.",
                },
                status=400,
            )


        min_delivery_amount = (
            department.min_delivery_amount
            or Decimal("0.00")
        )


        if (
            order.amount
            < min_delivery_amount
        ):
            return JsonResponse(
                {
                    "error": (
                        "Недостаточная сумма "
                        "для доставки."
                    ),

                    "order_amount":
                        str(order.amount),

                    "min_delivery_amount":
                        str(
                            min_delivery_amount
                        ),
                },
                status=400,
            )


    # =========================================================
    # Сохраняем
    # =========================================================

    order.shipping_type = (
        shipping_type
    )

    order.shipping_date = (
        shipping_date
    )

    order.delivery_address = (
        delivery_address
    )

    order.comment = (
        comment
    )

    order.current_step = max(
        order.current_step,
        4,
    )


    order.save(
        update_fields=[
            "shipping_type",
            "shipping_date",
            "delivery_address",
            "comment",
            "current_step",
            "updated_at",
        ]
    )


    return JsonResponse(
        {
            "order_id":
                str(order.pk),

            "shipping_type":
                order.shipping_type,

            "shipping_date":
                order.shipping_date.isoformat(),

            "delivery_address_id": (
                str(
                    order.delivery_address_id
                )
                if order.delivery_address_id
                else None
            ),

            "comment":
                order.comment,

            "amount":
                str(order.amount),

            "current_step":
                order.current_step,
        }
    )    

@login_required
@require_POST
def confirm_order_draft(
    request,
    order_id,
):

    try:

        with transaction.atomic():

            # =================================================
            # Блокируем заказ на время подтверждения
            # =================================================

            order = (
                Order.objects
                .select_for_update(
                    of=("self",)
                )
                .select_related(
                    "customer",
                    "contract",
                    "contract__manager",
                    "contract__manager__department",
                    "price_type",
                    "delivery_address",
                )
                .filter(
                    pk=order_id,
                    user=request.user,
                    contract__brand=(
                        request.brand.brand_id
                    ),
                )
                .first()
            )


            if order is None:
                return JsonResponse(
                    {
                        "error":
                            "Заказ не найден "
                            "или недоступен.",
                    },
                    status=404,
                )


            # =================================================
            # Статус
            # =================================================

            if (
                order.status
                != Order.STATUS_DRAFT
            ):

                return JsonResponse(
                    {
                        "error":
                            "Заказ уже оформлен "
                            "или недоступен для изменения.",
                    },
                    status=409,
                )


            # =================================================
            # Доступ пользователя к клиенту
            # =================================================

            access = (
                UserLegalEntityAccess.objects
                .filter(
                    user=request.user,
                    legal_entity=order.customer,
                    is_active=True,
                    legal_entity__is_active=True,
                )
                .select_related(
                    "price_type"
                )
                .first()
            )


            if access is None:

                return JsonResponse(
                    {
                        "error":
                            "Клиент больше недоступен.",
                    },
                    status=403,
                )


            if access.price_type_id is None:

                return JsonResponse(
                    {
                        "error":
                            "Для клиента не назначен "
                            "тип цен.",
                    },
                    status=400,
                )


            # =================================================
            # Форма оплаты
            # =================================================

            if (
                order.customer.allowed_payment_method
                != order.payment_method
            ):

                return JsonResponse(
                    {
                        "error":
                            "Форма оплаты не соответствует "
                            "типу клиента.",
                    },
                    status=400,
                )


            # =================================================
            # Договор
            # =================================================

            contract = order.contract


            if (
                not contract.is_active
                or contract.brand
                != request.brand.brand_id
            ):

                return JsonResponse(
                    {
                        "error":
                            "Договор больше недоступен.",
                    },
                    status=400,
                )


            if not contract.organization_id:

                return JsonResponse(
                    {
                        "error":
                            "Для договора не указана "
                            "организация.",
                    },
                    status=400,
                )


            # =================================================
            # Строки заказа
            # =================================================

            items = list(
                OrderItem.objects
                .select_related(
                    "product"
                )
                .filter(
                    order=order,
                )
                .order_by(
                    "line_number"
                )
            )


            if not items:

                return JsonResponse(
                    {
                        "error":
                            "В заказе нет товаров.",
                    },
                    status=400,
                )


            # =================================================
            # Проверяем строки
            # =================================================

            for item in items:

                if item.quantity <= 0:

                    return JsonResponse(
                        {
                            "error": (
                                "В заказе обнаружена строка "
                                "с некорректным количеством."
                            ),
                        },
                        status=400,
                    )


                if (
                    item.product is None
                    or not item.product.is_active
                ):

                    return JsonResponse(
                        {
                            "error": (
                                "Один из товаров заказа "
                                "больше недоступен."
                            ),
                        },
                        status=400,
                    )


            # =================================================
            # Остатки
            #
            # Подарки тоже являются физическим товаром,
            # поэтому участвуют в проверке остатка.
            # =================================================

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
                        "error":
                            "Для организации договора "
                            "не настроены активные склады.",
                    },
                    status=400,
                )


            quantities_by_product = {}


            for item in items:

                product_id = str(
                    item.product_id
                )

                quantities_by_product[
                    product_id
                ] = (
                    quantities_by_product.get(
                        product_id,
                        Decimal("0"),
                    )
                    + item.quantity
                )


            stock_rows = (
                StockBalance.objects
                .filter(
                    warehouse_id__in=(
                        warehouse_ids
                    ),
                    product_id__in=(
                        quantities_by_product.keys()
                    ),
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
                for row
                in stock_rows
            }


            shortages = []


            for (
                product_id,
                quantity,
            ) in quantities_by_product.items():

                available = (
                    stock_by_product.get(
                        product_id,
                        Decimal("0"),
                    )
                )


                if quantity > available:

                    product_name = next(
                        (
                            item.product_name
                            for item
                            in items
                            if str(
                                item.product_id
                            ) == product_id
                        ),
                        product_id,
                    )


                    shortages.append(
                        {
                            "product_id":
                                product_id,

                            "name":
                                product_name,

                            "requested":
                                str(quantity),

                            "available":
                                str(available),
                        }
                    )


            if shortages:

                return JsonResponse(
                    {
                        "error":
                            "Недостаточно товара "
                            "на складе.",

                        "shortages":
                            shortages,
                    },
                    status=409,
                )


            # =================================================
            # Пересчитываем сумму именно из OrderItem
            # =================================================

            order_amount = sum(
                (
                    item.amount
                    for item
                    in items
                ),
                Decimal("0.00"),
            ).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )


            if order_amount <= 0:

                return JsonResponse(
                    {
                        "error":
                            "Сумма заказа должна быть "
                            "больше нуля.",
                    },
                    status=400,
                )


            # =================================================
            # Способ отгрузки
            # =================================================

            if order.shipping_type not in {
                Order.SHIPPING_PICKUP,
                Order.SHIPPING_DELIVERY,
            }:

                return JsonResponse(
                    {
                        "error":
                            "Не указан способ отгрузки.",
                    },
                    status=400,
                )


            if order.shipping_date is None:

                return JsonResponse(
                    {
                        "error":
                            "Не указана дата отгрузки.",
                    },
                    status=400,
                )


            # =================================================
            # Минимальная дата
            # =================================================

            if (
                order.shipping_type
                == Order.SHIPPING_PICKUP
            ):

                min_shipping_date = (
                    get_pickup_min_date()
                )

            else:

                min_shipping_date = (
                    get_delivery_min_date()
                )


            if (
                order.shipping_date
                < min_shipping_date
            ):

                return JsonResponse(
                    {
                        "error":
                            "Дата отгрузки больше "
                            "не доступна.",

                        "min_date":
                            min_shipping_date.isoformat(),
                    },
                    status=400,
                )


            if not is_working_day(
                order.shipping_date
            ):

                return JsonResponse(
                    {
                        "error":
                            "Выбранная дата отгрузки "
                            "является нерабочей.",
                    },
                    status=400,
                )


            # =================================================
            # Доставка
            # =================================================

            if (
                order.shipping_type
                == Order.SHIPPING_DELIVERY
            ):

                if (
                    order.delivery_address_id
                    is None
                ):

                    return JsonResponse(
                        {
                            "error":
                                "Не указан адрес доставки.",
                        },
                        status=400,
                    )


                address_valid = (
                    LegalEntityDeliveryAddress.objects
                    .filter(
                        pk=(
                            order.delivery_address_id
                        ),
                        legal_entity=order.customer,
                        is_active=True,
                    )
                    .exists()
                )


                if not address_valid:

                    return JsonResponse(
                        {
                            "error":
                                "Адрес доставки "
                                "больше недоступен.",
                        },
                        status=400,
                    )


                manager = (
                    contract.manager
                )


                if manager is None:

                    return JsonResponse(
                        {
                            "error":
                                "Для договора "
                                "не указан менеджер.",
                        },
                        status=400,
                    )


                department = (
                    manager.department
                )


                if (
                    department is None
                    or not department.is_active
                ):

                    return JsonResponse(
                        {
                            "error":
                                "Для заказа "
                                "недоступна доставка.",
                        },
                        status=400,
                    )


                min_delivery_amount = (
                    department.min_delivery_amount
                    or Decimal("0.00")
                )


                if (
                    order_amount
                    < min_delivery_amount
                ):

                    return JsonResponse(
                        {
                            "error":
                                "Недостаточная сумма "
                                "для доставки.",

                            "order_amount":
                                str(order_amount),

                            "min_delivery_amount":
                                str(
                                    min_delivery_amount
                                ),
                        },
                        status=400,
                    )


            # =================================================
            # Самовывоз
            # =================================================

            else:

                # У черновика мог сохраниться адрес
                # от ранее выбранной доставки.

                order.delivery_address = None


            # =================================================
            # Финальная запись
            # =================================================

            order.amount = (
                order_amount
            )

            order.status = (
                Order.STATUS_CONFIRMED
            )


            order.save(
                update_fields=[
                    "amount",
                    "status",
                    "delivery_address",
                    "updated_at",
                ]
            )


            return JsonResponse(
                {
                    "order_id":
                        str(order.pk),

                    "number":
                        order.number,

                    "status":
                        order.status,

                    "status_name":
                        order.get_status_display(),

                    "amount":
                        str(order.amount),

                    "redirect_url":
                        reverse(
                            "order_detail",
                            kwargs={
                                "order_id":
                                    order.pk,
                            },
                        ),
                }
            )


    except Exception as exc:

        import traceback

        traceback.print_exc()

        return JsonResponse(
            {
                "error": str(exc),
                "exception_type": (
                    type(exc).__name__
                ),
            },
            status=500,
        )


@login_required
def order_draft_edit(
    request,
    order_id,
):

    order = (
        Order.objects
        .select_related(
            "customer",
            "contract",
            "price_type",
            "delivery_address",
        )
        .filter(
            pk=order_id,
            user=request.user,
            status=Order.STATUS_DRAFT,
            contract__brand=request.brand.brand_id,
        )
        .first()
    )


    if order is None:
        raise Http404(
            "Черновик заказа не найден."
        )


    form = OrderCreateForm(
        instance=order,
        user=request.user,
        brand=request.brand,
    )


    return render(
        request,
        "orders/order_create.html",
        {
            "form":
                form,

            "draft_order":
                order,

            "draft_order_id":
                str(order.pk),

            "draft_current_step":
                order.current_step,
        },
    )
