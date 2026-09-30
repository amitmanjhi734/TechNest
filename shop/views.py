from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.conf import settings
from shop.services.gemini import ask_gemini
from shop.models import Product
from .models import Product, CartItem
from django.db.models import Sum
from django.db import models
from django.contrib.auth.models import User
from decimal import Decimal
from django.utils import timezone
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse

import razorpay

from django.conf import settings
from django.http import JsonResponse

from .models import (
    Category,
    Address,
    Product,
    CartItem,
    WishlistItem,
    Order,
    OrderItem,
    Coupon,
    CouponUsage,
)

def login_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")

        user = authenticate(
            request,
            username=username,
            password=password
        )

        if user is not None:

            # Get the visitor's current session before login
            session_key = get_cart_session_key(request)

            # ---------------------------------
            # MOVE GUEST CART TO USER ACCOUNT
            # ---------------------------------

            guest_cart_items = CartItem.objects.filter(
                session_key=session_key,
                user__isnull=True
            )

            for item in guest_cart_items:

                existing_item = CartItem.objects.filter(
                    user=user,
                    product=item.product
                ).first()

                if existing_item:

                    existing_item.quantity += item.quantity

                    if existing_item.quantity > item.product.stock:
                        existing_item.quantity = item.product.stock

                    existing_item.save()
                    item.delete()

                else:

                    item.user = user
                    item.save(update_fields=["user"])

            # ---------------------------------
            # MOVE GUEST WISHLIST TO USER
            # ---------------------------------

            guest_wishlist_items = WishlistItem.objects.filter(
                session_key=session_key,
                user__isnull=True
            )

            for item in guest_wishlist_items:

                existing_item = WishlistItem.objects.filter(
                    user=user,
                    product=item.product
                ).first()

                if existing_item:
                    item.delete()
                else:
                    item.user = user
                    item.save(update_fields=["user"])

            # Login after transferring the data
            login(request, user)

            next_url = request.POST.get("next") or request.GET.get("next")

            if next_url:
                return redirect(next_url)

            return redirect("home")

        messages.error(request, "Invalid username or password.")

    return render(request, "shop/login.html")
    
def logout_view(request):
    logout(request)
    return redirect("home")


@login_required
def saved_addresses(request):
    """Manage the logged-in customer's saved delivery addresses."""
    addresses = Address.objects.filter(user=request.user).order_by(
        "-is_default", "-updated_at"
    )

    if request.method == "POST":
        action = request.POST.get("action", "add").strip().lower()

        if action == "delete":
            address_id = request.POST.get("address_id", "").strip()
            address = None
            if address_id.isdigit():
                address = Address.objects.filter(
                    id=int(address_id),
                    user=request.user,
                ).first()

            if not address:
                messages.error(request, "That saved address could not be found.")
                return redirect("saved_addresses")

            was_default = address.is_default
            address.delete()

            if was_default:
                replacement = Address.objects.filter(
                    user=request.user
                ).order_by("-updated_at").first()
                if replacement:
                    replacement.is_default = True
                    replacement.save(update_fields=["is_default", "updated_at"])

            messages.success(request, "Saved address removed successfully.")
            return redirect("saved_addresses")

        if action == "add":
            label = request.POST.get("address_label", "home").strip().lower()
            full_name = request.POST.get("full_name", "").strip()
            phone = request.POST.get("phone", "").strip()
            address_text = request.POST.get("address", "").strip()
            city = request.POST.get("city", "").strip()
            pin_code = request.POST.get("pin_code", "").strip()
            make_default = request.POST.get("make_default") == "1"

            if label not in {"home", "office", "other"}:
                label = "home"

            if not all([full_name, phone, address_text, city, pin_code]):
                messages.error(request, "Please fill in all address fields.")
                return render(
                    request,
                    "shop/saved_addresses.html",
                    {"saved_addresses": addresses},
                )

            has_existing = Address.objects.filter(user=request.user).exists()

            if make_default or not has_existing:
                Address.objects.filter(
                    user=request.user,
                    is_default=True,
                ).update(is_default=False)

            Address.objects.create(
                user=request.user,
                label=label,
                full_name=full_name,
                phone=phone,
                address=address_text,
                city=city,
                pin_code=pin_code,
                is_default=(make_default or not has_existing),
            )

            messages.success(request, "New address saved successfully.")
            return redirect("saved_addresses")

    return render(
        request,
        "shop/saved_addresses.html",
        {"saved_addresses": addresses},
    )

