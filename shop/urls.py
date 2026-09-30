from django.urls import path
from . import views

urlpatterns = [
    path('', views.home, name='home'),

    path(
        'product/<slug:slug>/',
        views.product_detail,
        name='product_detail'
    ),

    path(
        'cart/add/<slug:slug>/',
        views.add_to_cart,
        name='add_to_cart'
    ),

    path(
    'buy-now/<slug:slug>/',
    views.buy_now,
    name='buy_now'
),

    path(
        'cart/',
        views.cart,
        name='cart'
    ),

    path(
        'cart/increase/<slug:slug>/',
        views.increase_quantity,
        name='increase_quantity'
    ),

    path(
        'cart/decrease/<slug:slug>/',
        views.decrease_quantity,
        name='decrease_quantity'
    ),

    path(
        'cart/remove/<slug:slug>/',
        views.remove_from_cart,
        name='remove_from_cart'
    ),

    path(
    'checkout/',
    views.checkout,
    name='checkout'
    ),

    path(
    'order-success/<int:order_id>/',
    views.order_success,
    name='order_success'
    ),

    path(
    "my-orders/",
    views.my_orders,
    name="my_orders"
),

    path(
    "my-orders/<int:order_id>/",
    views.order_detail,
    name="order_detail"
),

path(
    "my-orders/<int:order_id>/cancel/",
    views.cancel_order,
    name="cancel_order"
),

    path(
    "payment/create/",
    views.create_razorpay_order,
    name="create_razorpay_order"
    ),

    path(
    "payment/verify/",
    views.payment_verify,
    name="payment_verify"
    ),

    path(
    "wishlist/",
    views.wishlist,
    name="wishlist"
    ),
    
path(
    "wishlist/add/<slug:slug>/",
    views.add_to_wishlist,
    name="add_to_wishlist"
),


path(
    "wishlist/remove/<slug:slug>/",
    views.remove_from_wishlist,
    name="remove_from_wishlist"
),

path(
    "ai-chat/", views.ai_chat, name="ai_chat"
),

path(
    "login/",
    views.login_view,
    name="login"
),

path(
    "register/",
    views.register_view,
    name="register"
),

path(
    "logout/",
    views.logout_view,
    name="logout"
),

path(
    "saved-addresses/",
    views.saved_addresses,
    name="saved_addresses"
),

path(
    "apply-coupon/",
    views.apply_coupon,
    name="apply_coupon"
),

path(
    "remove-coupon/",
    views.remove_coupon,
    name="remove_coupon"
),
]

