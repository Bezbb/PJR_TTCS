from datetime import timedelta
import http
import json
import random
from collections import defaultdict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.db.models import Q, F, ExpressionWrapper, DecimalField, Count
from django.http import (
    HttpResponse,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import get_object_or_404, render, redirect
from django.utils import timezone

from .models import *
from .models import CustomUser as User
from .helpers import *
import uuid
from .vnpay_utils import create_payment_url, verify_vnpay_return
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings
from openai import OpenAI
from django.conf import settings
from django.core.validators import validate_email
from django.core.exceptions import ValidationError
from django.contrib.auth.password_validation import validate_password
from django.db import transaction

client = OpenAI(api_key=settings.OPENAI_API_KEY)


def home(request):
    # Fetch all active categories
    categories = Category.objects.filter(is_active=True)

    # Fetch all active mobile brands
    active_mobile_brands = Product.objects.filter(
        category__category="Mobile Phones", is_active=True
    ).select_related("company")

    mobile_companies = set(mobile.company.company for mobile in active_mobile_brands)

    # Fetch all active laptop brands
    active_laptop_brands = Product.objects.filter(
        category__category="Laptops", is_active=True
    ).select_related("company")

    laptop_companies = set(laptop.company.company for laptop in active_laptop_brands)

    # Fetching company brands for Mobile, Tablet, and Laptops
    company_brand_mobile = Company.objects.filter(
        category__category="Mobile Phones"
    ).order_by("-id")[:6]
    company_brand_tablet = Company.objects.filter(
        category__category="Tablet"
    ).order_by("-id")[:6]
    company_brand_laptop = Company.objects.filter(
        category__category="Laptops"
    ).order_by("-id")[:6]

    # Fetching mobile phones, laptops, and trending products
    mobiles = Product.objects.filter(
        category__category="Mobile Phones", is_active=True
    ).order_by("-id")[:6]
    laptops = Product.objects.filter(
        category__category="Laptops", is_active=True
    ).order_by("-id")[:6]
    trending_products = Product.objects.filter(
        is_trending=True, is_active=True
    ).order_by("-id")[:6]
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]

    # Fetching all products globally and shuffling
    all_products = list(Product.objects.all())
    random.shuffle(all_products)
    shuffled_products = all_products[:6]

    context = {
        "company_brand_mobile": company_brand_mobile,
        "company_brand_tablet": company_brand_tablet,
        "company_brand_laptop": company_brand_laptop,
        "mobile_companies": mobile_companies,
        "laptop_companies": laptop_companies,
        "mobiles": mobiles,
        "laptops": laptops,
        "trending_products": trending_products,
        "latest_products": latest_products,
        "shuffled_products": shuffled_products,
        "categories": categories,
    }

    if request.method == "POST":
        search = request.POST.get("search")
        if search:
            search_obj = Product.objects.filter(
                Q(product_name__icontains=search)
                | Q(product_description__icontains=search)
            )
            return render(request, "search_results.html", {"search_obj": search_obj})

    return render(request, "home.html", context)


def search_results(request):
    return render(request, "search_results.html")


def calculate_delivery_date(order_date):
    days_to_add = 5  # Number of days for delivery
    current_date = order_date
    while days_to_add > 0:
        current_date += timedelta(days=1)
        if current_date.weekday() not in (5, 6):  # Skip Saturday (5) and Sunday (6)
            days_to_add -= 1
    return current_date




@login_required(login_url="login")
def buy_now(request, slug):
    """
    Mua ngay 1 sản phẩm:
    - Đảm bảo sản phẩm có trong giỏ (quantity = 1)
    - Sau đó chuyển thẳng sang trang checkout_info để nhập địa chỉ + chọn thanh toán
    """
    product = get_object_or_404(Product, slug=slug)
    user = request.user

    cart_item, created = Cart.objects.get_or_create(
        user=user,
        product=product,
        is_ordered=False,
        defaults={"quantity": 1}
    )

    if not created:
        # Mua ngay thì set về 1 sản phẩm cho rõ ràng
        cart_item.quantity = 1
        cart_item.save()

    # Tính lại tiền cho item này (nếu bạn muốn đảm bảo luôn đúng)
    calculate_cart_item_total(cart_item)

    messages.success(
        request,
        f"Bạn đang mua ngay {product.product_name}. Vui lòng điền thông tin giao hàng."
    )
    return redirect("checkout_info")