def ai_chat(request):

    if request.method != "POST":
        return JsonResponse(
            {
                "success": False,
                "message": "Invalid request method"
            },
            status=405
        )

    message = request.POST.get("message", "").strip()

    if not message:
        return JsonResponse(
            {
                "success": False,
                "message": "Message is required"
            },
            status=400
        )

    # ==============================
    # AI CHAT HISTORY
    # ==============================

    history = request.session.get(
        "ai_chat_history",
        []
    )

    # ==============================
    # ASK GEMINI
    # ==============================

    result = ask_gemini(
        message,
        history
    )

    reply = result.get(
        "reply",
        ""
    )

    recommended_slug = result.get(
        "recommended_slug"
    )

    action = result.get(
        "action",
        "none"
    )

    quantity = result.get(
        "quantity",
        1
    )

    # Make sure quantity is always valid
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        quantity = 1

    if quantity < 1:
        quantity = 1

    # ==============================
    # SESSION KEY
    # ==============================

    session_key = get_cart_session_key(
        request
    )

    # ==============================
    # AI CART ACTION
    # ==============================

    if (
        action == "add_to_cart"
        and recommended_slug
    ):

        product = Product.objects.filter(
            slug=recommended_slug,
            is_available=True
        ).first()

        if product:

            # Limit quantity to available stock
            if quantity > product.stock:
                quantity = product.stock

            # --------------------------------
            # LOGGED-IN USER CART
            # --------------------------------

            if request.user.is_authenticated:

                cart_item = CartItem.objects.filter(
                    user=request.user,
                    product=product
                ).first()

                if cart_item:

                    cart_item.quantity += quantity

                    if cart_item.quantity > product.stock:
                        cart_item.quantity = product.stock

                else:

                    cart_item = CartItem.objects.create(
                        user=request.user,
                        session_key=session_key,
                        product=product,
                        quantity=quantity
                    )

            # --------------------------------
            # GUEST CART
            # --------------------------------

            else:

                cart_item, created = CartItem.objects.get_or_create(
                    session_key=session_key,
                    user__isnull=True,
                    product=product
                )

                if created:

                    cart_item.quantity = quantity

                else:

                    cart_item.quantity += quantity

                    if cart_item.quantity > product.stock:
                        cart_item.quantity = product.stock

            cart_item.save()

    # ==============================
    # AI WISHLIST ACTION
    # ==============================

    elif (
        action == "add_to_wishlist"
        and recommended_slug
    ):

        product = Product.objects.filter(
            slug=recommended_slug,
            is_available=True
        ).first()

        if product:

            # --------------------------------
            # LOGGED-IN USER WISHLIST
            # --------------------------------

            if request.user.is_authenticated:

                wishlist_item = WishlistItem.objects.filter(
                    user=request.user,
                    product=product
                ).first()

                # Don't create duplicates
                if not wishlist_item:

                    WishlistItem.objects.create(
                        user=request.user,
                        session_key=session_key,
                        product=product
                    )

            # --------------------------------
            # GUEST WISHLIST
            # --------------------------------

            else:

                wishlist_item = WishlistItem.objects.filter(
                    session_key=session_key,
                    user__isnull=True,
                    product=product
                ).first()

                # Don't create duplicates
                if not wishlist_item:

                    WishlistItem.objects.create(
                        session_key=session_key,
                        product=product
                    )

    # ==============================
    # PRODUCT DATA
    # ==============================

    product_data = None

    if recommended_slug:

        product = Product.objects.filter(
            slug=recommended_slug
        ).first()

        if product:

            product_data = {
                "name": product.name,

                "slug": product.slug,

                "image": (
                    product.image.url
                    if product.image
                    else None
                ),

                "price": str(
                    product.discount_price
                    if product.discount_price
                    else product.price
                ),

                "original_price": (
                    str(product.price)
                    if product.discount_price
                    else None
                ),

                "rating": str(
                    product.rating
                ),

                "stock": product.stock,

                "is_available": (
                    product.is_available
                ),

                "url": reverse(
                    "product_detail",
                    args=[product.slug]
                ),
            }

    # ==============================
    # SAVE AI CHAT HISTORY
    # ==============================

    history.append({
        "user": message,
        "assistant": reply
    })

    request.session[
        "ai_chat_history"
    ] = history

    request.session.modified = True

    # ==============================
    # CART COUNT
    # ==============================

    if request.user.is_authenticated:

        cart_count = CartItem.objects.filter(
            user=request.user
        ).aggregate(
            total=Sum("quantity")
        )["total"] or 0

    else:

        cart_count = CartItem.objects.filter(
            session_key=session_key,
            user__isnull=True
        ).aggregate(
            total=Sum("quantity")
        )["total"] or 0

    # ==============================
    # WISHLIST COUNT
    # ==============================

    if request.user.is_authenticated:

        wishlist_count = WishlistItem.objects.filter(
            user=request.user
        ).count()

    else:

        wishlist_count = WishlistItem.objects.filter(
            session_key=session_key,
            user__isnull=True
        ).count()

    # ==============================
    # AI RESPONSE
    # ==============================

    return JsonResponse({
        "success": True,
        "reply": reply,
        "product": product_data,
        "action": action,
        "quantity": quantity,
        "cart_count": cart_count,
        "wishlist_count": wishlist_count
    })

def register_view(request):
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")

        if not username or not password or not password2:
            messages.error(request, "All fields are required.")
            return render(request, "shop/register.html")

        if password != password2:
            messages.error(request, "Passwords do not match.")
            return render(request, "shop/register.html")

        if User.objects.filter(username=username).exists():
            messages.error(request, "Username already exists.")
            return render(request, "shop/register.html")

        user = User.objects.create_user(
            username=username,
            password=password
        )

        login(request, user)

        return redirect("home")

    return render(request, "shop/register.html")

    # ==============================
    # PRODUCT DATA
    # ==============================

    product_data = None

    if recommended_slug:
        product = Product.objects.filter(
            slug=recommended_slug
        ).first()

        if product:
            product_data = {
                "name": product.name,
                "slug": product.slug,
                "image": (
                    product.image.url
                    if product.image
                    else None
                ),
                "price": str(
                    product.discount_price
                    if product.discount_price
                    else product.price
                ),
                "original_price": (
                    str(product.price)
                    if product.discount_price
                    else None
                ),
                "rating": str(product.rating),
                "stock": product.stock,
                "is_available": product.is_available,
                "url": reverse(
                    "product_detail",
                    args=[product.slug]
                ),
            }

    history.append({
        "user": message,
        "assistant": reply
    })

    request.session["ai_chat_history"] = history
    request.session.modified = True

        # ==============================
    # CART & WISHLIST COUNT
    # ==============================

    session_key = get_cart_session_key(request)

    if request.user.is_authenticated:

        cart_count = CartItem.objects.filter(
            user=request.user
        ).aggregate(
            total=Sum("quantity")
        )["total"] or 0

        wishlist_count = WishlistItem.objects.filter(
            user=request.user
        ).count()

    else:

        cart_count = CartItem.objects.filter(
            session_key=session_key,
            user__isnull=True
        ).aggregate(
            total=Sum("quantity")
        )["total"] or 0

        wishlist_count = WishlistItem.objects.filter(
            session_key=session_key,
            user__isnull=True
        ).count()

    # ==============================
    # AI RESPONSE
    # ==============================

    return JsonResponse({
        "success": True,
        "reply": reply,
        "product": product_data,
        "action": action,
        "quantity": quantity,
        "cart_count": cart_count,
        "wishlist_count": wishlist_count
    })

def get_cart_session_key(request):
    """
    Make sure the visitor has a Django session,
    then return its unique session key.
    """
    if not request.session.session_key:
        request.session.create()

    return request.session.session_key

