from django.db import models
from django.contrib.auth.models import User


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


class PromoAction(models.Model):
    promo_id = models.CharField(max_length=255, primary_key=True)
    name = models.CharField(max_length=500)
    description = models.TextField(blank=True, null=True)

    brand = models.ForeignKey(
        Brand,
        on_delete=models.PROTECT,
        related_name="promo_actions",
        verbose_name="Бренд",
    )

    date_from = models.DateField(blank=True, null=True)
    date_to = models.DateField(blank=True, null=True)

    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = "Промо акция"
        verbose_name_plural = "Промо акции"

    def __str__(self):
        return self.name
    
