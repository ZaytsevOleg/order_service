from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver

from django.conf import settings
from bson import ObjectId
from datetime import datetime

class Order:
    def __init__(self, order_id, Number,customer, holding, date, amount, comment, brand,
                 status, shipping_date, shipping_type, product_list):
        self.OrderID = order_id
        self.Number = Number
        self.Customer = customer
        self.Holding = holding
        self.Date = date
        self.Amount = amount
        self.Comment = comment
        self.Brand = brand
        self.Status = status
        self.Shipping_Date = shipping_date
        self.Shipping_Type = shipping_type
        self.Product = product_list

    @staticmethod
    def get_collection():
        return settings.MONGO_DB['customer_order']

    def save(self):
        """Сохраняет документ в MongoDB"""
        document = self.__dict__
        self.get_collection().insert_one(document)

    @classmethod
    def find(cls, query={}):
        """Возвращает список документов по запросу"""
        return list(cls.get_collection().find(query))

    # @classmethod
    # def find_by_id(cls, order_id):
    #     """Находит документ по OrderID"""
    #     return cls.get_collection().find_one({"order_id": order_id})
    
    @classmethod
    def find_by_id(cls, order_id):
        collection = cls.get_collection()

        return collection.find_one({
            "order_id": str(order_id).strip()
        })

    @classmethod
    def update(cls, order_id, update_fields):
        """Обновляет поля документа"""
        cls.get_collection().update_one({"OrderID": order_id}, {"$set": update_fields})

    @classmethod
    def delete(cls, order_id):
        """Удаляет документ по OrderID"""
        cls.get_collection().delete_one({"OrderID": order_id})


# Обёрточная модель для Django Admin
class OrderModel(models.Model):
    order_id = models.CharField(max_length=100, unique=True)
    Number = models.IntegerField()
    customer = models.CharField(max_length=255)
    holding = models.CharField(max_length=255)
    date = models.DateField()
    amount = models.FloatField()
    comment = models.TextField(blank=True, null=True)
    brand = models.CharField(max_length=100)
    status = models.CharField(max_length=50)
    shipping_date = models.DateField()
    shipping_type = models.CharField(max_length=100)
    product_list = models.JSONField()

    class Meta:
        managed = False
        verbose_name = "Order"
        verbose_name_plural = "Orders"

    def save(self, *args, **kwargs):
        """Сохраняет объект в MongoDB через класс Order"""
        order = Order(
            order_id=self.order_id,
            number=self.number,
            customer=self.customer,
            holding=self.holding,
            date=self.date,
            amount=self.amount,
            comment=self.comment,
            brand=self.brand,
            status=self.status,
            shipping_date=self.shipping_date,
            shipping_type=self.shipping_type,
            product_list=self.product_list,
        )
        order.save()

    def delete(self, *args, **kwargs):
        """Удаляет объект из MongoDB через класс Order"""
        Order.delete(self.order_id)

class Product(models.Model):
    ref_key = models.CharField(max_length=255, primary_key=True)  # Ref_key_product
    article = models.CharField(max_length=255)
    name = models.CharField(max_length=255)
    description = models.TextField(null=True, blank=True)

    class Meta:
        managed = False
        db_table = 'products'
        app_label = 'mssql'


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    holding_id = models.CharField(max_length=255, blank=True, null=True)
    title = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return f"Profile of {self.user.username}"

# Автоматическое создание профиля для нового пользователя
@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.get_or_create(user=instance)

@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    UserProfile.objects.get_or_create(user=instance)
    instance.profile.save()

