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


def send_bitrix_message(user_id: str, text: str):
    if not user_id:
        raise NotificationError("Не указан Bitrix ID получателя")

    if not settings.NOTIFY_BITRIX_WEBHOOK:
        raise NotificationError("Webhook Bitrix24 не настроен")

    try:
        response = requests.post(
            settings.NOTIFY_BITRIX_WEBHOOK,
            json={
                "DIALOG_ID": str(user_id),
                "MESSAGE": text,
            },
            timeout=15,
        )

        response.raise_for_status()
        data = response.json()

        if not isinstance(data, dict):
            raise NotificationError(
                "Некорректный ответ Bitrix24"
            )

        if data.get("error"):
            raise NotificationError(
                f"Ошибка Bitrix24: {data.get('error_description') or data['error']}"
            )

        if not data.get("result"):
            raise NotificationError(
                f"Bitrix24 не подтвердил отправку: {data}"
            )

        return data["result"]

    except requests.RequestException as exc:
        raise NotificationError(
            f"Ошибка подключения к Bitrix24: {exc}"
        ) from exc