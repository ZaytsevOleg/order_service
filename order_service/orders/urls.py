from django.urls import path
from . import views


urlpatterns = [
    path('', views.order_list, name='order_list'),
    path('create/', views.order_create, name='order_create'),
    path('order/<str:order_id>/', views.order_detail, name='order_detail')
]