def home(request):
    categories = Category.objects.all()

    selected_category = request.GET.get("category")
    search_query = request.GET.get("search", "").strip()

    if selected_category:
        products = Product.objects.filter(
            category__slug=selected_category
        )
    else:
        products = Product.objects.all()

    if search_query:
        search_words = search_query.split()

        for word in search_words:
            products = products.filter(
                Q(name__icontains=word)
                | Q(brand__icontains=word)
                | Q(category__name__icontains=word)
            )

    # ==============================
    # FEATURED PRODUCT
    # ==============================

    featured_product = Product.objects.filter(
        name__icontains="Samsung Galaxy S25",
        is_available=True
    ).first()

    # ==============================
    # ACTIVE COUPON FEATURE SLIDES
    # ==============================
    # Only show coupons that are genuinely usable right now.
    # This keeps the homepage synchronized with the same coupon records
    # customers use at checkout. No hard-coded promo codes or expiry dates.
    now = timezone.now()
    active_coupons = Coupon.objects.filter(
        active=True,
        start_date__lte=now,
        expiry_date__gte=now,
    ).prefetch_related(
        "specific_products",
        "specific_categories",
    ).order_by("expiry_date", "-created_at")

    coupon_slides = []

    for coupon in active_coupons:
        # A coupon whose total usage limit has already been reached should
        # never appear as a live homepage offer.
        if coupon.usage_limit is not None and coupon.usage_count >= coupon.usage_limit:
            continue

        specific_products = list(coupon.specific_products.all())
        specific_categories = list(coupon.specific_categories.all())

        # Choose a real TechNest product image to represent the coupon.
        # Product restrictions take priority; category restrictions come next;
        # site-wide coupons fall back to the existing featured product.
        featured_coupon_product = None

        for product in specific_products:
            if product.is_available and product.stock > 0 and product.image:
                featured_coupon_product = product
                break

        if featured_coupon_product is None:
            category_ids = [category.id for category in specific_categories]
            if category_ids:
                featured_coupon_product = Product.objects.filter(
                    category_id__in=category_ids,
                    is_available=True,
                    stock__gt=0,
                ).exclude(
                    image=""
                ).exclude(
                    image__isnull=True
                ).order_by("-created_at").first()

        if featured_coupon_product is None:
            if featured_product and featured_product.is_available and featured_product.stock > 0 and featured_product.image:
                featured_coupon_product = featured_product
            else:
                featured_coupon_product = Product.objects.filter(
                    is_available=True,
                    stock__gt=0,
                ).exclude(
                    image=""
                ).exclude(
                    image__isnull=True
                ).order_by("-created_at").first()

        if coupon.discount_type == "percentage":
            discount_label = f"{coupon.discount_value:g}% OFF"
        else:
            discount_label = f"₹{coupon.discount_value:,.0f} OFF"

        if specific_products:
            if len(specific_products) == 1:
                offer_title = f"Get the {specific_products[0].name} with {discount_label}"
            else:
                offer_title = f"Save {discount_label} on selected products"
            offer_description = "Use this coupon on the featured product before the offer expires."
        elif specific_categories:
            if len(specific_categories) == 1:
                offer_title = f"Save {discount_label} on {specific_categories[0].name}"
            else:
                offer_title = f"Save {discount_label} on selected categories"
            offer_description = "Shop eligible TechNest products and use the coupon before it expires."
        else:
            offer_title = f"Get {discount_label} across TechNest"
            offer_description = "Use this live TechNest coupon on eligible products before the offer expires."

        coupon_slides.append({
            "coupon": coupon,
            "product": featured_coupon_product,
            "discount_label": discount_label,
            "offer_title": offer_title,
            "offer_description": offer_description,
            "expiry_iso": coupon.expiry_date.isoformat(),
        })

    # ==============================
    # USER / GUEST CART & WISHLIST
    # ==============================

    session_key = get_cart_session_key(request)

    if request.user.is_authenticated:

        cart_items = CartItem.objects.filter(
            user=request.user
        )

        wishlist_items = WishlistItem.objects.filter(
            user=request.user
        )

    else:

        cart_items = CartItem.objects.filter(
            session_key=session_key
        )

        wishlist_items = WishlistItem.objects.filter(
            session_key=session_key
        )

    cart_count = sum(
        item.quantity
        for item in cart_items
    )

    wishlist_count = wishlist_items.count()
    wishlist_product_ids = set(
        wishlist_items.values_list(
            "product_id",
            flat=True
        )
    )

    return render(request, "shop/home.html", {
        "categories": categories,
        "products": products,
        "cart_count": cart_count,
        "wishlist_count": wishlist_count,
        "wishlist_product_ids": wishlist_product_ids,

        # Featured product for homepage
        "featured_product": featured_product,

        # Live coupon offers for the homepage carousel
        "coupon_slides": coupon_slides,
    })

def product_detail(request, slug):
    product = get_object_or_404(Product, slug=slug)

    return render(request, 'shop/product_detail.html', {
        'product': product,
    })

def wishlist(request):

    session_key = get_cart_session_key(request)

    # ==============================
    # LOGGED-IN USER WISHLIST
    # ==============================

    if request.user.is_authenticated:

        wishlist_items = WishlistItem.objects.filter(
            user=request.user
        ).select_related("product")

    # ==============================
    # GUEST WISHLIST
    # ==============================

    else:

        wishlist_items = WishlistItem.objects.filter(
            session_key=session_key
        ).select_related("product")

    return render(request, "shop/wishlist.html", {
        "wishlist_items": wishlist_items,
    })

def add_to_wishlist(request, slug):

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method"
        }, status=405)

    product = get_object_or_404(Product, slug=slug)

    session_key = get_cart_session_key(request)

def add_to_wishlist(request, slug):

    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "message": "Invalid request method"
        }, status=405)

    product = get_object_or_404(
        Product,
        slug=slug
    )

    session_key = get_cart_session_key(request)

    # ==============================
    # LOGGED-IN USER
    # ==============================

    if request.user.is_authenticated:

        wishlist_item = WishlistItem.objects.filter(
            user=request.user,
            product=product
        ).first()

        if wishlist_item:

            wishlist_item.delete()

            wishlist_count = WishlistItem.objects.filter(
                user=request.user
            ).count()

            return JsonResponse({
                "success": True,
                "wishlisted": False,
                "message": "Product removed from wishlist",
                "wishlist_count": wishlist_count
            })

        WishlistItem.objects.create(
            user=request.user,
            session_key=session_key,
            product=product
        )

        wishlist_count = WishlistItem.objects.filter(
            user=request.user
        ).count()

    # ==============================
    # GUEST USER
    # ==============================

    else:

        wishlist_item = WishlistItem.objects.filter(
            session_key=session_key,
            product=product
        ).first()

        if wishlist_item:

            wishlist_item.delete()

            wishlist_count = WishlistItem.objects.filter(
                session_key=session_key
            ).count()

            return JsonResponse({
                "success": True,
                "wishlisted": False,
                "message": "Product removed from wishlist",
                "wishlist_count": wishlist_count
            })

        WishlistItem.objects.create(
            session_key=session_key,
            product=product
        )

        wishlist_count = WishlistItem.objects.filter(
            session_key=session_key
        ).count()

    return JsonResponse({
        "success": True,
        "wishlisted": True,
        "message": "Product added to wishlist",
        "wishlist_count": wishlist_count
    })


    if wishlist_item:
        wishlist_item.delete()
        return JsonResponse({
            "success": True,
            "wishlisted": False,
            "message": "Product removed from wishlist",
            "wishlist_count": WishlistItem.objects.filter(
            session_key=session_key
        ).count()
    })

    WishlistItem.objects.create(
        session_key=session_key,
        product=product
    )

    return JsonResponse({
    "success": True,
    "wishlisted": True,
    "message": "Product added to wishlist",
    "wishlist_count": WishlistItem.objects.filter(
        session_key=session_key
    ).count()
})



