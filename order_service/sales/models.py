import uuid
from datetime import time
from django.conf import settings
from django.db import models

from catalog.models import (
    Contract,
    LegalEntity,
    LegalEntityDeliveryAddress,
    Product,
    PriceType,
)


class Order(models.Model):
    STATUS_DRAFT = 1
    STATUS_APPROVAL = 2
    STATUS_CONFIRMED = 3
    STATUS_SHIPPING = 4
    STATUS_COMPLETED = 5

    STATUS_CHOICES = [
        (STATUS_DRAFT, "Черновик"),
        (STATUS_APPROVAL, "На согласовании"),
        (STATUS_CONFIRMED, "Оформлен"),
        (STATUS_SHIPPING, "Отгрузка"),
        (STATUS_COMPLETED, "Завершен"),
    ]

    PAYMENT_CASH = "cash"
    PAYMENT_CASHLESS = "cashless"

    PAYMENT_CHOICES = [
        (PAYMENT_CASH, "Наличные"),
        (PAYMENT_CASHLESS, "Безналичная оплата"),
    ]

    SHIPPING_PICKUP = "pickup"
    SHIPPING_DELIVERY = "delivery"

    SHIPPING_CHOICES = [
        (SHIPPING_PICKUP, "Самовывоз"),
        (SHIPPING_DELIVERY, "Доставка"),
    ]

    id = models.UUIDField(
        primary_key=True,
        default=uuid.uuid4,
        editable=False,
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Пользователь",
    )

    customer = models.ForeignKey(
        LegalEntity,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Клиент",
    )

    contract = models.ForeignKey(
        Contract,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Договор",
    )

    price_type = models.ForeignKey(
        PriceType,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Тип цен",
    )

    delivery_address = models.ForeignKey(
        LegalEntityDeliveryAddress,
        on_delete=models.PROTECT,
        related_name="orders",
        verbose_name="Адрес доставки",
        blank=True,
        null=True,
    )

    number = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Номер",
    )

    status = models.PositiveSmallIntegerField(
        choices=STATUS_CHOICES,
        default=STATUS_DRAFT,
        verbose_name="Статус",
    )

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_CHOICES,
        verbose_name="Форма оплаты",
    )

    shipping_type = models.CharField(
        max_length=20,
        choices=SHIPPING_CHOICES,
        verbose_name="Способ отгрузки",
    )
    shipping_date = models.DateField(
        blank=True,
        null=True,
        verbose_name="Дата отгрузки",
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Скидка, %",
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        default=0,
        verbose_name="Сумма",
    )

    comment = models.TextField(
        blank=True,
        verbose_name="Комментарий",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="Создан",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="Изменен",
    )

    sent_to_1c_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="Передан в 1С",
    )

    one_c_order_id = models.CharField(
        max_length=255,
        blank=True,
        null=True,
        unique=True,
        verbose_name="Идентификатор заказа в 1С",
    )

    class Meta:
        ordering = ("-created_at",)
        verbose_name = "Заказ"
        verbose_name_plural = "Заказы"

    def __str__(self):
        return self.number or str(self.pk)


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="Заказ",
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.PROTECT,
        related_name="order_items",
        verbose_name="Товар",
    )

    line_number = models.PositiveIntegerField(
        verbose_name="Номер строки",
    )

    product_name = models.CharField(
        max_length=500,
        verbose_name="Название товара",
    )

    article = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Артикул",
    )

    quantity = models.DecimalField(
        max_digits=12,
        decimal_places=3,
        verbose_name="Количество",
    )

    price = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Цена",
    )

    discount_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0,
        verbose_name="Скидка, %",
    )

    amount = models.DecimalField(
        max_digits=14,
        decimal_places=2,
        verbose_name="Сумма",
    )

    promo_id = models.CharField(
        max_length=50,
        blank=True,
        null=True,
        verbose_name="Промоакция",
    )

    is_promo_product = models.BooleanField(
        default=False,
        verbose_name="Товар промоакции",
    )

    is_promo_gift = models.BooleanField(
        default=False,
        verbose_name="Подарок",
    )

    promo_name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Название промоакции",
    )

    class Meta:
        ordering = ("line_number",)
        constraints = [
            models.UniqueConstraint(
                fields=("order", "line_number"),
                name="unique_order_line_number",
            ),
        ]
        verbose_name = "Строка заказа"
        verbose_name_plural = "Строки заказа"

    def __str__(self):
        return f"{self.order} — {self.product_name}"

class ShippingSettings(models.Model):
    delivery_working_days = models.PositiveSmallIntegerField(
        default=3,
        verbose_name="Рабочих дней до доставки",
    )

    delivery_cutoff_time = models.TimeField(
        default=time(13, 0),
        verbose_name="Время отсечения для доставки",
        help_text=(
            "Заказы после этого времени считаются "
            "принятыми следующим рабочим днём."
        ),
    )

    pickup_same_day_enabled = models.BooleanField(
        default=True,
        verbose_name="Разрешать самовывоз в день заказа",
    )

    pickup_same_day_cutoff = models.TimeField(
        default=time(13, 0),
        verbose_name="Время отсечения для самовывоза",
        help_text=(
            "После этого времени самовывоз "
            "доступен со следующего рабочего дня."
        ),
    )

    booking_horizon_days = models.PositiveSmallIntegerField(
        default=60,
        verbose_name="Горизонт выбора даты, дней",
    )

    class Meta:
        verbose_name = "Настройка отгрузки"
        verbose_name_plural = "Настройки отгрузки"

    def __str__(self):
        return "Настройки отгрузки"


class WorkCalendarException(models.Model):
    DAY_TYPE_WORKING = "working"
    DAY_TYPE_NON_WORKING = "non_working"

    DAY_TYPE_CHOICES = [
        (
            DAY_TYPE_WORKING,
            "Рабочий день",
        ),
        (
            DAY_TYPE_NON_WORKING,
            "Нерабочий день",
        ),
    ]

    date = models.DateField(
        unique=True,
        verbose_name="Дата",
    )

    day_type = models.CharField(
        max_length=20,
        choices=DAY_TYPE_CHOICES,
        verbose_name="Тип дня",
    )

    name = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="Название",
    )

    comment = models.TextField(
        blank=True,
        verbose_name="Комментарий",
    )

    class Meta:
        verbose_name = "Исключение производственного календаря"
        verbose_name_plural = "Исключения производственного календаря"
        ordering = ("date",)

    def __str__(self):
        return (
            f"{self.date:%d.%m.%Y} — "
            f"{self.get_day_type_display()}"
        )