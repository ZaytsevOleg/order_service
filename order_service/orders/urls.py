from django.urls import path

from . import views


urlpatterns = [
    path(
        "",
        views.order_list,
        name="order_list",
    ),

    path(
        "create/",
        views.order_create,
        name="order_create",
    ),

    path(
        "order/<uuid:order_id>/",
        views.order_detail,
        name="order_detail",
    ),

    path(
        "api/customer/<str:customer_id>/options/",
        views.customer_options,
        name="customer_options",
    ),
    path(
        "api/customer/<str:customer_id>/products/",
        views.customer_products,
        name="customer_products",
    ),
    path(
        "api/customer/<str:customer_id>/promotions/",
        views.customer_promotions,
        name="customer_promotions",
    ),
    path(
        "api/customer/<str:customer_id>/promotions/evaluate/",
        views.evaluate_promotions,
        name="evaluate_promotions",
    ),
]