def remove_from_wishlist(request, slug):

    product = get_object_or_404(
        Product,
        slug=slug
    )

    session_key = get_cart_session_key(request)

    if request.user.is_authenticated:

        WishlistItem.objects.filter(
            user=request.user,
            product=product
        ).delete()

    else:

        WishlistItem.objects.filter(
            session_key=session_key,
            product=product
        ).delete()

    return redirect("wishlist")

def add_to_cart(request, slug):

    product = get_object_or_404(Product, slug=slug)

    session_key = get_cart_session_key(request)

    if request.method == "POST":

        quantity = int(request.POST.get("quantity", 1))

        if quantity < 1:
            quantity = 1

        if quantity > product.stock:
            quantity = product.stock

        # ==============================
        # LOGGED-IN USER CART
        # ==============================

        if request.user.is_authenticated:

            cart_item = CartItem.objects.filter(
                user=request.user,
                product=product
            ).first()

            if cart_item:

                cart_item.quantity += quantity

                if cart_item.quantity > product.stock:
                    cart_item.quantity = product.stock

            else:

                cart_item = CartItem.objects.create(
                    user=request.user,
                    session_key=session_key,
                    product=product,
                    quantity=quantity
                )

        # ==============================
        # GUEST CART
        # ==============================

        else:

            cart_item, created = CartItem.objects.get_or_create(
            session_key=session_key,
            user__isnull=True,
            product=product
        )

            if created:

                cart_item.quantity = quantity

            else:

                cart_item.quantity += quantity

                if cart_item.quantity > product.stock:
                    cart_item.quantity = product.stock

        cart_item.save()

    return redirect("cart")
    
def buy_now(request, slug):
    product = get_object_or_404(Product, slug=slug)

    if request.method == "POST":

        quantity = int(request.POST.get("quantity", 1))

        if quantity < 1:
            quantity = 1

        if quantity > product.stock:
            quantity = product.stock

        # Store Buy Now selection temporarily in the session
        request.session["buy_now_product_id"] = product.id
        request.session["buy_now_quantity"] = quantity

        return redirect("checkout")

    return redirect(
        "product_detail",
        slug=product.slug
    )


def cart(request):

    session_key = get_cart_session_key(request)

    # Clear any old Buy Now selection when using the normal cart
    request.session.pop("buy_now_product_id", None)
    request.session.pop("buy_now_quantity", None)

    # ==============================
    # LOGGED-IN USER CART
    # ==============================

    if request.user.is_authenticated:

        cart_items = CartItem.objects.filter(
            user=request.user
        ).select_related("product")

    # ==============================
    # GUEST CART
    # ==============================

    else:

        cart_items = CartItem.objects.filter(
            session_key=session_key
        ).select_related("product")

    total = sum(
        item.get_total_price()
        for item in cart_items
    )

    return render(request, "shop/cart.html", {
        "cart_items": cart_items,
        "total": total,
    })

def increase_quantity(request, slug):
    product = get_object_or_404(Product, slug=slug)

    session_key = get_cart_session_key(request)

    if request.method == "POST":

        if request.user.is_authenticated:

            cart_item = CartItem.objects.filter(
                user=request.user,
                product=product
            ).first()

        else:

            cart_item = CartItem.objects.filter(
                session_key=session_key,
                product=product
            ).first()

        if cart_item:

            if cart_item.quantity < product.stock:
                cart_item.quantity += 1
                cart_item.save()

    return redirect("cart")


def decrease_quantity(request, slug):
    product = get_object_or_404(Product, slug=slug)

    session_key = get_cart_session_key(request)

    if request.method == "POST":

        if request.user.is_authenticated:

            cart_item = CartItem.objects.filter(
                user=request.user,
                product=product
            ).first()

        else:

            cart_item = CartItem.objects.filter(
                session_key=session_key,
                product=product
            ).first()

        if cart_item:

            if cart_item.quantity > 1:
                cart_item.quantity -= 1
                cart_item.save()
            else:
                cart_item.delete()

    return redirect("cart")


def remove_from_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)

    session_key = get_cart_session_key(request)

    if request.method == "POST":

        if request.user.is_authenticated:

            CartItem.objects.filter(
                user=request.user,
                product=product
            ).delete()

        else:

            CartItem.objects.filter(
                session_key=session_key,
                product=product
            ).delete()

    return redirect("cart")

class CheckoutItem:
    """Lightweight checkout item used for Buy Now flows."""

    def __init__(self, product, quantity):
        self.product = product
        self.quantity = int(quantity)

    def get_total_price(self):
        price = self.product.discount_price or self.product.price
        return price * self.quantity


def get_checkout_items(request):
    """Return the exact items being checked out for this request."""
    buy_now_product_id = request.session.get("buy_now_product_id")
    buy_now_quantity = request.session.get("buy_now_quantity")

    if buy_now_product_id and buy_now_quantity:
        product = get_object_or_404(
            Product.objects.select_related("category"),
            id=buy_now_product_id,
            is_available=True,
        )
        return [CheckoutItem(product, buy_now_quantity)]

    if request.user.is_authenticated:
        return list(
            CartItem.objects.filter(
                user=request.user
            ).select_related("product", "product__category")
        )

    session_key = get_cart_session_key(request)
    return list(
        CartItem.objects.filter(
            session_key=session_key,
            user__isnull=True,
        ).select_related("product", "product__category")
    )


