from django.db import models
from django.contrib.auth.models import User
from django.core.validators import (
    MinValueValidator,
    MaxValueValidator,
)


class Brand(models.Model):
    brand_id = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name="Идентификатор бренда в 1С",
    )

    name = models.CharField(
        max_length=100,
        unique=True,
        verbose_name="Название",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    class Meta:
        ordering = ("name",)
        verbose_name = "Бренд"
        verbose_name_plural = "Бренды"

    def __str__(self):
        return self.name



class PriceType(models.Model):
    price_type_id = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name="Идентификатор типа цен в 1С"
    )

    name = models.CharField(
        max_length=255,
        verbose_name="Наименование типа цен"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен"
    )

    class Meta:
        verbose_name = "Тип цен"
        verbose_name_plural = "Типы цен"
        ordering = ("name",)

    def __str__(self):
        return self.name
    


class LegalEntity(models.Model):
    CLIENT_TYPE_LLC = "llc"
    CLIENT_TYPE_IE = "ie"
    CLIENT_TYPE_PERSON = "person"

    CLIENT_TYPE_CHOICES = [
        (CLIENT_TYPE_LLC, "ООО"),
        (CLIENT_TYPE_IE, "ИП"),
        (CLIENT_TYPE_PERSON, "Физическое лицо"),
    ]

    legal_entity_id = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name="Идентификатор клиента в 1С",
    )

    name = models.CharField(
        max_length=500,
        verbose_name="Наименование",
    )

    full_name = models.CharField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name="Полное наименование",
    )

    client_type = models.CharField(
        max_length=20,
        choices=CLIENT_TYPE_CHOICES,
        verbose_name="Тип клиента",
    )

    inn = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="ИНН",
    )

    kpp = models.CharField(
        max_length=20,
        blank=True,
        null=True,
        verbose_name="КПП",
    )


    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Клиент"
        verbose_name_plural = "Клиенты"
        ordering = ("name",)

    def __str__(self):
        return self.name
    
    @property
    def allowed_payment_method(self):
        if self.client_type in {
            self.CLIENT_TYPE_LLC,
            self.CLIENT_TYPE_IE,
        }:
            return "cashless"

        if self.client_type == self.CLIENT_TYPE_PERSON:
            return "cash"

        return None

    @property
    def allowed_payment_method_display(self):
        payment_methods = {
            "cash": "Наличные",
            "cashless": "Безналичная оплата",
        }

        return payment_methods.get(
            self.allowed_payment_method,
            "Не определено",
        )


class UserLegalEntityAccess(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="legal_entities",
        verbose_name="Пользователь",
    )

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="customer_accesses",
        verbose_name="Клиент",
    )

    price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        blank=True,
        null=True,
        related_name="legal_entities",
        verbose_name="Тип цен",
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Скидка, %",
    )

    is_default = models.BooleanField(
        default=False,
        verbose_name="По умолчанию",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "legal_entity"),
                name="unique_user_legal_entity",
            )
        ]
        verbose_name = "Доступ пользователя к клиенту"
        verbose_name_plural = "Доступы пользователей к клиентам"

    def __str__(self):
        return f"{self.user.username} — {self.legal_entity.name}"


class LegalEntityDeliveryAddress(models.Model):
    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="delivery_addresses",
        verbose_name="Клиент",
    )

    address_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        verbose_name="Идентификатор адреса в 1С",
    )

    address = models.TextField(
        verbose_name="Адрес",
    )

    is_default = models.BooleanField(
        default=False,
        verbose_name="По умолчанию",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("legal_entity", "address_id"),
                name="unique_legal_entity_delivery_address",
            ),
        ]
        verbose_name = "Адрес доставки"
        verbose_name_plural = "Адреса доставки"
        ordering = ("address",)

    def __str__(self):
        return self.address


class Contract(models.Model):
    BRAND_GUINOT = "e3154c7c-4423-11e9-8120-a21e6608e067"
    BRAND_RHEA = "e3154c7d-4423-11e9-8120-a21e6608e067"

    BRAND_CHOICES = [
        (BRAND_GUINOT, "Guinot"),
        (BRAND_RHEA, "Rhea cosmetics"),
    ]

    legal_entity = models.ForeignKey(
        LegalEntity,
        on_delete=models.CASCADE,
        related_name="contracts",
        verbose_name="Клиент",
    )

    contract_id = models.CharField(
        max_length=255,
        verbose_name="Идентификатор договора в 1С"
    )

    organization_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Организация в 1С",
        help_text=(
            "UID организации из 1С. "
            "Используется для определения складов "
            "и остатков по договору."
        ),
    )

    contract_name = models.CharField(
        max_length=500,
        verbose_name="Наименование договора"
    )

    brand = models.CharField(
        max_length=50,
        choices=BRAND_CHOICES,
        verbose_name="Бренд"
    )

    is_default = models.BooleanField(
        default=False,
        verbose_name="По умолчанию"
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("legal_entity", "brand"),
                name="unique_legal_entity_brand_contract",
            )
        ]
        verbose_name = "Договор"
        verbose_name_plural = "Договоры"
        ordering = ("contract_name",)

    def __str__(self):
        return f"{self.contract_name} — {self.get_brand_display()}"


