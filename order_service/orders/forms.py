from django import forms

from catalog.models import (
    Contract,
    LegalEntityDeliveryAddress,
    UserLegalEntityAccess,
)
from sales.models import Order


class OrderCreateForm(forms.ModelForm):
    class Meta:
        model = Order
        fields = [
            "customer",
            "contract",
            "delivery_address",
            "payment_method",
            "shipping_type",
            "shipping_date",
            "comment",
        ]

        widgets = {
            "shipping_date": forms.DateInput(
                attrs={"type": "date"},
            ),
            "comment": forms.Textarea(
                attrs={"rows": 3},
            ),
        }

    def __init__(self, *args, user=None, brand=None, **kwargs):
        super().__init__(*args, **kwargs)

        self.user = user
        self.brand = brand

        self.fields["customer"].queryset = (
            self.fields["customer"]
            .queryset
            .none()
        )

        self.fields["contract"].queryset = (
            Contract.objects.none()
        )

        self.fields["delivery_address"].queryset = (
            LegalEntityDeliveryAddress.objects.none()
        )

        if not user:
            return

        accesses = (
            UserLegalEntityAccess.objects
            .filter(
                user=user,
                is_active=True,
                legal_entity__is_active=True,
            )
            .select_related(
                "legal_entity",
                "price_type",
            )
        )

        self.fields["customer"].queryset = (
            self.fields["customer"]
            .queryset
            .model.objects
            .filter(
                customer_accesses__in=accesses,
            )
            .distinct()
            .order_by("name")
        )

        customer_id = (
            self.data.get("customer")
            or getattr(
                self.instance,
                "customer_id",
                None,
            )
        )

        if brand:
            self.fields["customer"].queryset = (
                self.fields["customer"]
                .queryset
                .filter(
                    contracts__brand=brand.brand_id,
                    contracts__is_active=True,
                )
                .distinct()
            )

        if customer_id:
            contract_filters = {
                "legal_entity_id": customer_id,
                "is_active": True,
            }

            if brand:
                contract_filters["brand"] = (
                    brand.brand_id
                )

            self.fields["contract"].queryset = (
                Contract.objects
                .filter(**contract_filters)
                .order_by(
                    "contract_name",
                )
            )

            self.fields[
                "delivery_address"
            ].queryset = (
                LegalEntityDeliveryAddress.objects
                .filter(
                    legal_entity_id=customer_id,
                    is_active=True,
                )
                .order_by("address")
            )