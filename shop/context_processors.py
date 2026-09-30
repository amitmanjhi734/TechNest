from django.db.models import Sum
from .models import CartItem, WishlistItem


def shop_context(request):
    """
    Globally provide cart_count and wishlist_count across all templates.
    """
    cart_count = 0
    wishlist_count = 0

    try:
        session_key = request.session.session_key

        if request.user.is_authenticated:
            cart_count = CartItem.objects.filter(
                user=request.user
            ).aggregate(total=Sum("quantity"))["total"] or 0

            wishlist_count = WishlistItem.objects.filter(
                user=request.user
            ).count()
        elif session_key:
            cart_count = CartItem.objects.filter(
                session_key=session_key,
                user__isnull=True
            ).aggregate(total=Sum("quantity"))["total"] or 0

            wishlist_count = WishlistItem.objects.filter(
                session_key=session_key,
                user__isnull=True
            ).count()
    except Exception:
        cart_count = 0
        wishlist_count = 0

    return {
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
    }