class Product(models.Model):
    product_id = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name="Идентификатор товара в 1С",
    )

    code = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Код в 1С",
    )

    article = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Артикул",
    )

    source_name = models.CharField(
        max_length=1000,
        blank=True,
        null=True,
        verbose_name="Исходное наименование из 1С",
    )

    name = models.CharField(
        max_length=500,
        verbose_name="Наименование",
    )

    name_translation = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Перевод наименования",
    )

    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="products",
        verbose_name="Бренд",
    )

    category = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Категория",
    )

    subcategory = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Подкатегория",
    )

    level_2 = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Уровень иерархии 2",
    )

    level_3 = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Уровень иерархии 3",
    )

    level_4 = models.CharField(
        max_length=500,
        blank=True,
        null=True,
        verbose_name="Уровень иерархии 4",
    )

    description = models.TextField(
        blank=True,
        null=True,
        verbose_name="Описание",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Активен",
    )

    is_customer_selectable = models.BooleanField(
        default=False,
        db_index=True,
        verbose_name="Доступен для выбора клиентом",
        help_text=(
            "Управляется приложением. "
            "При повторной синхронизации Airflow значение не изменяется."
        ),
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Товар"
        verbose_name_plural = "Товары"
        ordering = ("name",)

    def __str__(self):
        return self.name


class Price(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="prices",
        verbose_name="Товар"
    )

    price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        related_name="prices",
        verbose_name="Тип цен",
    )

    price = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        verbose_name="Цена"
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено"
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("product", "price_type"),
                name="unique_product_price_type"
            )
        ]
        verbose_name = "Цена"
        verbose_name_plural = "Цены"

    def __str__(self):
        return f"{self.product.name} — {self.price_type.name}: {self.price}"


class CurrencyRate(models.Model):
    currency_code = models.CharField(
        max_length=10,
        default="YE",
        db_index=True,
        verbose_name="Валюта",
    )

    rate = models.DecimalField(
        max_digits=12,
        decimal_places=4,
        verbose_name="Курс к рублю",
    )

    valid_from = models.DateField(
        db_index=True,
        verbose_name="Действует с",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создан",
    )

    class Meta:
        verbose_name = "Курс валюты"
        verbose_name_plural = "Курсы валют"
        ordering = (
            "-valid_from",
            "-id",
        )
        constraints = [
            models.UniqueConstraint(
                fields=(
                    "currency_code",
                    "valid_from",
                ),
                name=(
                    "unique_currency_rate_date"
                ),
            ),
        ]

    def __str__(self):
        return (
            f"{self.currency_code}: "
            f"{self.rate} "
            f"с {self.valid_from:%d.%m.%Y}"
        )
    

class Warehouse(models.Model):
    warehouse_id = models.CharField(
        max_length=255,
        primary_key=True,
        verbose_name="Идентификатор склада в 1С",
    )

    organization_id = models.CharField(
        max_length=255,
        db_index=True,
        verbose_name="Организация в 1С",
    )

    name = models.CharField(
        max_length=500,
        verbose_name="Наименование склада",
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Активен",
    )

    class Meta:
        verbose_name = "Склад"
        verbose_name_plural = "Склады"
        ordering = (
            "organization_id",
            "name",
        )

    def __str__(self):
        return self.name


class StockBalance(models.Model):
    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="stock_balances",
        verbose_name="Товар",
    )

    warehouse = models.ForeignKey(
        Warehouse,
        on_delete=models.CASCADE,
        related_name="stock_balances",
        verbose_name="Склад",
    )

    quantity = models.DecimalField(
        max_digits=14,
        decimal_places=3,
        default=0,
        verbose_name="Остаток",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлено",
    )

    class Meta:
        verbose_name = "Остаток товара"
        verbose_name_plural = "Остатки товаров"

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "product",
                    "warehouse",
                ),
                name="unique_product_warehouse_stock",
            ),
        ]

        indexes = [
            models.Index(
                fields=(
                    "warehouse",
                    "product",
                ),
                name="stock_warehouse_product_idx",
            ),
        ]

    def __str__(self):
        return (
            f"{self.product} / "
            f"{self.warehouse}: "
            f"{self.quantity}"
        )