@login_required(login_url="login")
# add to cart
def checkout_cart(request, slug):
    product = get_object_or_404(
        Product, slug=slug
    )  # ✅ object, không phải chuỗi
    user = request.user

    cart_item, created = Cart.objects.get_or_create(  # ✅ dùng object
        user=user, product=product, is_ordered=False, defaults={"quantity": 1}
    )
    if not created:
        cart_item.quantity += 1
        cart_item.save()
        messages.success(request, f"Đã tăng số lượng {product.product_name} trong giỏ!")
    else:
        messages.success(request, f"Đã thêm {product.product_name} vào giỏ!")

    return HttpResponseRedirect(request.META.get("HTTP_REFERER", "/"))


def calculate_cart_item_total(cart_item):
    product = cart_item.product
    cart_item.total_price = float(product.discounted_price()) * cart_item.quantity
    cart_item.save()


@login_required(login_url="login")
def add_to_cart(request):
    context = {}
    cart_items = Cart.objects.filter(user=request.user, is_ordered=False)
    subtotal = 0
    delivery_date = calculate_delivery_date(timezone.now())

    if request.method == "POST":
        action = request.POST.get("action")
        cart_item_id = int(request.POST.get("cart_item_id"))
        cart_item = get_object_or_404(Cart, id=cart_item_id)

        if action == "increase":
            cart_item.quantity += 1
            calculate_cart_item_total(cart_item)
        elif action == "decrease":
            cart_item.quantity -= 1
            if cart_item.quantity <= 0:
                cart_item.delete()
                return redirect("add_to_cart")
            else:
                calculate_cart_item_total(cart_item)
        else:
            # If action is not increase or decrease, it means a new item is being added to the cart
            # Increase quantity by 1
            cart_item.quantity += 1
            calculate_cart_item_total(cart_item)

        # Recalculate subtotal and total
        subtotal = sum(float(item.total_price) for item in cart_items)
        total = subtotal

        return redirect("add_to_cart")

    # If not a POST request or action not specified
    for cart_item in cart_items:
        # Calculate total price for each cart item
        calculate_cart_item_total(cart_item)
        subtotal += cart_item.total_price
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    context = {
        "cart_items": cart_items,
        "subtotal": subtotal,
        "total": subtotal,
        "delivery_date": delivery_date,
        "latest_products": latest_products,
    }

    return render(request, "checkout_cart.html", context)


@login_required(login_url="login")
def get_cart_data(request):
    if request.user.is_authenticated:
        cart_items = Cart.objects.filter(user=request.user, is_ordered=False)
    else:
        cart_items = Cart.objects.none()

    subtotal = sum(
        float(cart_item.product.discounted_price()) * cart_item.quantity
        for cart_item in cart_items
    )
    total = subtotal  # For now, total is same as subtotal

    data = {
        "cart_items": list(
            cart_items.values()
        ),  # Serialize queryset to JSON-compatible format
        "subtotal": subtotal,
        "total": total,
    }
    return data


@login_required(login_url="login")
def remove_cart(request, slug):
    product = get_object_or_404(Product, slug=slug)
    user = request.user

    cart_item = Cart.objects.filter(user=user, product=product, is_ordered=False).first()

    if cart_item:
        cart_item.delete()
        messages.success(request, f"Đã xóa {product.product_name} khỏi giỏ hàng.")
    else:
        messages.error(request, "Sản phẩm không tồn tại trong giỏ hàng.")

    return redirect(request.META.get("HTTP_REFERER", "add_to_cart"))


