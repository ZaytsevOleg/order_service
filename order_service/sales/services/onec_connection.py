import requests

from sales.services.onec_credentials import decrypt_password


def test_onec_connection(connection):
    """Проверяет доступность OData и авторизацию в 1С."""

    url = connection.base_url.rstrip("/") + "/"

    try:
        response = requests.get(
            url,
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            timeout=connection.timeout,
        )

        response.raise_for_status()

        return True, f"Подключение успешно. HTTP {response.status_code}"

    except requests.exceptions.HTTPError as exc:
        status = exc.response.status_code

        if status == 401:
            return False, "Ошибка авторизации: проверьте логин и пароль 1С"

        if status == 403:
            return False, "Доступ запрещён: проверьте права пользователя 1С"

        return False, f"Ошибка HTTP {status}"

    except requests.exceptions.RequestException as exc:
        return False, f"Ошибка соединения: {exc}"

    except Exception as exc:
        return False, f"Ошибка настройки подключения: {exc}"