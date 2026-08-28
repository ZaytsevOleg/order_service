from django.contrib.auth.decorators import login_required
from django.shortcuts import (
    get_object_or_404,
    redirect,
    render,
)

from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from django.db.models import Q, Prefetch, Sum
from django.http import JsonResponse

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
from sales.models import Order
import json
from .forms import OrderCreateForm
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from orders.services.promo_engine import PromoEngine


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
                        customer.name,

                    "client_type":
                        customer.client_type,

                    "client_type_name":
                        customer.get_client_type_display(),
                }
                for customer in customers
            ],
        }
    )