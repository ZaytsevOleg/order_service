from django.contrib import admin
from .models import UserProfile
from .models import OrderModel
from .models import Order


@admin.register(OrderModel)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('order_id', 'customer', 'date', 'amount', 'status')  # Поля для отображения
    search_fields = ('order_id', 'customer', 'brand')  # Поля для поиска
    readonly_fields = ('order_id',)  # Защита от изменения ID

    def get_queryset(self, request):
        """Получаем данные из MongoDB"""
        orders = OrderModel.get_all()
        return orders

    def save_model(self, request, obj, form, change):
        """Сохраняет объект в MongoDB"""
        obj.save()

    def delete_model(self, request, obj):
        """Удаляет объект из MongoDB"""
        Order.delete(obj.order_id)

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'holding_id','title')
