from django.db import models
from django.contrib.auth.models import User


class Category(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True)

    def __str__(self):
        return self.name


class Address(models.Model):
    LABEL_CHOICES = [
        ("home", "Home"),
        ("office", "Office"),
        ("other", "Other"),
    ]

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name="saved_addresses",
    )

    label = models.CharField(
        max_length=20,
        choices=LABEL_CHOICES,
        default="home",
    )

    full_name = models.CharField(max_length=200)
    phone = models.CharField(max_length=20)
    address = models.TextField()
    city = models.CharField(max_length=100)
    pin_code = models.CharField(max_length=10)

    is_default = models.BooleanField(default=False)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ("-is_default", "-updated_at")

    def __str__(self):
        return f"{self.get_label_display()} - {self.full_name} ({self.city})"


class Product(models.Model):
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="products"
    )

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)

    brand = models.CharField(max_length=100, blank=True)

    description = models.TextField()

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    discount_price = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        blank=True,
        null=True
    )

    stock = models.PositiveIntegerField(default=0)

    image = models.ImageField(
        upload_to="products/",
        blank=True,
        null=True
    )

    rating = models.DecimalField(
        max_digits=2,
        decimal_places=1,
        default=0
    )

    is_available = models.BooleanField(default=True)

    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def discount_percentage(self):
        """Return the product discount as a whole-number percentage."""
        if self.discount_price is None or self.price is None:
            return 0
        if self.discount_price >= self.price or self.price == 0:
            return 0
        return int(round(((self.price - self.discount_price) / self.price) * 100))

    def __str__(self):
        return self.name

class CartItem(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="cart_items"
    )

    session_key = models.CharField(
        max_length=40,
        db_index=True
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    quantity = models.PositiveIntegerField(default=1)

    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session_key', 'product'],
                name='unique_session_product'
            )
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name}"

    def get_total_price(self):
        price = self.product.discount_price or self.product.price
        return price * self.quantity

class Order(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="orders"
    )

    session_key = models.CharField(
        max_length=40,
        db_index=True,
        blank=True,
        null=True
    )

    PAYMENT_CHOICES = [
        ('cod', 'Cash on Delivery'),
        ('online', 'Online Payment'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('paid', 'Paid'),
        ('failed', 'Failed'),
    ]

    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('confirmed', 'Confirmed'),
        ('shipped', 'Shipped'),
        ('delivered', 'Delivered'),
        ('cancelled', 'Cancelled'),
    ]

    full_name = models.CharField(max_length=200)

    phone = models.CharField(max_length=20)

    address = models.TextField()

    city = models.CharField(max_length=100)

    pin_code = models.CharField(max_length=10)

    payment_method = models.CharField(
        max_length=20,
        choices=PAYMENT_CHOICES,
        default='cod'
    )

    payment_status = models.CharField(
        max_length=20,
        choices=PAYMENT_STATUS_CHOICES,
        default='pending'
    )

    cancelled_from_status = models.CharField(
    max_length=20,
    choices=STATUS_CHOICES,
    blank=True,
    null=True
    )
    stock_restored = models.BooleanField(default=False)

    razorpay_order_id = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    razorpay_payment_id = models.CharField(
        max_length=100,
        blank=True,
        null=True
    )

    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='pending'
    )


    coupon = models.ForeignKey(
    "Coupon",
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name="orders"
    )

    coupon_code = models.CharField(
        max_length=50,
        blank=True,
        null=True
    )

    coupon_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )


    total_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    confirmed_at = models.DateTimeField(
        blank=True,
        null=True
    )

    shipped_at = models.DateTimeField(
        blank=True,
        null=True
    )

    delivered_at = models.DateTimeField(
        blank=True,
        null=True
    )

    cancelled_at = models.DateTimeField(
        blank=True,
        null=True
    )

    def __str__(self):
        return f"Order #{self.id} - {self.full_name}"


class OrderItem(models.Model):
    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name='items'
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.SET_NULL,
        null=True
    )

    quantity = models.PositiveIntegerField()

    price = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    def get_total_price(self):
        if self.price is None or self.quantity is None:
            return 0

        return self.price * self.quantity

    def __str__(self):
       if self.product:
            return f"{self.quantity} x {self.product.name}"

       return f"{self.quantity} x Deleted Product"

class WishlistItem(models.Model):

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="wishlist_items"
    )

    session_key = models.CharField(
        max_length=40,
        db_index=True
    )

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE
    )

    added_at = models.DateTimeField(auto_now_add=True)


    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['session_key', 'product'],
                name='unique_wishlist_product'
            )
        ]

    def __str__(self):
        return self.product.name

# =========================================================
# COUPON
# =========================================================

class Coupon(models.Model):

    DISCOUNT_TYPE_CHOICES = [
        ("percentage", "Percentage"),
        ("fixed", "Fixed Amount"),
    ]

    code = models.CharField(
        max_length=50,
        unique=True
    )

    discount_type = models.CharField(
        max_length=20,
        choices=DISCOUNT_TYPE_CHOICES
    )

    discount_value = models.DecimalField(
        max_digits=10,
        decimal_places=2
    )

    minimum_order_amount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=0
    )

    maximum_discount = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        blank=True,
        null=True
    )

    active = models.BooleanField(
        default=True
    )

    start_date = models.DateTimeField()

    expiry_date = models.DateTimeField()

    usage_limit = models.PositiveIntegerField(
        blank=True,
        null=True
    )

    usage_count = models.PositiveIntegerField(
        default=0
    )

    usage_limit_per_user = models.PositiveIntegerField(
        blank=True,
        null=True
    )

    specific_products = models.ManyToManyField(
        Product,
        blank=True,
        related_name="coupons"
    )

    specific_categories = models.ManyToManyField(
        Category,
        blank=True,
        related_name="coupons"
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def save(self, *args, **kwargs):
        self.code = self.code.strip().upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code

class CouponUsage(models.Model):

    coupon = models.ForeignKey(
        Coupon,
        on_delete=models.CASCADE,
        related_name="usages"
    )

    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="coupon_usages"
    )

    session_key = models.CharField(
        max_length=40,
        blank=True,
        null=True,
        db_index=True
    )

    order = models.ForeignKey(
        Order,
        on_delete=models.CASCADE,
        related_name="coupon_usage"
    )

    used_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        if self.user:
            return f"{self.coupon.code} - {self.user.username}"

        return f"{self.coupon.code} - Guest" 