@login_required(login_url="login")
@login_required(login_url='login')
@login_required(login_url='login')
def checkout_info(request):
    # lấy giỏ hàng hiện tại của user
    cart_items = Cart.objects.filter(user=request.user, is_ordered=False)

    if not cart_items.exists():
        messages.error(request, "Giỏ hàng của bạn đang trống, vui lòng thêm sản phẩm trước khi thanh toán.")
        return redirect('add_to_cart')

    

    if request.method == "POST":
        first_name = request.POST.get('first_name')
        last_name = request.POST.get('last_name')
        company_name = request.POST.get('company_name') or ''
        area_code = request.POST.get('area_code') or ''
        primary_phone = request.POST.get('primary_phone')
        street_address = request.POST.get('street_address')
        zip_code = request.POST.get('zip_code') or ''
        payment_method = request.POST.get('payment_method')  # 'cod' hoặc 'online'

        # lưu địa chỉ giao hàng
        shipping_obj = ShippingAddress.objects.create(
            first_name=first_name,
            last_name=last_name,
            company=company_name,
            area_code=area_code,
            primary_phone=primary_phone,
            street_address=street_address,
            zip_code=zip_code
        )
        shipping_obj.save()

        # TÍNH TỔNG GIỎ HÀNG
        total_amount = 0
        for item in cart_items:
            calculate_cart_item_total(item)
            total_amount += float(item.total_price)

        # 🔹 CASE 1: Thanh toán khi nhận hàng (COD)
        if payment_method == 'cod':
            for item in cart_items:
                OrderTracking.objects.create(
                    user=request.user,
                    product=item.product,
                    quantity=item.quantity,
                    total_price=item.total_price,
                    order_status=1,  # bạn tùy chọn: 1 = chờ giao / COD
                )
                item.mark_as_ordered_or_deleted()
                item.delete()

            messages.success(request, "Đặt hàng thành công. Bạn sẽ thanh toán khi nhận hàng.")
            return redirect('checkout_complete')

        # 🔹 CASE 2: Thanh toán online (VNPay)
        # Tạo mã đơn để gửi cho VNPay
        order_code = uuid.uuid4().hex[:10].upper()

        # Lưu vào session để checkout_payment dùng
        request.session['vnp_order_code'] = order_code
        request.session['vnp_amount'] = int(total_amount)

        return redirect('checkout_payment')

    latest_products = Product.objects.filter(is_active=True).order_by('-id')[:4]
    context = {
        'latest_products': latest_products
    }
    return render(request, 'checkout_info.html', context)


@login_required(login_url="login")
def checkout_payment(request):
    order_code = request.session.get("vnp_order_code")
    amount = request.session.get("vnp_amount")

    if not order_code or not amount:
        messages.error(request, "Không tìm thấy thông tin đơn hàng để thanh toán.")
        return redirect("add_to_cart")

    ip = request.META.get("REMOTE_ADDR", "127.0.0.1")

    payment_url = create_payment_url(
        order_code=order_code,
        amount=amount,
        order_desc=f"Thanh toán đơn hàng {order_code}",
        ipaddr=ip,
    )

    return redirect(payment_url)


@login_required(login_url="login")
def vnpay_return(request):
    """VNPay redirect về đây sau khi thanh toán"""
    vnp_data = request.GET

    # 1. Kiểm tra chữ ký VNPay
    if not verify_vnpay_return(vnp_data):
        messages.error(request, "Dữ liệu thanh toán VNPay không hợp lệ.")
        return redirect("payment_failed")

    vnp_ResponseCode = vnp_data.get("vnp_ResponseCode")  # '00' = thành công
    vnp_TxnRef = vnp_data.get("vnp_TxnRef")  # mã order_code bên mình (nếu cần)
    vnp_Amount = int(vnp_data.get("vnp_Amount", 0)) // 100  # về lại đơn vị VND

    if vnp_ResponseCode == "00":
        # ✅ Thanh toán thành công
        cart_items = Cart.objects.filter(user=request.user, is_ordered=False)

        for item in cart_items:
            calculate_cart_item_total(item)
            OrderTracking.objects.create(
                user=request.user,
                product=item.product,
                quantity=item.quantity,
                total_price=item.total_price,
                order_status=2,  # Placed
            )
            item.mark_as_ordered_or_deleted()
            item.delete()

        # Xoá thông tin VNP khỏi session
        request.session.pop("vnp_order_code", None)
        request.session.pop("vnp_amount", None)

        messages.success(
            request, "Thanh toán VNPay thành công. Cảm ơn bạn đã mua hàng!"
        )
        return redirect("checkout_complete")
    else:
        messages.error(
            request,
            f"Thanh toán VNPay thất bại. Mã lỗi: {vnp_ResponseCode}",
        )
        return redirect("payment_failed")


