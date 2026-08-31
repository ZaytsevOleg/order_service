from django.contrib import admin

from .models import (
    ShippingSettings,
    WorkCalendarException,
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