# shop/ai_helpers.py
import re
from django.db.models import Q
from django.urls import reverse
from .models import Product   # chỉnh lại cho đúng tên model của bạn


def extract_budget_vnd(text: str):
    """
    Tìm ngân sách từ câu hỏi, ví dụ:
    - 'dưới 20 triệu'
    - 'tầm 15tr'
    - 'khoảng 25-30tr'
    Trả về (min_price, max_price) theo VNĐ hoặc (None, None) nếu không thấy.
    """
    text = text.lower().replace("triệu", "tr").replace(" ", "")
    numbers = re.findall(r"(\d+)\s*tr", text)

    if not numbers:
        return None, None

    nums = [int(n) * 1_000_000 for n in numbers]

    # kiểu "từ 15tr đến 20tr"
    if "đến" in text or "-" in text or "từ" in text:
        return min(nums), max(nums)

    # kiểu "dưới 20tr"
    if "dưới" in text or "<" in text:
        return None, nums[0]

    # kiểu "trên 20tr"
    if "trên" in text or ">" in text:
        return nums[0], None

    # kiểu "tầm 20tr"
    return None, nums[0]


def search_products_for_message(message: str, max_results: int = 5):
    """
    Tìm sản phẩm phù hợp dựa trên từ khóa & ngân sách.
    Bạn có thể custom lại filter cho đúng field của model Product.
    """
    qs = Product.objects.filter(is_active=True) if hasattr(Product, "is_active") else Product.objects.all()

    min_price, max_price = extract_budget_vnd(message)

    # GIẢ SỬ có field discounted_price, nếu khác thì sửa lại
    price_field = "discounted_price" if hasattr(Product, "discounted_price") else "price"

    if min_price is not None:
        qs = qs.filter(**{f"{price_field}__gte": min_price})
    if max_price is not None:
        qs = qs.filter(**{f"{price_field}__lte": max_price})

    # tách keyword theo khoảng trắng, bỏ mấy từ vô nghĩa
    stop_words = ["tư", "vấn", "mua", "giúp", "cho", "tôi", "mình", "em", "cần", "laptop", "máy", "tính"]
    keywords = [w for w in re.split(r"\s+", message.lower()) if w and w not in stop_words]

    if keywords:
        q = Q()
        for kw in keywords:
            q |= Q(product_name__icontains=kw) | Q(description__icontains=kw)
        qs = qs.filter(q)

    # ưu tiên giá tăng dần, hoặc bạn đổi thành -sold_count, -view_count...
    qs = qs.order_by(price_field)[:max_results]

    products_data = []
    for p in qs:
        # tự build URL detail, chỉnh name url cho trùng với của bạn
        try:
            url = reverse("product_detail", args=[p.slug])
        except Exception:
            url = "#"

        products_data.append({
            "name": p.product_name,
            "price": getattr(p, price_field, None),
            "short_desc": (p.description[:120] + "...") if getattr(p, "description", "") else "",
            "url": url,
        })

    return products_data


def build_products_context_text(products_data):
    """
    Chuyển list sản phẩm thành 1 đoạn text cho AI đọc.
    """
    if not products_data:
        return "Không tìm thấy sản phẩm nào phù hợp trong kho hàng."

    lines = ["Danh sách một số sản phẩm phù hợp trong kho hàng E-Tech Shop:"]
    for i, p in enumerate(products_data, start=1):
        price_str = f"{p['price']:,} đ" if p["price"] else "Không rõ giá"
        lines.append(
            f"{i}. {p['name']} - Giá: {price_str}. URL: {p['url']}. Mô tả ngắn: {p['short_desc']}"
        )
    return "\n".join(lines)
