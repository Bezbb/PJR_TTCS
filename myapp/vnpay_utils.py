# vnpay_utils.py
import hashlib
import hmac
import urllib.parse
from django.conf import settings
from datetime import datetime


def _hmac_sha512(key, data):
    return hmac.new(key.encode(), data.encode(), hashlib.sha512).hexdigest()


def create_payment_url(order_code, amount, order_desc, ipaddr):
    vnp_Version = "2.1.0"
    vnp_Command = "pay"
    vnp_TmnCode = settings.VNPAY_TMN_CODE
    vnp_Url = settings.VNPAY_PAYMENT_URL
    vnp_Returnurl = settings.VNPAY_RETURN_URL

    # VNPay dùng đơn vị VND * 100
    vnp_Amount = int(amount) * 100

    vnp_TxnRef = str(order_code)  # mã đơn hàng / mã giao dịch bên bạn
    vnp_IpAddr = ipaddr
    vnp_CreateDate = datetime.now().strftime("%Y%m%d%H%M%S")
    vnp_CurrCode = "VND"
    vnp_Locale = "vn"
    vnp_OrderInfo = order_desc
    vnp_OrderType = "other"

    inputData = {
        "vnp_Version": vnp_Version,
        "vnp_Command": vnp_Command,
        "vnp_TmnCode": vnp_TmnCode,
        "vnp_Amount": str(vnp_Amount),
        "vnp_CurrCode": vnp_CurrCode,
        "vnp_TxnRef": vnp_TxnRef,
        "vnp_OrderInfo": vnp_OrderInfo,
        "vnp_OrderType": vnp_OrderType,
        "vnp_Locale": vnp_Locale,
        "vnp_ReturnUrl": vnp_Returnurl,
        "vnp_IpAddr": vnp_IpAddr,
        "vnp_CreateDate": vnp_CreateDate,
    }

    # Sắp xếp key theo alphabet
    sorted_keys = sorted(inputData.keys())
    query = ""
    hash_data = ""

    for idx, key in enumerate(sorted_keys):
        value = inputData[key]
        if idx == 0:
            query += f"{key}={urllib.parse.quote_plus(value)}"
            hash_data += f"{key}={value}"
        else:
            query += f"&{key}={urllib.parse.quote_plus(value)}"
            hash_data += f"&{key}={value}"

    # ký hash
    vnp_SecureHash = _hmac_sha512(settings.VNPAY_HASH_SECRET, hash_data)
    payment_url = f"{vnp_Url}?{query}&vnp_SecureHash={vnp_SecureHash}"
    return payment_url


def verify_vnpay_return(querydict):
    """
    querydict: request.GET
    kiểm tra chữ ký VNPay trả về
    """
    vnp_SecureHash = querydict.get("vnp_SecureHash")
    if not vnp_SecureHash:
        return False

    inputData = {}
    for key in querydict:
        if key.startswith("vnp_") and key not in ["vnp_SecureHash", "vnp_SecureHashType"]:
            inputData[key] = querydict.get(key)

    sorted_keys = sorted(inputData.keys())
    hash_data = ""
    for idx, key in enumerate(sorted_keys):
        value = inputData[key]
        if idx == 0:
            hash_data += f"{key}={value}"
        else:
            hash_data += f"&{key}={value}"

    check_hash = _hmac_sha512(settings.VNPAY_HASH_SECRET, hash_data)
    return check_hash == vnp_SecureHash
