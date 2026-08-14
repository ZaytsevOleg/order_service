from django import forms
from django.contrib import admin

from .models import (
    Brand,
    PriceType,
    UserLegalEntityAccess,
    LegalEntityDeliveryAddress,
    LegalEntity,
    Contract,
    Product,
    Price,
    PromoAction,
    CurrencyRate,
    Warehouse,
    StockBalance,
)


@admin.register(Brand)
class BrandAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "brand_id",
        "is_active",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "brand_id",
    )

    ordering = (
        "name",
    )


@admin.register(PriceType)
class PriceTypeAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "price_type_id",
        "is_active",
    )

    list_filter = (
        "is_active",
    )

    search_fields = (
        "name",
        "price_type_id",
    )

    ordering = (
        "name",
    )


class UserLegalEntityAccessAdminForm(forms.ModelForm):
    class Meta:
        model = UserLegalEntityAccess
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()

        is_active = cleaned_data.get("is_active")
        price_type = cleaned_data.get("price_type")

        if is_active and price_type is None:
            self.add_error(
                "price_type",
                "Для активного доступа необходимо выбрать тип цен.",
            )

        return cleaned_data


class DeliveryAddressInline(admin.TabularInline):
    model = LegalEntityDeliveryAddress
    extra = 0

    fields = (
        "address",
        "address_id",
        "is_default",
        "is_active",
    )

    can_delete = True
    show_change_link = True

    verbose_name = "Адрес доставки"
    verbose_name_plural = "Адреса доставки"


class ContractInline(admin.TabularInline):
    model = Contract
    extra = 0

    fields = (
        "contract_name",
        "contract_id",
        "brand",
        "is_default",
        "is_active",
    )

    can_delete = True
    show_change_link = True

    verbose_name = "Договор"
    verbose_name_plural = "Договоры"


class UserLegalEntityAccessInline(admin.TabularInline):
    model = UserLegalEntityAccess
    form = UserLegalEntityAccessAdminForm

    extra = 0

    autocomplete_fields = (
        "user",
        "price_type",
    )

    fields = (
        "user",
        "price_type",
        "discount_percent",
        "is_default",
        "is_active",
    )


@admin.register(UserLegalEntityAccess)
class UserLegalEntityAccessAdmin(admin.ModelAdmin):
    form = UserLegalEntityAccessAdminForm

    list_display = (
        "user",
        "legal_entity",
        "legal_entity_inn",
        "price_type",
        "discount_percent",
        "is_default",
        "is_active",
    )

    list_filter = (
        "price_type",
        "is_default",
        "is_active",
        "legal_entity__client_type",
    )

    search_fields = (
        "user__username",
        "user__email",
        "user__first_name",
        "user__last_name",
        "legal_entity__name",
        "legal_entity__full_name",
        "legal_entity__inn",
        "legal_entity__kpp",
        "legal_entity__legal_entity_id",
    )


    list_select_related = (
        "user",
        "legal_entity",
        "price_type",
    )

    ordering = (
        "user__username",
        "legal_entity__name",
    )

    @admin.display(
        description="ИНН",
        ordering="legal_entity__inn",
    )
    def legal_entity_inn(self, obj):
        return obj.legal_entity.inn


@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    change_form_template = (
        "admin/catalog/legalentity/change_form.html"
    )

    list_display = (
        "name",
        "client_type",
        "inn",
        "kpp",
        "contracts_count",
        "addresses_count",
        "payment_method_display",
        "is_active",
    )

    list_filter = (
        "client_type",
        "is_active",
    )

    search_fields = (
        "name",
        "full_name",
        "inn",
        "kpp",
        "legal_entity_id",
    )

    readonly_fields = (
        "updated_at",
    )

    inlines = [
        ContractInline,
        DeliveryAddressInline,
        UserLegalEntityAccessInline,
    ]

    ordering = (
        "name",
    )

    @admin.display(description="Форма оплаты")
    def payment_method_display(self, obj):
        return obj.allowed_payment_method_display

    @admin.display(description="Договоры")
    def contracts_count(self, obj):
        return obj.contracts.count()

    @admin.display(description="Адреса")
    def addresses_count(self, obj):
        return obj.delivery_addresses.count()


@admin.register(Contract)
class ContractAdmin(admin.ModelAdmin):
    list_display = (
        "contract_name",
        "contract_id",
        "legal_entity",
        "brand",
        "organization_id",
        "is_default",
        "is_active",
    )

    list_filter = (
        "brand",
        "is_default",
        "is_active",
    )

    search_fields = (
        "contract_name",
        "contract_id",
        "legal_entity__name",
        "legal_entity__inn",
    )

    autocomplete_fields = (
        "legal_entity",
    )

    list_select_related = (
        "legal_entity",
    )


@admin.register(LegalEntityDeliveryAddress)
class LegalEntityDeliveryAddressAdmin(admin.ModelAdmin):
    list_display = (
        "legal_entity",
        "short_address",
        "is_default",
        "is_active",
    )

    list_filter = (
        "is_default",
        "is_active",
    )

    search_fields = (
        "address",
        "address_id",
        "legal_entity__name",
        "legal_entity__inn",
    )

    autocomplete_fields = (
        "legal_entity",
    )

    list_select_related = (
        "legal_entity",
    )

    @admin.display(description="Адрес")
    def short_address(self, obj):
        if len(obj.address) <= 100:
            return obj.address

        return f"{obj.address[:100]}..."


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        "article",
        "name",
        "brand",
        "is_active",
    )

    list_filter = (
        "brand",
        "is_active",
    )

    search_fields = (
        "article",
        "name",
        "product_id",
    )

    autocomplete_fields = (
        "brand",
    )


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "price_type",
        "price",
        "updated_at",
    )

    list_filter = (
        "price_type",
    )

    search_fields = (
        "product__name",
        "product__article",
        "price_type__name",
        "price_type__price_type_id",
    )

    list_select_related = (
        "product",
        "price_type",
    )


@admin.register(PromoAction)
class PromoActionAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "brand",
        "date_from",
        "date_to",
        "is_active",
    )

    list_filter = (
        "brand",
        "is_active",
    )

    autocomplete_fields = (
        "brand",
    )

@admin.register(CurrencyRate)
class CurrencyRateAdmin(admin.ModelAdmin):
    list_display = (
        "currency_code",
        "rate",
        "valid_from",
        "created_at",
    )

    list_filter = (
        "currency_code",
    )

    search_fields = (
        "currency_code",
    )

    ordering = (
        "-valid_from",
        "-id",
    )

    readonly_fields = (
        "created_at",
    )


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "warehouse_id",
        "organization_id",
        "is_active",
    )

    list_filter = (
        "is_active",
        "organization_id",
    )

    search_fields = (
        "name",
        "warehouse_id",
        "organization_id",
    )

    ordering = (
        "organization_id",
        "name",
    )


@admin.register(StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = (
        "product",
        "warehouse",
        "quantity",
        "updated_at",
    )

    list_filter = (
        "warehouse",
    )

    search_fields = (
        "product__name",
        "product__article",
        "warehouse__name",
    )

    autocomplete_fields = (
        "product",
        "warehouse",
    )

    ordering = (
        "warehouse",
        "product",
    )

    readonly_fields = (
        "updated_at",
    )