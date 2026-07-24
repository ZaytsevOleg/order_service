from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from .models import Order, Product
from .mongo_utils import get_order_items
from .forms import OrderForm
from .managers import OrderManager
import json

STATUS_MAP = {
    1: "Черновик",
    2: "Согласование",
    3: "Оформлен",
    4: "Отгрузка",
    5: "Завершен",
}


STATUS_ICONS = {
    1: "bi-pencil",            # Черновик
    2: "bi-clock-history",     # На согласовании
    3: "bi-check2-square",     # Оформлен
    4: "bi-truck",             # Отгрузка
    5: "bi-patch-check-fill",  # Завершен
}


def get_status_text(status):
    STATUS_MAP = {
        1: "Черновик",
        2: "Согласование",
        3: "Оформлен",
        4: "Отгрузка",
        5: "Завершен",
    }

    try:
        return STATUS_MAP.get(int(status), "Неизвестно")
    except (TypeError, ValueError):
        return "Неизвестно"
    


# Маршрут списка заказов
@login_required
def order_list(request):
    holding_id = request.user.profile.holding_id

    orders = []

    for order in OrderManager.get_all_orders(holding_id):
        status_value = int(order.get('status', 0))

        orders.append({
            'order_number': order.get('order_id'),
            'Number': order.get('Number'),
            'customer': order.get('customer'),
            'creation_date': order.get('date'),
            'status': STATUS_MAP.get(status_value, 'Неизвестно'),
            'status_value': status_value,
            'status_icon': STATUS_ICONS.get(status_value, 'bi-question-circle'),
            'shipping_date': order.get('shipping_date'),
            'shipping_type': order.get('shipping_type'),
            'total_amount': order.get('amount'),
        })

    return render(request, 'orders/order_list.html', {
        'orders': orders
    })



@login_required
def home(request):
    return render(request, 'orders/home.html')

def order_create(request):
    if request.method == 'POST':
        form = OrderForm(request.POST)
        if form.is_valid():
            order = form.save(commit=False)
            order.partner = request.user
            order.save()
            return redirect('order_list')
    else:
        form = OrderForm()
    return render(request, 'orders/order_form.html', {'form': form})

# Маршрут просмотра заказа
@login_required
def order_detail(request, order_id):
    order = Order.find_by_id(order_id)

    if order:
        status_value = int(order.get('status', 0))

        order['status_text'] = STATUS_MAP.get(status_value, 'Неизвестно')
        order['status_value'] = status_value
        order['status_icon'] = STATUS_ICONS.get(status_value, 'bi-question-circle')

    products = []

    if order:
        for item in order.get('product_list', []):
            products.append({
                'line_number': item.get('LineNumber'),
                'product_name': item.get('product_name') or item.get('Номенклатура_Key'),
                'product_article': item.get('product_article'),
                'quantity': item.get('Количество'),
                'price': item.get('Цена'),
                'amount': item.get('Сумма'),
                'discount': item.get('ПроцентСкидкиНаценки'),
            })

    return render(request, 'orders/order_detail.html', {
        'order': order,
        'products': products,
    })

# Маршрут создания заказа
@login_required
def order_create(request):
    return render(request, 'orders/order_create.html')