def get_coupon_usage_filter(request, coupon):
    """Return the identity used for per-user coupon limits."""
    usage_filter = {"coupon": coupon}

    if request.user.is_authenticated:
        usage_filter["user"] = request.user
    else:
        usage_filter["session_key"] = get_cart_session_key(request)

    return usage_filter


def calculate_coupon_discount(coupon, cart_items):
    """
    Validate coupon rules against the current checkout items and return:
    (subtotal, discount, error_message).
    """
    subtotal = sum(
        item.get_total_price()
        for item in cart_items
    )

    if subtotal <= 0:
        return Decimal("0"), Decimal("0"), "Your cart is empty."

    if subtotal < coupon.minimum_order_amount:
        return (
            subtotal,
            Decimal("0"),
            f"Minimum order amount for this coupon is ₹{coupon.minimum_order_amount}."
        )

    specific_products = coupon.specific_products.all()
    specific_categories = coupon.specific_categories.all()

    has_product_restriction = specific_products.exists()
    has_category_restriction = specific_categories.exists()

    product_ids = set(
        specific_products.values_list("id", flat=True)
    ) if has_product_restriction else set()

    category_ids = set(
        specific_categories.values_list("id", flat=True)
    ) if has_category_restriction else set()

    eligible_subtotal = Decimal("0")

    for item in cart_items:
        product = item.product

        eligible = (
            not has_product_restriction
            and not has_category_restriction
        )

        if has_product_restriction and product.id in product_ids:
            eligible = True

        if has_category_restriction and product.category_id in category_ids:
            eligible = True

        if eligible:
            eligible_subtotal += item.get_total_price()

    if eligible_subtotal <= 0:
        # Give the customer a useful explanation instead of a generic
        # "does not apply" message. This is especially helpful when a
        # coupon is restricted to particular products/categories.
        if has_product_restriction and not has_category_restriction:
            product_names = list(
                specific_products.values_list("name", flat=True)
            )

            if len(product_names) == 1:
                restriction_message = (
                    f"This coupon is only valid for {product_names[0]}."
                )
            else:
                restriction_message = (
                    "This coupon is only valid for these products: "
                    + ", ".join(product_names)
                    + "."
                )

        elif has_category_restriction and not has_product_restriction:
            category_names = list(
                specific_categories.values_list("name", flat=True)
            )

            if len(category_names) == 1:
                restriction_message = (
                    f"This coupon is only valid for products in the "
                    f"{category_names[0]} category."
                )
            else:
                restriction_message = (
                    "This coupon is only valid for products in these "
                    "categories: "
                    + ", ".join(category_names)
                    + "."
                )

        else:
            # Both product and category restrictions are present and use OR
            # logic, so explain both sides to the customer.
            product_names = list(
                specific_products.values_list("name", flat=True)
            )
            category_names = list(
                specific_categories.values_list("name", flat=True)
            )

            restriction_parts = []

            if product_names:
                if len(product_names) == 1:
                    restriction_parts.append(product_names[0])
                else:
                    restriction_parts.append(
                        "these products: " + ", ".join(product_names)
                    )

            if category_names:
                if len(category_names) == 1:
                    restriction_parts.append(
                        f"products in the {category_names[0]} category"
                    )
                else:
                    restriction_parts.append(
                        "products in these categories: "
                        + ", ".join(category_names)
                    )

            restriction_message = (
                "This coupon is only valid for "
                + " or ".join(restriction_parts)
                + "."
            )

        return subtotal, Decimal("0"), restriction_message

    if coupon.discount_type == "percentage":
        discount = (
            eligible_subtotal
            * coupon.discount_value
            / Decimal("100")
        )
    else:
        discount = coupon.discount_value

    if coupon.maximum_discount is not None:
        discount = min(discount, coupon.maximum_discount)

    # A coupon can never reduce the order below zero.
    discount = min(discount, eligible_subtotal)

    # Currency values are stored to two decimal places.
    discount = discount.quantize(Decimal("0.01"))

    return subtotal, discount, None


def validate_coupon_for_request(request, code, cart_items=None):
    """Validate a coupon against current account/session and checkout items."""
    code = (code or "").strip().upper()

    if not code:
        return None, Decimal("0"), Decimal("0"), "Please enter a coupon code."

    try:
        coupon = Coupon.objects.get(code=code)
    except Coupon.DoesNotExist:
        return None, Decimal("0"), Decimal("0"), "Invalid coupon code."

    if not coupon.active:
        return None, Decimal("0"), Decimal("0"), "This coupon is currently inactive."

    now = timezone.now()

    if now < coupon.start_date:
        return None, Decimal("0"), Decimal("0"), "This coupon is not active yet."

    if now > coupon.expiry_date:
        return None, Decimal("0"), Decimal("0"), "This coupon has expired."

    if (
        coupon.usage_limit is not None
        and coupon.usage_count >= coupon.usage_limit
    ):
        return None, Decimal("0"), Decimal("0"), "This coupon has reached its usage limit."

    usage_filter = get_coupon_usage_filter(request, coupon)
    user_usage_count = CouponUsage.objects.filter(**usage_filter).count()

    if (
        coupon.usage_limit_per_user is not None
        and user_usage_count >= coupon.usage_limit_per_user
    ):
        return None, Decimal("0"), Decimal("0"), (
            "You have reached the usage limit for this coupon."
        )

    if cart_items is None:
        cart_items = get_checkout_items(request)

    if not cart_items:
        return None, Decimal("0"), Decimal("0"), "Your cart is empty."

    subtotal, discount, error = calculate_coupon_discount(
        coupon,
        cart_items,
    )

    if error:
        return None, subtotal, Decimal("0"), error

    return coupon, subtotal, discount, None


def clear_coupon_session(request):
    request.session.pop("coupon_code", None)
    request.session.pop("coupon_discount", None)
    request.session.modified = True


def get_current_coupon_total(request, cart_items):
    """Recalculate the session coupon against the current checkout."""
    code = request.session.get("coupon_code")

    if not code:
        subtotal = sum(item.get_total_price() for item in cart_items)
        return None, subtotal, Decimal("0"), subtotal, None

    coupon, subtotal, discount, error = validate_coupon_for_request(
        request,
        code,
        cart_items,
    )

    if error:
        clear_coupon_session(request)
        return None, subtotal, Decimal("0"), subtotal, error

    # Keep the session value synchronized with the current cart.
    request.session["coupon_code"] = coupon.code
    request.session["coupon_discount"] = str(discount)
    request.session.modified = True

    return coupon, subtotal, discount, subtotal - discount, None


