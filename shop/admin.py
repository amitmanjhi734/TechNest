from django.contrib import admin

from .models import (
    Category,
    Address,
    Product,
    CartItem,
    Order,
    OrderItem,
    Coupon,
    CouponUsage,
)


# ============================================================
# CATEGORY ADMIN
# ============================================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'slug',
    )

    prepopulated_fields = {
        'slug': ('name',),
    }


# ============================================================
# PRODUCT ADMIN
# ============================================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = (
        'name',
        'brand',
        'price',
        'discount_price',
        'stock',
        'is_available',
    )

    list_filter = (
        'is_available',
        'category',
        'brand',
    )

    search_fields = (
        'name',
        'brand',
        'description',
    )

    prepopulated_fields = {
        'slug': ('name',),
    }


# ============================================================
# CART ITEM ADMIN
# ============================================================

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = (
        'product',
        'quantity',
        'added_at',
    )

    search_fields = (
        'product__name',
    )


# ============================================================
# ORDER ITEM INLINE
# ============================================================

class OrderItemInline(admin.TabularInline):
    model = OrderItem
    extra = 0

    readonly_fields = (
        'product',
        'quantity',
        'price',
        'get_total_price',
    )

    def get_total_price(self, obj):
        return obj.get_total_price()

    get_total_price.short_description = 'Total'


# ============================================================
# ORDER ADMIN
# ============================================================

@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):

    list_display = (
        'id',
        'full_name',
        'phone',
        'payment_method',
        'payment_status',
        'status',
        'total_amount',
        'created_at',
    )

    list_filter = (
        'status',
        'payment_method',
        'payment_status',
        'created_at',
    )

    search_fields = (
        'full_name',
        'phone',
        'city',
        'pin_code',
        'razorpay_order_id',
        'razorpay_payment_id',
    )

    readonly_fields = (
        'created_at',
        'razorpay_order_id',
        'razorpay_payment_id',
    )

    ordering = (
        '-created_at',
    )

    list_per_page = 25

    inlines = [
        OrderItemInline,
    ]

    # --------------------------------------------------------
    # AUTOMATIC ORDER TIMESTAMPS
    # --------------------------------------------------------

    def save_model(self, request, obj, form, change):

        if change:
            old_order = Order.objects.get(pk=obj.pk)

            if old_order.status != obj.status:
                from django.utils import timezone

                # Confirmed
                if (
                    obj.status == 'confirmed'
                    and obj.confirmed_at is None
                ):
                    obj.confirmed_at = timezone.now()

                # Shipped
                if (
                    obj.status == 'shipped'
                    and obj.shipped_at is None
                ):
                    obj.shipped_at = timezone.now()

                # Delivered
                if (
                    obj.status == 'delivered'
                    and obj.delivered_at is None
                ):
                    obj.delivered_at = timezone.now()

                # Cancelled
                if (
                    obj.status == 'cancelled'
                    and obj.cancelled_at is None
                ):
                    obj.cancelled_at = timezone.now()

        super().save_model(
            request,
            obj,
            form,
            change,
        )

    # --------------------------------------------------------
    # ADMIN ACTIONS
    # --------------------------------------------------------

    actions = [
        'cancel_selected_orders',
    ]

    @admin.action(
        description='Cancel selected orders and restore stock'
    )
    def cancel_selected_orders(
        self,
        request,
        queryset,
    ):
        for order in queryset:

            if order.status == 'cancelled':
                continue

            from .views import restore_order_stock

            restore_order_stock(order.id)

        self.message_user(
            request,
            'Selected orders have been cancelled and stock has been restored.',
        )


# ============================================================
# ORDER ITEM ADMIN
# ============================================================

@admin.register(OrderItem)
class OrderItemAdmin(admin.ModelAdmin):
    list_display = (
        'order',
        'product',
        'quantity',
        'price',
    )

    search_fields = (
        'order__full_name',
        'product__name',
    )


# ============================================================
# COUPON ADMIN
# ============================================================

@admin.register(Coupon)
class CouponAdmin(admin.ModelAdmin):
    list_display = (
        'code',
        'discount_type',
        'discount_value',
        'active',
        'start_date',
        'expiry_date',
        'usage_count',
        'usage_limit',
    )

    list_filter = (
        'active',
        'discount_type',
        'start_date',
        'expiry_date',
    )

    search_fields = (
        'code',
    )

    filter_horizontal = (
        'specific_products',
        'specific_categories',
    )

    readonly_fields = (
        'usage_count',
        'created_at',
    )


# ============================================================
# COUPON USAGE ADMIN
# ============================================================

@admin.register(CouponUsage)
class CouponUsageAdmin(admin.ModelAdmin):
    list_display = (
        'coupon',
        'user',
        'session_key',
        'order',
        'used_at',
    )

    list_filter = (
        'used_at',
        'coupon',
    )

    search_fields = (
        'coupon__code',
        'user__username',
        'session_key',
        'order__id',
    )

    readonly_fields = (
        'coupon',
        'user',
        'session_key',
        'order',
        'used_at',
    )


# ============================================================
# ADDRESS ADMIN
# ============================================================

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'user',
        'label',
        'full_name',
        'phone',
        'city',
        'pin_code',
        'is_default',
        'updated_at',
    )

    list_filter = (
        'label',
        'is_default',
        'city',
    )

    search_fields = (
        'user__username',
        'full_name',
        'phone',
        'address',
        'city',
        'pin_code',
    )

    readonly_fields = (
        'created_at',
        'updated_at',
    )