@login_required(login_url="login")
def checkout_complete(request):
    # Retrieve all ordered items for the current user
    ordered_items = OrderTracking.objects.filter(user=request.user).order_by("-id")
    delivery_date = calculate_delivery_date(timezone.now())
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]

    context = {
        "ordered_items": ordered_items,  # Use a plural name to indicate multiple items
        "delivery_date": delivery_date,
        "latest_products": latest_products,
    }

    return render(request, "checkout_complete.html", context)





@login_required(login_url="login")
def payment_failed(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    context = {
        "latest_products": latest_products,
    }
    return render(request, "payment-failed.html", context)





@login_required(login_url="login")
def my_account(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    order = OrderTracking.objects.filter(user=request.user).order_by("-id")
    delivery_data = calculate_delivery_date(timezone.now())
    context = {
        "order": order,
        "delivery_date": delivery_data,
        "latest_products": latest_products,
    }
    return render(request, "my_account.html", context)


def product_detail(request, slug):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    product = get_object_or_404(Product, slug=slug)

    product_description = ProductDescription.objects.filter(product=product)
    product_img = ProductDescription.objects.filter(product=product)
    information = AdditionalInformation.objects.filter(product=product)
    reviews_qs = Review.objects.filter(product=product).order_by("-id")
    review_count = reviews_qs.count()

    # Sản phẩm ngẫu nhiên
    products = Product.objects.all()
    shuffled_products = list(products)
    random.shuffle(shuffled_products)
    random_products = shuffled_products[:6]

    new_product_name = None
    if information:
        new_product_name = information[0].new_product_name

    # XỬ LÝ GỬI REVIEW
    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.error(request, "Bạn cần đăng nhập để đánh giá sản phẩm.")
            return redirect("login")

        # 1. Kiểm tra đã mua sản phẩm chưa
        user_purchased = OrderTracking.objects.filter(
            user=request.user, product=product
        ).exists()
        if not user_purchased:
            messages.error(request, "Chỉ những khách đã mua hàng mới được đánh giá sản phẩm.")
            return redirect("product_detail", slug=slug)

        # 2. Kiểm tra đã đánh giá trước đó chưa
        already_reviewed = Review.objects.filter(
            user=request.user, product=product
        ).exists()
        if already_reviewed:
            messages.error(request, "Bạn đã đánh giá sản phẩm này rồi.")
            return redirect("product_detail", slug=slug)

        # 3. Tạo review mới
        name = request.POST.get("name")
        email = request.POST.get("email")
        message_text = request.POST.get("message")
        rating = int(request.POST.get("rating"))

        rating_obj = Review.objects.create(
            product=product,
            user=request.user,
            name=name,
            title=email,
            review=message_text,
            rating=rating,
        )
        rating_obj.save()

        messages.success(request, "Đánh giá của bạn đã được gửi thành công.")
        return redirect("product_detail", slug=slug)

    # PHÂN TRANG REVIEW
    paginated = Paginator(reviews_qs, 5)
    page_number = request.GET.get("page")
    try:
        reviews_page = paginated.page(page_number)
    except PageNotAnInteger:
        reviews_page = paginated.page(1)
    except EmptyPage:
        reviews_page = paginated.page(paginated.num_pages)

    user_reviews = None
    if request.user.is_authenticated:
        user_reviews = Review.objects.filter(user=request.user, product=product)

    context = {
        "product": product,
        "product_description": product_description,
        "product_img": product_img,
        "information": information,
        "new_product_name": new_product_name,
        "review_count": review_count,
        "reviews": reviews_page,           # ← chỉ để 1 key reviews
        "user_reviews": user_reviews,
        "random_products": random_products,
        "latest_products": latest_products,
    }

    return render(request, "product_detail.html", context)



def product(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    total_products = Product.objects.all().count()
    all_products = Product.objects.all().order_by("-id")

    category_count = {}

    for item in all_products:
        category = item.category.category
        if category not in category_count:
            category_count[item.company.company] = 1
        else:
            category_count[item.company.company] += 1

    # Calculate counts of products for each company
    company_counts = {}
    for product in all_products:
        company_name = product.company.company
        if company_name not in company_counts:
            company_counts[company_name] = 1
        else:
            company_counts[company_name] += 1

    paginator = Paginator(all_products, 6)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    if request.method == "POST":
        price_from = request.POST.get("price_from")
        price_to = request.POST.get("price_to")
        search = request.POST.get("search")
        company_name = request.POST.get("company_name")

        # Filter products based on company
        if company_name:
            all_products = all_products.filter(
                company__company=company_name
            )  # filter company name from the product model
            paginator = Paginator(all_products, 9)  # applying pagination to the filtered products
            paginated_products = paginator.page(1)  # Reset page to 1 after filtering

        # Check if price_from and price_to are provided and convert them to integers
        if price_from and price_to:
            # Filter products based on price range
            all_products = all_products.annotate(
                discounted_price=F("orignal_price")
                - F("orignal_price") * F("discount_percentage") / 100
            ).filter(
                # Filter products where discounted price is within the specified range
                discounted_price__gte=price_from,
                discounted_price__lte=price_to,
            )

        # Filter products based on search query
        if search:
            all_products = all_products.filter(
                Q(product_name__icontains=search)
                | Q(product_description__icontains=search)
            )

        # Re-paginate the queryset after applying filters
        paginator = Paginator(all_products, 6)
        paginated_products = paginator.page(1)  # Reset page to 1 after filtering

    context = {
        "product_names": paginated_products,
        "total_products": total_products,
        "mobile_companies": category_count,
        "show_top_companies": True,
        "company_counts": company_counts,
        "latest_products": latest_products,
    }

    return render(request, "product.html", context)





@login_required(login_url="login")
def laptops(request):
    category_name = "Laptops"  # Category name for laptops

    category_products = Product.objects.filter(
        category__category=category_name, is_active=True
    ).order_by("-id")
    paginator = Paginator(category_products, 9)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    total_products = category_products.count()

    context = {
        "product_names": paginated_products,
        "category_name": category_name,
        "total_products": total_products,
        "show_top_companies": False,
    }

    return render(request, "product.html", context)


@login_required(login_url="login")
def tablets(request):
    category_name = "Tablet"
    category_products = Product.objects.filter(
        category__category=category_name, is_active=True
    ).order_by("-id")
    paginator = Paginator(category_products, 9)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    total_products = category_products.count()

    context = {
        "product_names": paginated_products,
        "category_name": category_name,
        "total_products": total_products,
        "show_top_companies": False,
    }

    return render(request, "product.html", context)


@login_required(login_url="login")
def mobile_phones(request):
    category_name = "Mobile Phones"
    category_products = Product.objects.filter(
        category__category=category_name, is_active=True
    ).order_by("-id")
    paginator = Paginator(category_products, 6)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    total_products = category_products.count()

    context = {
        "product_names": paginated_products,
        "category_name": category_name,
        "total_products": total_products,
        "show_top_companies": False,
    }

    return render(request, "product.html", context)


@login_required(login_url="login")
def product_by_company_laptops(request, company_name):
    # Filter products based on the company name
    company_products = Product.objects.filter(
        company__company=company_name, category__category="Laptop", is_active=True
    )
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    total_products = company_products.count()

    paginator = Paginator(company_products, 9)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    context = {
        "product_names": paginated_products,
        "company_name": company_name,
        "total_products": total_products,
        "latest_products": latest_products,
    }

    return render(request, "product.html", context)


@login_required(login_url="login")
def product_by_company(request, company_name):
    # Filter products based on the company name
    company_products = Product.objects.filter(
        company__company=company_name
    ).order_by("-id")
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    total_products = company_products.count()

    paginator = Paginator(company_products, 9)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    context = {
        "product_names": paginated_products,
        "company_name": company_name,
        "total_products": total_products,
        "latest_products": latest_products,
    }

    return render(request, "product.html", context)


def product_by_category(request, category_id):
    category = get_object_or_404(Category, id=category_id)
    products = Product.objects.filter(category=category, is_active=True)
    product_count_filter = products.count()
    paginator = Paginator(products, 9)

    page_number = request.GET.get("page")
    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)
    context = {
        "category": category,
        "paginated_products": paginated_products,
        "product_count_filter": product_count_filter,
    }
    return render(request, "product_by_category.html", context)


@login_required(login_url="login")
def product_by_company_tablets(request, company_name=None):
    # Filter products based on the company name
    tablets_products = Product.objects.filter(company__company=company_name)

    paginator = Paginator(tablets_products, 9)
    page_number = request.GET.get("page")

    try:
        paginated_products = paginator.page(page_number)
    except PageNotAnInteger:
        paginated_products = paginator.page(1)
    except EmptyPage:
        paginated_products = paginator.page(paginator.num_pages)

    context = {
        "product_names": paginated_products,
        "company_name": company_name,
    }

    return render(request, "product.html", context)


@login_required(login_url="login")
def order_tracking(request):
    delivery_date = calculate_delivery_date(timezone.now())
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    if request.method == "POST":
        order_id = request.POST.get("order_id")

        cart_items = OrderTracking.objects.filter(
            user=request.user, order_id=order_id
        )

        if not cart_items.exists():
            messages.error(request, "Order ID does not exist")
            return redirect("order_tracking")

        context = {
            "cart_items": cart_items,
            "delivery_date": delivery_date,
            "latest_products": latest_products,
        }
        return render(request, "order-status.html", context)

    return render(request, "order_tracking.html")


def login_page(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    if request.method == "POST":
        email = request.POST.get("email")
        password = request.POST.get("password")

        if not User.objects.filter(email=email).exists():
            messages.info(request, "Please create an account first.")
            return redirect("login")

        user = authenticate(email=email, password=password)

        if user is not None:
            login(request, user)
            return redirect("/")
        else:
            messages.info(request, "invalid Email and Password")
            return redirect("login")

    context = {
        "latest_products": latest_products,
    }
    return render(request, "login.html", context)


def register(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]

    if request.method == "POST":
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        email = request.POST.get("email", "").strip().lower()
        password = request.POST.get("password", "")
        repassword = request.POST.get("repassword", "")

        # 1️⃣ Validate input rỗng
        if not all([first_name, last_name, email, password, repassword]):
            messages.error(request, "Vui lòng điền đầy đủ thông tin.")
            return redirect("register")

        # 2️⃣ Validate email
        try:
            validate_email(email)
        except ValidationError:
            messages.error(request, "Email không hợp lệ.")
            return redirect("register")

        # 3️⃣ Check email đã đăng ký chưa
        if User.objects.filter(email=email).exists():
            messages.error(request, "Email này đã được đăng ký.")
            return redirect("register")

        # 4️⃣ Check password nhập lại
        if password != repassword:
            messages.error(request, "Mật khẩu nhập lại không khớp.")
            return redirect("register")

        # 5️⃣ Validate độ mạnh mật khẩu (Django chuẩn)
        try:
            validate_password(password)
        except ValidationError as e:
            messages.error(request, " ".join(e.messages))
            return redirect("register")

        # 6️⃣ Tạo user (atomic)
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    first_name=first_name,
                    last_name=last_name,
                    password=password,
                )
        except Exception:
            messages.error(request, "Có lỗi xảy ra khi tạo tài khoản.")
            return redirect("register")

        # 7️⃣ Auto login
        login(request, user)
        messages.success(request, "Đăng ký tài khoản thành công!")
        return redirect("/")

    return render(request, "register.html", {
        "latest_products": latest_products,
    })


def forget_password(request):
    latest_products = Product.objects.filter(is_active=True).order_by("-id")[:4]
    try:
        if request.method == "POST":
            email = request.POST.get("email")

            if not User.objects.filter(email=email).exists():
                messages.info(request, "Email does not exists")
                return redirect("forget_password")

            user_obj = User.objects.get(email=email)
            token = str(uuid.uuid4())

            profile_obj, created = Profile.objects.get_or_create(user=user_obj)
            profile_obj.forget_token = token
            profile_obj.save()
            send_email(user_obj.email, token)
            messages.success(request, "Vui lòng kiểm tra email của bạn.")
            return redirect("forget_password")

    except Exception as e:
        print(e)
    context = {
        "latest_products": latest_products,
    }
    return render(request, "forget_password.html", context)


def change_password(request, token):
    # Retrieve the Profile object associated with the provided token
    profile_obj = Profile.objects.filter(forget_token=token).first()

    # Check if the request method is POST
    if request.method == "POST":
        # Retrieve the password and confirm_password from the POST data
        password = request.POST.get("password")
        confirm_password = request.POST.get("confirm_password")

        # Check if the password matches the confirm_password
        if password != confirm_password:
            # If passwords don't match, display a message and redirect back to the change password page
            messages.info(request, "Password does not match")
            return redirect(f"change_password{token}")
        else:
            # Retrieve the User object associated with the profile's email
            user_obj = User.objects.get(email=profile_obj.user.email)

            # Set the new password for the user
            user_obj.set_password(password)

            # Save the user object with the new password
            user_obj.save()

            # Display a success message and redirect to the login page
            messages.info(request, "Password has been changed successfully")
            return redirect("login")
    return render(request, "change_password.html")


def reset_password(request):
    if request.method == "POST":
        old_password = request.method.POST("old_passowrd")
        new_password1 = request.method.POST("new_password1")
        new_password2 = request.method.POST("new_password2")

    return render(request, "reset-password.html")


@login_required(login_url="login")
def order_progress(request, pid):
    order = OrderTracking.objects.get(id=pid)
    orderstatus = status
    return render(request, "order-progress.html", locals())


@login_required(login_url="login")
def order_history(request):
    order = OrderTracking.objects.filter(user=request.user).order_by("-id")

    return render(request, "order-history.html", locals())


def cancel_order(request, pid):
    order = OrderTracking.objects.get(id=pid)
    order.delete()
    messages.info(request, "Order has been cancelled")
    return redirect("order-history")


def return_order(request, pid):
    order = OrderTracking.objects.get(id=pid)
    order.delete()
    messages.info(request, "Order has been returned")
    return redirect("order-history")


def logout_page(request):
    logout(request)
    return redirect("home")




import json
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from openai import OpenAI

client = OpenAI(api_key=settings.OPENAI_API_KEY)




# ======================== HỖ TRỢ CHATBOX AI TƯ VẤN MUA HÀNG ========================
import json
import re
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.urls import reverse
from django.db.models import ExpressionWrapper, F, DecimalField, Q
from openai import OpenAI
from django.conf import settings

from .models import Product

client = OpenAI(api_key=settings.OPENAI_API_KEY)


# ======================== EXTRACT BUDGET ========================

def extract_budget_vnd(text: str):
    text_norm = (
        text.lower()
        .replace("triệu", "tr")
        .replace("vnđ", "")
        .replace("vnd", "")
        .replace(" ", "")
    )

    numbers = re.findall(r"(\d+)tr", text_norm)
    if not numbers:
        return None, None

    nums = [int(n) * 1_000_000 for n in numbers]

    if any(k in text_norm for k in ["đến", "-", "từ"]):
        return min(nums), max(nums)

    if any(k in text_norm for k in ["dưới", "<"]):
        return None, nums[0]

    if any(k in text_norm for k in ["trên", ">"]):
        return nums[0], None

    return None, nums[0]


# ======================== EXTRACT CATEGORY ========================

def extract_category_from_message(text: str):
    t = text.lower()

    if any(k in t for k in ["laptop", "máy tính xách tay"]):
        return "Laptops"
    if any(k in t for k in ["điện thoại", "phone", "smartphone", "mobile"]):
        return "Mobile Phones"
    if any(k in t for k in ["tablet", "ipad"]):
        return "Tablet"

    return None


# ======================== SEARCH PRODUCTS ========================

def search_products_for_message(message: str, max_results: int = 3):
    qs = Product.objects.filter(is_active=True, is_stock=True).annotate(
        discounted_price=ExpressionWrapper(
            F("orignal_price") - F("orignal_price") * F("discount_percentage") / 100,
            output_field=DecimalField(max_digits=20, decimal_places=2),
        )
    )

    # 1️⃣ CATEGORY
    category = extract_category_from_message(message)
    if category:
        qs = qs.filter(category__category__icontains=category)

    # 2️⃣ PRICE
    min_price, max_price = extract_budget_vnd(message)
    if min_price:
        qs = qs.filter(discounted_price__gte=min_price)
    if max_price:
        qs = qs.filter(discounted_price__lte=max_price)

    # 3️⃣ KEYWORDS
    stop_words = {
        "tư","vấn","mua","giúp","cho","mình","em","cần",
        "con","nào","loại","máy","tính","laptop","điện","thoại",
        "phone","tablet","ipad","dưới","trên","khoảng","tầm",
        "triệu","vnd","vnđ"
    }

    words = re.findall(r"\w+", message.lower())
    keywords = [w for w in words if w not in stop_words and len(w) > 1]

    if keywords:
        q = Q()
        for kw in keywords:
            q |= (
                Q(product_name__icontains=kw)
                | Q(product_description__icontains=kw)
                | Q(company__company__icontains=kw)
                | Q(category__category__icontains=kw)
                | Q(additional_informations__feature__icontains=kw)
                | Q(additional_informations__new_product_description__icontains=kw)
            )
        qs = qs.filter(q).distinct()

    qs = qs.order_by("-is_trending", "discounted_price", "-created_at")[:max_results]

    # 4️⃣ FORMAT OUTPUT
    results = []
    for p in qs:
        results.append({
            "name": p.product_name,
            "price": float(p.discounted_price),
            "short_desc": (p.product_description or "")[:120] + "...",
            "url": reverse("product_detail", args=[p.slug]),
            "category": p.category.category,
            "brand": p.company.company,
            "image": p.product_image.url if p.product_image else "",
        })

    return results


# ======================== AI CHAT ========================

@csrf_exempt
def ai_chat(request):
    if request.method != "POST":
        return JsonResponse({"error": "Only POST allowed"}, status=405)

    try:
        data = json.loads(request.body)
        user_message = data.get("message", "").strip()

        if not user_message:
            return JsonResponse({"error": "Message is empty"}, status=400)

        products = search_products_for_message(user_message)

        product_context = "\n".join(
            f"{i+1}. {p['name']} | {p['brand']} | {p['price']:,.0f} đ | {p['short_desc']}"
            for i, p in enumerate(products)
        ) or "Không có sản phẩm phù hợp."

        response = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Bạn là trợ lý bán hàng của E-Tech Shop.\n"
                        "Luôn trả lời tiếng Việt, thân thiện.\n"
                        "Không đưa link, không liệt kê cấu hình chi tiết.\n"
                        "Tối đa 3 sản phẩm, tổng dưới 5 câu."
                    )
                },
                {
                    "role": "system",
                    "content": f"DANH SÁCH SẢN PHẨM:\n{product_context}"
                },
                {
                    "role": "user",
                    "content": user_message
                }
            ]
        )

        return JsonResponse({
            "reply": response.choices[0].message.content.strip(),
            "products": products
        })

    except Exception as e:
        print("AI_CHAT_ERROR:", e)
        return JsonResponse({"error": "AI system error"}, status=500)