def record_coupon_usage(order, request):
    """Record one successful coupon use and increment its usage count."""
    if not order.coupon_id:
        return

    with transaction.atomic():
        coupon = Coupon.objects.select_for_update().get(
            pk=order.coupon_id
        )

        # Idempotency: payment verification may be retried.
        if CouponUsage.objects.filter(order=order).exists():
            return

        if (
            coupon.usage_limit is not None
            and coupon.usage_count >= coupon.usage_limit
        ):
            raise ValueError("This coupon has reached its usage limit.")

        usage_filter = {"coupon": coupon}

        if order.user_id:
            usage_filter["user_id"] = order.user_id
        else:
            usage_filter["session_key"] = order.session_key

        if (
            coupon.usage_limit_per_user is not None
            and CouponUsage.objects.filter(**usage_filter).count()
            >= coupon.usage_limit_per_user
        ):
            raise ValueError(
                "This coupon has reached the usage limit for this customer."
            )

        CouponUsage.objects.create(
            coupon=coupon,
            user=order.user,
            session_key=order.session_key,
            order=order,
        )

        coupon.usage_count += 1
        coupon.save(update_fields=["usage_count"])


def apply_coupon(request):
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Invalid request method."
        }, status=400)

    cart_items = get_checkout_items(request)

    if not cart_items:
        return JsonResponse({
            "success": False,
            "error": "Your cart is empty."
        }, status=400)

    coupon, subtotal, discount, error = validate_coupon_for_request(
        request,
        request.POST.get("code", ""),
        cart_items,
    )

    if error:
        return JsonResponse({
            "success": False,
            "error": error,
        }, status=400)

    request.session["coupon_code"] = coupon.code
    request.session["coupon_discount"] = str(discount)
    request.session.modified = True

    final_total = subtotal - discount

    return JsonResponse({
        "success": True,
        "code": coupon.code,
        "discount": str(discount),
        "subtotal": str(subtotal),
        "total": str(final_total),
        "message": f"Coupon {coupon.code} applied successfully.",
    })



def remove_coupon(request):
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Invalid request method."
        }, status=400)

    cart_items = get_checkout_items(request)
    subtotal = sum((item.get_total_price() for item in cart_items), Decimal("0"))

    clear_coupon_session(request)
    request.session.modified = True

    return JsonResponse({
        "success": True,
        "subtotal": str(subtotal),
        "total": str(subtotal),
        "message": "Coupon removed successfully.",
    })


def get_checkout_saved_addresses(request):
    """Return saved addresses and the preferred default address for logged-in users."""
    if not request.user.is_authenticated:
        return [], None

    addresses = list(
        Address.objects.filter(user=request.user).order_by("-is_default", "-updated_at")
    )
    return addresses, (addresses[0] if addresses else None)


def resolve_checkout_address(request):
    """Resolve the address submitted at checkout, preferring a user's saved address."""
    data = {
        "full_name": request.POST.get("full_name", "").strip(),
        "phone": request.POST.get("phone", "").strip(),
        "address": request.POST.get("address", "").strip(),
        "city": request.POST.get("city", "").strip(),
        "pin_code": request.POST.get("pin_code", "").strip(),
    }

    saved_address = None
    saved_address_id = request.POST.get("saved_address_id", "").strip()

    if request.user.is_authenticated and saved_address_id and saved_address_id != "new":
        saved_address = Address.objects.filter(
            id=saved_address_id,
            user=request.user,
        ).first()

        if saved_address:
            data = {
                "full_name": saved_address.full_name,
                "phone": saved_address.phone,
                "address": saved_address.address,
                "city": saved_address.city,
                "pin_code": saved_address.pin_code,
            }

    return data, saved_address


def maybe_save_checkout_address(request, address_data, selected_saved_address=None):
    """Save a newly entered address when the customer asks us to remember it."""
    if not request.user.is_authenticated or selected_saved_address is not None:
        return None

    if request.POST.get("save_address") != "1":
        return None

    label = request.POST.get("address_label", "home").strip().lower()
    if label not in {"home", "office", "other"}:
        label = "home"

    make_default = request.POST.get("make_default") == "1"
    has_existing = Address.objects.filter(user=request.user).exists()

    if make_default:
        Address.objects.filter(user=request.user, is_default=True).update(is_default=False)

    saved = Address.objects.create(
        user=request.user,
        label=label,
        full_name=address_data["full_name"],
        phone=address_data["phone"],
        address=address_data["address"],
        city=address_data["city"],
        pin_code=address_data["pin_code"],
        is_default=(make_default or not has_existing),
    )

    return saved

