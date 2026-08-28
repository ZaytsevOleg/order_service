from django import forms

from catalog.models import (
    Contract,
    LegalEntityDeliveryAddress,
    UserLegalEntityAccess,
    LegalEntity
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

    def __init__(
        self,
        *args,
        user=None,
        brand=None,
        **kwargs,
    ):
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

        # -----------------------------------------------------
        # Форма оплаты
        # -----------------------------------------------------

        payment_method = (
            self.data.get("payment_method")
            or getattr(
                self.instance,
                "payment_method",
                None,
            )
        )

        # -----------------------------------------------------
        # Доступные пользователю клиенты
        # -----------------------------------------------------

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

        customers = (
            self.fields["customer"]
            .queryset
            .model.objects
            .filter(
                customer_accesses__in=accesses,
            )
            .distinct()
        )

        # -----------------------------------------------------
        # Ограничение по бренду
        # -----------------------------------------------------

        if brand:
            customers = (
                customers
                .filter(
                    contracts__brand=brand.brand_id,
                    contracts__is_active=True,
                )
                .distinct()
            )

        # -----------------------------------------------------
        # Фильтрация по форме оплаты
        # -----------------------------------------------------

        if payment_method == Order.PAYMENT_CASH:

            customers = customers.filter(
                client_type=
                    LegalEntity.CLIENT_TYPE_PERSON,
            )

        elif payment_method == Order.PAYMENT_CASHLESS:

            customers = customers.filter(
                client_type__in=[
                    LegalEntity.CLIENT_TYPE_LLC,
                    LegalEntity.CLIENT_TYPE_IE,
                ],
            )

        else:
            # Пока форма оплаты не выбрана,
            # клиента выбирать не даём.
            customers = customers.none()

        self.fields["customer"].queryset = (
            customers.order_by("name")
        )

        # -----------------------------------------------------
        # Выбранный клиент
        # -----------------------------------------------------

        customer_id = (
            self.data.get("customer")
            or getattr(
                self.instance,
                "customer_id",
                None,
            )
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

    def clean(self):

        cleaned_data = super().clean()

        customer = cleaned_data.get("customer")

        payment_method = cleaned_data.get(
                "payment_method"
            )

        if (
            customer
            and payment_method
            and customer.allowed_payment_method
                != payment_method
        ):
            self.add_error(
                "payment_method",
                "Выбранная форма оплаты "
                "недоступна для этого клиента.",
            )

        return cleaned_data