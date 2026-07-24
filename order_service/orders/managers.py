# orders/managers.py
from django.conf import settings
from .mongo_utils import get_order_items, save_order_items

class OrderManager:
    @staticmethod
    def get_order(order_id):
        return get_order_items(order_id)

    @staticmethod
    def save_order(order_id, items):
        save_order_items(order_id, items)

    @staticmethod
    def get_all_orders(holding_id):
        db = settings.MONGO_DB
        collection = db['customer_order']
        return collection.find({'holding': holding_id},{'order_id':1,'Number':1,'customer':1,'date':1,'amount':1,'status':1,'shipping_date':1,'shipping_type':1})   # Возвращает курсор всех заказов
