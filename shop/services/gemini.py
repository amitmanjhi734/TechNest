import json
from google import genai
from google.genai.types import Schema, Type
from django.conf import settings
from django.db.models import Q

from shop.models import Product

def search_catalog(query):
    stop_words = {
        "i", "me", "my", "a", "an", "the",
        "what", "which", "who", "where", "when",
        "do", "does", "did", "you", "your",
        "have", "has", "had", "is", "are", "am",
        "can", "could", "would", "should",
        "want", "need", "looking", "for",
        "please", "show", "tell", "give",
        "some", "any", "product", "products",
        "thing", "things", "something", "device", "devices",
        "of", "to", "in", "on", "with", "and", "or"
    }

    search_words = [
        word.strip(".,?!")
        for word in query.lower().split()
        if word.strip(".,?!") not in stop_words
    ]

    search_query = Q()

    for word in search_words:
        search_query |= (
            Q(name__icontains=word)
            | Q(brand__icontains=word)
            | Q(category__name__icontains=word)
        )

    products = Product.objects.filter(
        search_query
    ).distinct().select_related("category")

    catalog = []

    for product in products:
        catalog.append({
            "name": product.name,
            "slug": product.slug,
            "category": product.category.name,
            "brand": product.brand,
            "price": str(product.price),
            "discount_price": (
                str(product.discount_price)
                if product.discount_price
                else None
            ),
            "stock": product.stock,
            "rating": str(product.rating),
            "is_available": product.is_available,
        })

    return catalog

def ai_add_to_cart(request, product_slug, quantity=1):
    from shop.models import Product
    from shop.models import CartItem
    from shop.views import get_cart_session_key

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

    if quantity > product.stock:
        quantity = product.stock

    session_key = get_cart_session_key(request)

    cart_item, created = CartItem.objects.get_or_create(
        session_key=session_key,
        product=product
    )

    if created:
        cart_item.quantity = quantity
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
        "quantity": cart_item.quantity
    }

def ask_gemini(message, history=None):
    try:
        if history is None:
            history = []

        catalog = search_catalog(message)

        print("AI MESSAGE:", message)
        print("AI CATALOG:", catalog)

        client = genai.Client(api_key=settings.GEMINI_API_KEY)

        product_slugs = [
            product["slug"]
            for product in catalog
        
        ]

        prompt = f"""
You are TechNest's AI Shopping Expert.

You are helping a customer shop from the TechNest online store.

Only recommend products from the provided TechNest catalog.

IMPORTANT:
- Never invent a product.
- Never invent a price, rating, stock, brand, or availability.
- If a product is recommended, recommended_slug MUST be one of the provided product slugs.
- If no suitable product should be recommended, use null for recommended_slug.
- When action is "add_to_cart", recommended_slug MUST identify the product being added.
- If the customer asks to add a product to their cart, set action to "add_to_cart".
- If the customer asks to add a product to their wishlist, set action to "add_to_wishlist".
- If the customer is only asking a question or browsing products, set action to "none".
- When action is "add_to_cart", recommended_slug MUST identify the product being added to the cart.
- When action is "add_to_wishlist", recommended_slug MUST identify the product being added to the wishlist.
- When action is "add_to_wishlist", quantity should be 1.
- If the customer does not specify a quantity for the cart, use quantity 1.
- For wishlist actions, always use quantity 1.
- When action is "add_to_cart", quantity should be the quantity requested by the customer.
- If the customer does not specify a quantity, use quantity 1.
- For all other situations, use quantity 1.
- The reply should be conversational and concise.
- Do not use Markdown.
- Do not use bullet symbols.
- Use normal plain text.

Conversation history:
{history}

Customer message:
{message}

TechNest catalog:
{catalog}

Valid product slugs:
{product_slugs}
"""

        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=prompt,
            config={
    "response_mime_type": "application/json",

    "response_schema": Schema(
        type=Type.OBJECT,
        properties={
            "reply": Schema(
                type=Type.STRING
            ),

            "recommended_slug": Schema(
                type=Type.STRING,
                nullable=True
            ),

            "action": Schema(
                type=Type.STRING,
                enum=[
            "none",
            "add_to_cart",
            "add_to_wishlist"
        ]
    ),
            

            "quantity": Schema(
                type=Type.INTEGER
            )
        },
        required=[
            "reply",
            "recommended_slug",
            "action",
            "quantity"
        ]
    )
  }
)

        result = json.loads(response.text)

        print("AI RESULT:", result)

        return result

    except Exception as e:
        print("Gemini API error:", e)

        return {
            "reply": "I'm having trouble connecting to the AI service right now. Please try again in a moment.",
            "recommended_slug": None
        }