def checkout(request):
    session_key = get_cart_session_key(request)
    cart_items = get_checkout_items(request)

    if not cart_items:
        return redirect("cart")

    saved_addresses, default_address = get_checkout_saved_addresses(request)
    selected_address_id = (
        request.POST.get("saved_address_id", "")
        if request.method == "POST"
        else (str(default_address.id) if default_address else "new")
    )

    coupon, subtotal, discount, total, coupon_error = (
        get_current_coupon_total(request, cart_items)
    )

    if request.method == "POST":
        had_coupon = bool(request.session.get("coupon_code"))

        address_data, selected_saved_address = resolve_checkout_address(request)
        full_name = address_data["full_name"]
        phone = address_data["phone"]
        address = address_data["address"]
        city = address_data["city"]
        pin_code = address_data["pin_code"]
        payment_method = request.POST.get("payment_method")

        # Recalculate the coupon on the server immediately before checkout.
        # Never trust the amount shown by JavaScript.
        cart_items = get_checkout_items(request)
        coupon, subtotal, discount, total, coupon_error = (
            get_current_coupon_total(request, cart_items)
        )

        common_context = {
            "cart_items": cart_items,
            "saved_addresses": saved_addresses,
            "selected_address_id": selected_address_id,
            "customer_name": full_name,
            "customer_phone": phone,
            "customer_address": address,
            "customer_city": city,
            "customer_pin_code": pin_code,
            "subtotal": subtotal,
            "coupon": coupon,
            "coupon_discount": discount,
            "total": total,
        }

        if coupon_error and had_coupon:
            common_context.update({
                "coupon": None,
                "coupon_discount": Decimal("0"),
                "total": subtotal,
                "error": coupon_error,
            })
            return render(request, "shop/checkout.html", common_context)

        for item in cart_items:
            if item.quantity > item.product.stock:
                common_context["error"] = (
                    f"Only {item.product.stock} units of "
                    f"{item.product.name} are available."
                )
                return render(request, "shop/checkout.html", common_context)

        if payment_method == "cod":
            with transaction.atomic():
                # Lock the coupon for the final usage check if one is being used.
                if coupon:
                    coupon = Coupon.objects.select_for_update().get(pk=coupon.pk)

                    if (
                        coupon.usage_limit is not None
                        and coupon.usage_count >= coupon.usage_limit
                    ):
                        clear_coupon_session(request)
                        common_context.update({
                            "coupon": None,
                            "coupon_discount": Decimal("0"),
                            "total": subtotal,
                            "error": "This coupon has reached its usage limit.",
                        })
                        return render(request, "shop/checkout.html", common_context)

                    usage_filter = {"coupon": coupon}
                    if request.user.is_authenticated:
                        usage_filter["user"] = request.user
                    else:
                        usage_filter["session_key"] = session_key

                    if (
                        coupon.usage_limit_per_user is not None
                        and CouponUsage.objects.filter(**usage_filter).count()
                        >= coupon.usage_limit_per_user
                    ):
                        clear_coupon_session(request)
                        common_context.update({
                            "coupon": None,
                            "coupon_discount": Decimal("0"),
                            "total": subtotal,
                            "error": (
                                "You have reached the usage limit for this coupon."
                            ),
                        })
                        return render(request, "shop/checkout.html", common_context)

                order = Order.objects.create(
                    session_key=session_key,
                    user=request.user if request.user.is_authenticated else None,
                    full_name=full_name,
                    phone=phone,
                    address=address,
                    city=city,
                    pin_code=pin_code,
                    payment_method="cod",
                    payment_status="pending",
                    coupon=coupon,
                    coupon_code=coupon.code if coupon else None,
                    coupon_discount=discount,
                    total_amount=total,
                )

                for item in cart_items:
                    OrderItem.objects.create(
                        order=order,
                        product=item.product,
                        quantity=item.quantity,
                        price=(
                            item.product.discount_price
                            or item.product.price
                        ),
                    )

                    item.product.stock -= item.quantity
                    item.product.save(update_fields=["stock"])

                if coupon:
                    try:
                        record_coupon_usage(order, request)
                    except ValueError as exc:
                        raise transaction.TransactionManagementError(str(exc))

                # Save a newly entered address only after the order has been
                # successfully created. Existing saved addresses are not duplicated.
                maybe_save_checkout_address(
                    request,
                    address_data,
                    selected_saved_address,
                )

                if not request.session.get("buy_now_product_id"):
                    if request.user.is_authenticated:
                        CartItem.objects.filter(user=request.user).delete()
                    else:
                        CartItem.objects.filter(
                            session_key=session_key,
                            user__isnull=True,
                        ).delete()

                request.session.pop("buy_now_product_id", None)
                request.session.pop("buy_now_quantity", None)
                clear_coupon_session(request)

            return redirect("order_success", order_id=order.id)

        if payment_method != "online":
            common_context["error"] = "Please select a valid payment method."
            return render(request, "shop/checkout.html", common_context)

    # GET: prefill the customer's default saved address when available.
    default_name = default_address.full_name if default_address else ""
    default_phone = default_address.phone if default_address else ""
    default_address_text = default_address.address if default_address else ""
    default_city = default_address.city if default_address else ""
    default_pin = default_address.pin_code if default_address else ""

    return render(request, "shop/checkout.html", {
        "cart_items": cart_items,
        "saved_addresses": saved_addresses,
        "selected_address_id": selected_address_id,
        "subtotal": subtotal,
        "coupon": coupon,
        "coupon_discount": discount,
        "total": total,
        "error": coupon_error if coupon_error and request.method == "GET" else None,
        "customer_name": default_name,
        "customer_phone": default_phone,
        "customer_address": default_address_text,
        "customer_city": default_city,
        "customer_pin_code": default_pin,
    })

def create_razorpay_order(request):
    if request.method != "POST":
        return JsonResponse({
            "success": False,
            "error": "Invalid request method."
        }, status=400)

    session_key = get_cart_session_key(request)
    cart_items = get_checkout_items(request)

    if not cart_items:
        return JsonResponse({
            "success": False,
            "error": "Your cart is empty."
        }, status=400)

    # Always recalculate the amount on the server.
    had_coupon = bool(request.session.get("coupon_code"))
    coupon, subtotal, discount, total, coupon_error = (
        get_current_coupon_total(request, cart_items)
    )

    if coupon_error and had_coupon:
        return JsonResponse({
            "success": False,
            "error": coupon_error,
        }, status=400)

    for item in cart_items:
        if item.quantity > item.product.stock:
            return JsonResponse({
                "success": False,
                "error": (
                    f"Only {item.product.stock} units of "
                    f"{item.product.name} are available."
                )
            }, status=400)

    address_data, selected_saved_address = resolve_checkout_address(request)
    full_name = address_data["full_name"]
    phone = address_data["phone"]
    address = address_data["address"]
    city = address_data["city"]
    pin_code = address_data["pin_code"]

    order = Order.objects.create(
        session_key=session_key,
        user=request.user if request.user.is_authenticated else None,
        full_name=full_name,
        phone=phone,
        address=address,
        city=city,
        pin_code=pin_code,
        payment_method="online",
        payment_status="pending",
        coupon=coupon,
        coupon_code=coupon.code if coupon else None,
        coupon_discount=discount,
        total_amount=total,
    )

    for item in cart_items:
        OrderItem.objects.create(
            order=order,
            product=item.product,
            quantity=item.quantity,
            price=(
                item.product.discount_price
                or item.product.price
            ),
        )

    client = razorpay.Client(
        auth=(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )
    )

    razorpay_amount = int(total * 100)

    razorpay_order = client.order.create({
        "amount": razorpay_amount,
        "currency": "INR",
        "receipt": f"technest_order_{order.id}",
    })

    order.razorpay_order_id = razorpay_order["id"]
    order.save(update_fields=["razorpay_order_id"])

    # Remember a newly entered address after the order has been created.
    # Existing saved addresses are never duplicated.
    maybe_save_checkout_address(
        request,
        address_data,
        selected_saved_address,
    )

    return JsonResponse({
        "success": True,
        "razorpay_key_id": settings.RAZORPAY_KEY_ID,
        "razorpay_order_id": razorpay_order["id"],
        "razorpay_amount": razorpay_amount,
        "order_id": order.id,
        "customer_name": full_name,
        "customer_phone": phone,
    })