class PromoAction(models.Model):

    # =========================================================
    # Тип условия выполнения акции
    # =========================================================

    CONDITION_FIXED_SET = "fixed_set"
    CONDITION_TOTAL_QUANTITY = "total_quantity"
    CONDITION_TOTAL_AMOUNT = "total_amount"

    CONDITION_TYPE_CHOICES = (
        (
            CONDITION_FIXED_SET,
            "Фиксированный состав",
        ),
        (
            CONDITION_TOTAL_QUANTITY,
            "Количество товаров из списка",
        ),
        (
            CONDITION_TOTAL_AMOUNT,
            "Сумма товаров из списка",
        ),
    )

    # =========================================================
    # Результат акции
    # =========================================================

    REWARD_GIFT = "gift"
    REWARD_DISCOUNT = "discount"

    REWARD_TYPE_CHOICES = (
        (
            REWARD_GIFT,
            "Подарок",
        ),
        (
            REWARD_DISCOUNT,
            "Скидка",
        ),
    )

    # =========================================================
    # Идентификатор
    # =========================================================

    promo_id = models.CharField(
        max_length=255,
        primary_key=True,
        editable=False,
        verbose_name="Идентификатор акции",
    )

    # =========================================================
    # Основная информация
    # =========================================================

    name = models.CharField(
        max_length=500,
        verbose_name="Название акции",
    )

    short_description = models.CharField(
        max_length=1000,
        blank=True,
        verbose_name="Краткое описание",
        help_text=(
            "Отображается непосредственно "
            "на карточке акции."
        ),
    )

    description = models.TextField(
        blank=True,
        verbose_name="Подробное описание",
        help_text=(
            "Отображается в окне «Подробнее»."
        ),
    )

    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="promo_actions",
        verbose_name="Бренд",
    )

    image = models.ImageField(
        upload_to="promo/",
        blank=True,
        null=True,
        verbose_name="Изображение",
        help_text=(
            "Основное изображение, "
            "отображаемое на карточке акции."
        ),
    )

    # =========================================================
    # Условие выполнения
    # =========================================================

    condition_type = models.CharField(
        max_length=30,
        choices=CONDITION_TYPE_CHOICES,
        default=CONDITION_FIXED_SET,
        db_index=True,
        verbose_name="Условие выполнения",
    )

    threshold_quantity = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Минимальное количество товаров",
        help_text=(
            "Используется для условия "
            "«Количество товаров из списка»."
        ),
    )

    threshold_amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Минимальная сумма, руб.",
        help_text=(
            "Используется для условия "
            "«Сумма товаров из списка». "
            "Сумма рассчитывается по базовым ценам "
            "до применения скидок."
        ),
    )

    # =========================================================
    # Результат акции
    # =========================================================

    reward_type = models.CharField(
        max_length=20,
        choices=REWARD_TYPE_CHOICES,
        default=REWARD_GIFT,
        db_index=True,
        verbose_name="Результат акции",
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        blank=True,
        null=True,
        verbose_name="Промо-скидка, %",
        help_text=(
            "Используется, если результат акции — "
            "скидка. Применяется только к товарам "
            "акции и не суммируется "
            "со скидкой клиента."
        ),
    )

    # =========================================================
    # Отображение акции клиенту
    # =========================================================

    show_progress = models.BooleanField(
        default=False,
        verbose_name="Показывать прогресс выполнения",
        help_text=(
            "Если включено, клиент увидит, "
            "сколько товаров или какой суммы "
            "не хватает до выполнения условий акции."
        ),
    )


    progress_threshold_percent = models.PositiveSmallIntegerField(
        default=50,
        validators=[
            MinValueValidator(1),
            MaxValueValidator(99),
        ],
        verbose_name="Показывать прогресс начиная с, %",
        help_text=(
            "Используется только если включено "
            "«Показывать прогресс выполнения». "
            "Например, 50 означает, что подсказка появится "
            "после выполнения 50% условий акции."
        ),
    )

    def _generate_promo_id(self):

        promo_ids = (
            PromoAction.objects
            .filter(
                promo_id__startswith="promo_"
            )
            .values_list(
                "promo_id",
                flat=True,
            )
        )

        max_number = 0

        for promo_id in promo_ids:

            try:
                number = int(
                    promo_id.removeprefix(
                        "promo_"
                    )
                )

                max_number = max(
                    max_number,
                    number,
                )

            except ValueError:
                continue

        return (
            f"promo_{max_number + 1:04d}"
        )

    def save(self, *args, **kwargs):

        if not self.promo_id:
            self.promo_id = (
                self._generate_promo_id()
            )

        super().save(
            *args,
            **kwargs
        )
    # =========================================================
    # Период действия
    # =========================================================

    valid_from = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Действует с",
    )

    valid_to = models.DateTimeField(
        blank=True,
        null=True,
        db_index=True,
        verbose_name="Действует до",
    )

    # =========================================================
    # Управление
    # =========================================================

    priority = models.PositiveIntegerField(
        default=100,
        db_index=True,
        verbose_name="Приоритет",
        help_text=(
            "Чем меньше значение, тем выше "
            "приоритет акции при пересечении условий."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        db_index=True,
        verbose_name="Активна",
    )

    # =========================================================
    # Служебные поля
    # =========================================================

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создана",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Обновлена",
    )

    # =========================================================
    # Meta
    # =========================================================

    class Meta:
        verbose_name = "Промо акция"
        verbose_name_plural = "Промо акции"

        ordering = (
            "priority",
            "-valid_from",
            "name",
        )

    def __str__(self):
        return self.name


