import smtplib
import requests

from email.message import EmailMessage
from django.conf import settings

class NotificationError(Exception):
    pass


def send_email(to_email: str, subject: str, text: str):
    if not to_email:
        raise NotificationError("Не указан Email получателя")

    if not settings.NOTIFY_EMAIL_HOST:
        raise NotificationError("SMTP не настроен")

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.NOTIFY_EMAIL_USER
    message["To"] = to_email
    message.set_content(text)

    try:
        with smtplib.SMTP(
            settings.NOTIFY_EMAIL_HOST,
            settings.NOTIFY_EMAIL_PORT,
            timeout=15,
        ) as smtp:
            if settings.NOTIFY_EMAIL_USE_TLS:
                smtp.starttls()

            smtp.login(
                settings.NOTIFY_EMAIL_USER,
                settings.NOTIFY_EMAIL_PASSWORD,
            )

            smtp.send_message(message)

    except Exception as exc:
        raise NotificationError(
            f"Ошибка отправки Email: {exc}"
        ) from exc