from django.contrib import admin, messages
from django import forms
from django.core.exceptions import ValidationError
from django.http import HttpResponseRedirect
from django.urls import path, reverse

from sales.services.onec_connection import test_onec_connection
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
    change_form_template = "admin/sales/onecconnection/change_form.html"

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
    def get_urls(self):
        custom_urls = [
            path(
                "<int:object_id>/test/",
                self.admin_site.admin_view(self.test_connection_view),
                name="sales_onecconnection_test",
            ),
        ]
        return custom_urls + super().get_urls()

    def test_connection_view(self, request, object_id):
        if request.method != "POST":
            return HttpResponseRedirect(
                reverse("admin:sales_onecconnection_change", args=[object_id])
            )

        connection = self.get_object(request, object_id)

        if connection is None or not self.has_change_permission(request, connection):
            from django.core.exceptions import PermissionDenied
            raise PermissionDenied

        success, message = test_onec_connection(connection)

        self.message_user(
            request,
            message,
            level=messages.SUCCESS if success else messages.ERROR,
        )

        return HttpResponseRedirect(
            reverse("admin:sales_onecconnection_change", args=[object_id])
        )
