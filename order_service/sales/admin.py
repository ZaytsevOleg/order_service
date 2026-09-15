from django.contrib import admin

from .models import (
    ShippingSettings,
    WorkCalendarException,
    Order,
    OrderItem,
    TransportCompany,
)


@admin.register(ShippingSettings)
class ShippingSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "delivery_working_days",
        "delivery_cutoff_time",
        "pickup_same_day_enabled",
        "pickup_same_day_cutoff",
        "booking_horizon_days",
    )


@admin.register(WorkCalendarException)
class WorkCalendarExceptionAdmin(
    admin.ModelAdmin
):
    list_display = (
        "date",
        "day_type",
        "name",
        "comment",
    )

    list_filter = (
        "day_type",
    )

    search_fields = (
        "name",
        "comment",
    )

    ordering = (
        "-date",
    )

    date_hierarchy = "date"


@admin.register(TransportCompany)
class TransportCompanyAdmin(admin.ModelAdmin):

    list_display = (
        "name",
        "is_active",
        "sort_order",
    )

    list_editable = (
        "is_active",
        "sort_order",
    )

    search_fields = (
        "name",
    )

    ordering = (
        "sort_order",
        "name",
    )