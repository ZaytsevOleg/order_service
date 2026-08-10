from django import forms

from sales.models import Order


class OrderForm(forms.ModelForm):
    class Meta:
        model = Order

        fields = [
            "customer",
            "contract",
            "price_type",
            "delivery_address",
            "payment_method",
            "shipping_type",
            "comment",
        ]

        widgets = {
            "comment": forms.Textarea(
                attrs={
                    "rows": 3,
                }
            ),
        }