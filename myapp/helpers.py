from django.contrib.auth.base_user import BaseUserManager
from django.conf import settings
from django.core.mail import send_mail


class Manager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('The Email is required')
        first_name = extra_fields.get('first_name')
        last_name = extra_fields.get('last_name')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, password=None, **extra_fields):
        
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff = True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser = True')
        
        return self.create_user(email, password, **extra_fields)


def send_email(email, token):
    subject = "Khôi phục mật khẩu của bạn"

    reset_link = f"http://127.0.0.1:8000/change_password/{token}"

    message = f"""
Xin chào,

Bạn đã yêu cầu đặt lại mật khẩu cho tài khoản của mình.

Vui lòng nhấp vào liên kết bên dưới để đổi mật khẩu:

{reset_link}

Lưu ý:
- Liên kết chỉ có hiệu lực trong một khoảng thời gian giới hạn.
- Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng bỏ qua email này.
- Không chia sẻ đường link này cho bất kỳ ai.

Trân trọng,
Hệ thống hỗ trợ khách hàng
"""

    email_from = settings.EMAIL_HOST_USER
    recipient_list = [email]

    send_mail(
        subject,
        message,
        email_from,
        recipient_list,
        fail_silently=False,
    )

    return True
