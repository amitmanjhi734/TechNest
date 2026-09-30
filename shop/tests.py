from decimal import Decimal
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone

from .models import Category, Product, CartItem, Coupon, CouponUsage, Order


class CouponSystemTests(TestCase):
    def setUp(self):
        self.category = Category.objects.create(
            name="Gaming",
            slug="gaming",
        )
        self.other_category = Category.objects.create(
            name="Laptops",
            slug="laptops",
        )

        self.product = Product.objects.create(
            category=self.category,
            name="Gaming Console",
            slug="gaming-console",
            brand="TechNest",
            description="Test product",
            price=Decimal("10000.00"),
            discount_price=Decimal("9000.00"),
            stock=10,
        )
        self.other_product = Product.objects.create(
            category=self.other_category,
            name="Laptop",
            slug="laptop",
            brand="TechNest",
            description="Test product",
            price=Decimal("20000.00"),
            stock=10,
        )

        now = timezone.now()
        self.coupon = Coupon.objects.create(
            code="TECH10",
            discount_type="percentage",
            discount_value=Decimal("10"),
            minimum_order_amount=Decimal("5000"),
            maximum_discount=Decimal("500"),
            active=True,
            start_date=now - timedelta(days=1),
            expiry_date=now + timedelta(days=1),
        )

    def add_to_guest_cart(self, product, quantity=1):
        session = self.client.session
        if not session.session_key:
            session.create()
        session_key = session.session_key
        CartItem.objects.create(
            session_key=session_key,
            product=product,
            quantity=quantity,
        )
        return session_key

    def test_percentage_coupon_uses_effective_discounted_product_price(self):
        self.add_to_guest_cart(self.product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "tech10"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data["success"])
        self.assertEqual(data["subtotal"], "9000.00")
        self.assertEqual(data["discount"], "500.00")
        self.assertEqual(data["total"], "8500.00")

    def test_coupon_rejects_cart_below_minimum(self):
        self.product.discount_price = Decimal("4000.00")
        self.product.save(update_fields=["discount_price"])
        self.add_to_guest_cart(self.product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()["success"])
        self.assertIn("Minimum order amount", response.json()["error"])

    def test_product_and_category_restrictions_use_or_logic(self):
        self.coupon.specific_products.add(self.product)
        self.coupon.specific_categories.add(self.other_category)

        self.add_to_guest_cart(self.product)
        self.add_to_guest_cart(self.other_product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )

        self.assertEqual(response.status_code, 200)
        data = response.json()

        # Both products qualify: ₹9,000 + ₹20,000 = ₹29,000.
        # Maximum discount limits the 10% discount to ₹500.
        self.assertEqual(data["subtotal"], "29000.00")
        self.assertEqual(data["discount"], "500.00")


    def test_product_restriction_has_customer_friendly_message(self):
        self.coupon.specific_products.add(self.product)
        self.add_to_guest_cart(self.other_product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "This coupon is only valid for Gaming Console."
        )

    def test_category_restriction_has_customer_friendly_message(self):
        self.coupon.specific_categories.add(self.category)
        self.add_to_guest_cart(self.other_product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(
            response.json()["error"],
            "This coupon is only valid for products in the Gaming category."
        )

    def test_coupon_usage_is_recorded_for_cod_order(self):
        self.add_to_guest_cart(self.product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )
        self.assertEqual(response.status_code, 200)

        response = self.client.post(
            "/checkout/",
            {
                "full_name": "Test Customer",
                "phone": "9999999999",
                "address": "Test Address",
                "city": "Test City",
                "pin_code": "700000",
                "payment_method": "cod",
            },
        )

        self.assertEqual(response.status_code, 302)
        order = Order.objects.get(pk=int(response.url.rstrip("/").split("/")[-1]))

        self.assertEqual(order.coupon, self.coupon)
        self.assertEqual(order.coupon_code, "TECH10")
        self.assertEqual(order.coupon_discount, Decimal("500.00"))
        self.assertEqual(order.total_amount, Decimal("8500.00"))
        self.assertEqual(self.coupon.__class__.objects.get(pk=self.coupon.pk).usage_count, 1)
        self.assertEqual(CouponUsage.objects.filter(order=order).count(), 1)

    def test_expired_coupon_is_rejected(self):
        self.coupon.expiry_date = timezone.now() - timedelta(minutes=1)
        self.coupon.save(update_fields=["expiry_date"])
        self.add_to_guest_cart(self.product)

        response = self.client.post(
            "/apply-coupon/",
            {"code": "TECH10"},
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["error"], "This coupon has expired.")
