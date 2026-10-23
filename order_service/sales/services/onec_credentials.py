
from cryptography.fernet import Fernet
from django.conf import settings


def get_cipher():
    key = settings.ONEC_CREDENTIALS_KEY

    if not key:
        raise RuntimeError(
            "Не задан ONEC_CREDENTIALS_KEY"
        )

    return Fernet(key.encode("ascii"))


def encrypt_password(password):
    return get_cipher().encrypt(
        password.encode("utf-8")
    ).decode("ascii")


def decrypt_password(encrypted_password):
    return get_cipher().decrypt(
        encrypted_password.encode("ascii")
    ).decode("utf-8")
