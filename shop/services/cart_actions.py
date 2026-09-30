from shop.models import Product, CartItem
from shop.views import get_cart_session_key


def ai_add_to_cart(request, product_slug, quantity=1):
    try:
        product = Product.objects.get(
            slug=product_slug,
            is_available=True
        )
    except Product.DoesNotExist:
        return {
            "success": False,
            "message": "I couldn't find that product in our store."
        }

    if product.stock <= 0:
        return {
            "success": False,
            "message": f"{product.name} is currently out of stock."
        }

    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    session_key = get_cart_session_key(request)

    cart_item, created = CartItem.objects.get_or_create(
        session_key=session_key,
        product=product
    )

    if created:
        cart_item.quantity = min(quantity, product.stock)
    else:
        cart_item.quantity += quantity

        if cart_item.quantity > product.stock:
            cart_item.quantity = product.stock

    cart_item.save()

    return {
        "success": True,
        "message": f"{product.name} has been added to your cart.",
        "product_name": product.name,
        "product_slug": product.slug,
        "quantity": cart_item.quantity,
    }