class PromoActionProduct(models.Model):

    promo = models.ForeignKey(
        PromoAction,
        on_delete=models.CASCADE,
        related_name="condition_products",
        verbose_name="Промо акция",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="promo_conditions",
        verbose_name="Товар",
    )

    quantity = models.PositiveIntegerField(
        blank=True,
        null=True,
        verbose_name="Необходимое количество",
        help_text=(
            "Указывается только для акции "
            "с фиксированным составом. "
            "Для условий по общему количеству "
            "или сумме оставьте поле пустым."
        ),
    )

    class Meta:
        verbose_name = "Товар условия промо"
        verbose_name_plural = "Товары условия промо"

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "promo",
                    "product",
                ),
                name=(
                    "unique_promo_condition_product"
                ),
            ),
        ]

    def __str__(self):

        if self.quantity:
            return (
                f"{self.product} × "
                f"{self.quantity}"
            )

        return str(self.product)

class PromoGiftProduct(models.Model):

    promo = models.ForeignKey(
        PromoAction,
        on_delete=models.CASCADE,
        related_name="gift_products",
        verbose_name="Промо акция",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="promo_gifts",
        verbose_name="Подарок",
    )

    quantity = models.PositiveIntegerField(
        default=1,
        verbose_name="Количество в подарок",
    )

    class Meta:
        verbose_name = "Подарок промо"
        verbose_name_plural = "Подарки промо"

        constraints = [
            models.UniqueConstraint(
                fields=(
                    "promo",
                    "product",
                ),
                name="unique_promo_gift_product",
            ),
        ]

    def __str__(self):
        return (
            f"{self.product} × "
            f"{self.quantity}"
        )


class Department(models.Model):

    department_id = models.CharField(
        max_length=100,
        primary_key=True,
        verbose_name="Идентификатор подразделения",
    )

    name = models.CharField(
        max_length=255,
        verbose_name="Подразделение",
    )

    min_delivery_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0,
        verbose_name="Минимальная сумма для доставки",
        help_text=(
            "При меньшей сумме заказа клиенту "
            "будет доступен только самовывоз."
        ),
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активно",
    )

    class Meta:
        ordering = [
            "name",
        ]

        verbose_name = (
            "Подразделение"
        )

        verbose_name_plural = (
            "Подразделения"
        )

    def __str__(self):
        return self.name


class Manager(models.Model):

    manager_id = models.CharField(
        max_length=100,
        primary_key=True,
        verbose_name="Идентификатор менеджера",
    )

    name = models.CharField(
        max_length=255,
        verbose_name="Менеджер",
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        related_name="managers",
        verbose_name="Подразделение",
    )

    email = models.EmailField(
        blank=True,
        verbose_name="Email",
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
        verbose_name="Телефон",
    )

    bitrix_id = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="ID пользователя Bitrix24",
    )

    is_active = models.BooleanField(
        default=True,
        verbose_name="Активен",
    )

    class Meta:
        ordering = [
            "name",
        ]

        verbose_name = (
            "Менеджер"
        )

        verbose_name_plural = (
            "Менеджеры"
        )

    def __str__(self):
        return self.name


            