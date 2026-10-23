from django.contrib import admin
from django import forms
from django.core.exceptions import ValidationError

from .models import OneCConnection
from .services.onec_credentials import (
    encrypt_password,
)
from .models import (
    ShippingSettings,
    WorkCalendarException,
    Order,
    OrderItem,
    OrderLog,
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
        "id_1c",
        "is_active",
        "sort_order",
    )

    list_editable = (
        "is_active",
        "sort_order",
    )

    search_fields = (
        "name",
        "id_1c",
    )

    ordering = (
        "sort_order",
        "name",
    )



class OneCConnectionForm(forms.ModelForm):
    password = forms.CharField(
        label="Новый пароль 1С",
        widget=forms.PasswordInput(
            render_value=False
        ),
        required=False,
        help_text=(
            "При редактировании оставьте пустым, "
            "чтобы сохранить текущий пароль."
        ),
    )

    class Meta:
        model = OneCConnection
        fields = (
            "name",
            "base_url",
            "username",
            "password",
            "timeout",
            "is_active",
        )

    def clean(self):
        data = super().clean()
        password = data.get("password")

        if not password and not (
            self.instance.pk
            and self.instance.encrypted_password
        ):
            raise ValidationError(
                "Необходимо указать пароль 1С."
            )

        return data

    def save(self, commit=True):
        instance = super().save(commit=False)
        password = self.cleaned_data.get("password")

        if password:
            instance.encrypted_password = (
                encrypt_password(password)
            )

        if commit:
            instance.save()
            self.save_m2m()

        return instance


@admin.register(OneCConnection)
class OneCConnectionAdmin(admin.ModelAdmin):
    form = OneCConnectionForm

    list_display = (
        "name",
        "base_url",
        "username",
        "is_active",
    )

    list_filter = ("is_active",)

    search_fields = (
        "name",
        "username",
    )

    fieldsets = (
        (
            "Подключение",
            {
                "fields": (
                    "name",
                    "base_url",
                    "username",
                    "password",
                    "timeout",
                    "is_active",
                )
            },
        ),
    )