def payment_verify(request):
    if request.method != "POST":
        return redirect("cart")

    razorpay_order_id = request.POST.get("razorpay_order_id")
    razorpay_payment_id = request.POST.get("razorpay_payment_id")
    razorpay_signature = request.POST.get("razorpay_signature")

    order = get_object_or_404(
        Order,
        razorpay_order_id=razorpay_order_id
    )

    client = razorpay.Client(
        auth=(
            settings.RAZORPAY_KEY_ID,
            settings.RAZORPAY_KEY_SECRET,
        )
    )

    try:

        # Verify Razorpay signature
        client.utility.verify_payment_signature({
            "razorpay_order_id": razorpay_order_id,
            "razorpay_payment_id": razorpay_payment_id,
            "razorpay_signature": razorpay_signature,
        })

    except razorpay.errors.SignatureVerificationError:

        order.payment_status = "failed"
        order.save()

        return render(request, "shop/payment_failed.html", {
            "order": order,
        })

    # Payment is verified successfully
    with transaction.atomic():

        # Prevent processing the same payment twice
        if order.payment_status == "paid":
            return redirect(
                "order_success",
                order_id=order.id
            )

        # Check stock again
        for item in order.items.all():

            if item.product is None:
                continue

            if item.quantity > item.product.stock:

                order.payment_status = "failed"
                order.save()

                return render(
                    request,
                    "shop/payment_failed.html",
                    {
                        "order": order,
                        "error": (
                            f"Sorry, {item.product.name} "
                            f"is no longer available in the "
                            f"required quantity."
                        ),
                    }
                )

        # Decrease stock
        for item in order.items.all():

            if item.product is not None:

                item.product.stock -= item.quantity
                item.product.save()

         # Save payment information
        from django.utils import timezone

        order.razorpay_payment_id = razorpay_payment_id
        order.payment_status = "paid"
        order.status = "confirmed"

        if order.confirmed_at is None:
            order.confirmed_at = timezone.now()

        order.save()

        # Coupon usage is recorded only after Razorpay payment verification.
        if order.coupon_id:
            record_coupon_usage(order, request)

        # Clear the actual cart only for normal cart checkout
        buy_now_product_id = request.session.get("buy_now_product_id")

    if not buy_now_product_id:
        session_key = get_cart_session_key(request)

        if request.user.is_authenticated:
            CartItem.objects.filter(user=request.user).delete()
        else:
            CartItem.objects.filter(
                session_key=session_key,
                user__isnull=True,
            ).delete()

        # Clear Buy Now selection after successful payment
    request.session.pop("buy_now_product_id", None)
    request.session.pop("buy_now_quantity", None)

    return redirect(
        "order_success",
        order_id=order.id
    )

def order_success(request, order_id):
    order = get_object_or_404(
        Order,
        id=order_id
    )

    return render(request, "shop/order_success.html", {
        "order": order,
    })

def order_detail(request, order_id):
    if not request.user.is_authenticated:
        return redirect("login")

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user
    )

    return render(request, "shop/order_detail.html", {
        "order": order,
    })

def my_orders(request):
    if not request.user.is_authenticated:
        return redirect("login")

    orders = Order.objects.filter(
        user=request.user
    ).order_by("-created_at")

    return render(request, "shop/my_orders.html", {
        "orders": orders,
    })

def my_orders(request):

    session_key = get_cart_session_key(request)

    if request.user.is_authenticated:

        orders = Order.objects.filter(
            user=request.user
        ).order_by("-created_at")

    else:

        orders = Order.objects.filter(
            session_key=session_key
        ).order_by("-created_at")

    return render(request, "shop/my_orders.html", {
        "orders": orders,
    })

def cancel_order(request, order_id):
    if request.method != "POST":
        return redirect("my_orders")

    if not request.user.is_authenticated:
        return redirect("login")

    order = get_object_or_404(
        Order,
        id=order_id,
        user=request.user
    )

    # Order can only be cancelled before it is shipped
    if order.status not in ["pending", "confirmed"]:
        messages.error(
            request,
            "This order can no longer be cancelled."
        )
        return redirect(
            "order_detail",
            order_id=order.id
        )

    # Prevent cancelling the same order twice
    if order.status == "cancelled":
        messages.info(
            request,
            "This order has already been cancelled."
        )
        return redirect(
            "order_detail",
            order_id=order.id
        )

    with transaction.atomic():

        order = Order.objects.select_for_update().get(
            id=order.id,
            user=request.user
    )

        # Restore stock only once
        if not order.stock_restored:

            for item in order.items.all():

                if item.product is not None:
                    item.product.stock += item.quantity
                    item.product.save(
                        update_fields=["stock"]
                    )

            order.stock_restored = True

        from django.utils import timezone

        order.cancelled_from_status = order.status
        order.cancelled_at = timezone.now()
        order.status = "cancelled"

        order.save(
            update_fields=[
                "status",
                "cancelled_from_status",
                "cancelled_at",
                "stock_restored",
            ]
        )

    messages.success(
        request,
        f"Order #{order.id} has been cancelled successfully."
    )

    return redirect(
        "order_detail",
        order_id=order.id
    )
def restore_order_stock(order_id):
    with transaction.atomic():

        order = get_object_or_404(
            Order.objects.select_for_update(),
            id=order_id
        )

        # Already cancelled → do nothing
        if order.status == "cancelled":
            return order

        # Restore stock only once
        if not order.stock_restored:

            for item in order.items.select_related("product"):

                if item.product is not None:

                    item.product.stock += item.quantity
                    item.product.save(
                        update_fields=["stock"]
                    )

            order.stock_restored = True

        # Cancel the order
        from django.utils import timezone

        order.cancelled_from_status = order.status
        order.cancelled_at = timezone.now()
        order.status = "cancelled"

        order.save(
            update_fields=[
                "status",
                "cancelled_from_status",
                "cancelled_at",
                "stock_restored"
            ]
        )

        return order
