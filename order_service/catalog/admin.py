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

class DeliveryAddressInline(admin.TabularInline):
    model = LegalEntityDeliveryAddress
    extra = 0


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


@admin.register(UserLegalEntityAccess)
class UserLegalEntityAccessAdmin(admin.ModelAdmin):
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
        "legal_entity__name",
        "legal_entity__inn",
        "legal_entity__legal_entity_id",
    )

    autocomplete_fields = (
        "user",
        "legal_entity",
        "price_type",
    )

    @admin.display(description="ИНН")
    def legal_entity_inn(self, obj):
        return obj.legal_entity.inn

@admin.register(PriceType)
class PriceTypeAdmin(admin.ModelAdmin):
    list_display = ("name", "price_type_id", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "price_type_id")


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
    list_display = ("product", "price_type", "price", "updated_at")
    list_filter = ("price_type",)
    search_fields = (
        "product__name",
        "product__article",
        "price_type__name",
        "price_type__price_type_id",
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

@admin.register(LegalEntity)
class LegalEntityAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "client_type",
        "inn",
        "kpp",
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

    inlines = [
        ContractInline,
        DeliveryAddressInline,
    ]

    @admin.display(description="Форма оплаты")
    def payment_method_display(self, obj):
        return obj.allowed_payment_method_display
