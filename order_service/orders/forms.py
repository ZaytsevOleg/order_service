from django import forms
from .models import OrderModel

class OrderForm(forms.ModelForm):
    class Meta:
        model = OrderModel
        fields = [
            'order_id',
            'Number', 
            'customer', 
            'holding',
            'date',
            'amount',
            'comment',
            'brand',
            'status',
            'shipping_date',
            'shipping_type'
            ]

