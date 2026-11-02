import requests

from sales.models import OneCConnection
from sales.services.onec_credentials import decrypt_password
from sales.services.order_1c_payload import build_order_payload
from sales.services.onec_signatories import (
    get_onec_signatories,
    OneCSignatoriesError,
)




class OneCOrderError(Exception):
    pass


def get_onec_connection():
    connection = OneCConnection.objects.filter(is_active=True).first()

    if connection is None:
        raise OneCOrderError("Не настроено активное подключение к 1С")

    return connection


def create_onec_order(order):
    """
    Создаёт непроведённый ЗаказКлиента в 1С.

    ВНИМАНИЕ: функция выполняет реальный POST.
    Пока не вызываем её из пользовательского интерфейса.
    """
    if order.one_c_order_id:
        raise OneCOrderError("Заказ уже связан с документом 1С")

    connection = get_onec_connection()
    payload = build_order_payload(order)

    # Получаем действующих подписантов организации из 1С.
    try:
        signatories = get_onec_signatories(
            connection=connection,
            organization_guid=payload["Организация_Key"],
            document_date=payload["Date"],
        )
    except OneCSignatoriesError as exc:
        raise OneCOrderError(
            f"Не удалось определить подписантов заказа: {exc}"
        ) from exc

    payload.update(signatories)

    url = (
        connection.base_url.rstrip("/")
        + "/Document_ЗаказКлиента"
    )

    try:
        response = requests.post(
            url,
            json=payload,
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
            },
            timeout=connection.timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise OneCOrderError(
            "Не удалось получить подтверждение создания заказа в 1С. "
            "Перед повторной отправкой необходимо проверить, "
            "не был ли документ создан."
        ) from exc

    if not response.ok:
        raise OneCOrderError(
            f"Ошибка 1С HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    try:
        data = response.json()

        returned_external_id = data.get("НомерПоДаннымКлиента")

        if returned_external_id != str(order.id):
            raise OneCOrderError(
                "1С вернула документ с неожиданным "
                "номером по данным клиента. "
                "Проверьте результат отправки вручную."
            )

        ref_key = data["Ref_Key"]
    except (ValueError, KeyError, TypeError) as exc:
        raise OneCOrderError(
            "1С ответила успешно, но не вернула корректный Ref_Key. "
            "Перед повторной отправкой проверьте документ в 1С."
        ) from exc

    return {
        "ref_key": ref_key,
        "number": data.get("Number"),
        "date": data.get("Date"),
        "posted": data.get("Posted"),
    }


from urllib.parse import urlencode


def find_onec_order(order, connection=None):
    """
    Поиск документа 1С по UUID заказа Django.
    Только чтение, без изменения данных.
    """
    connection = connection or get_onec_connection()

    order_id = str(order.id)
    escaped_id = order_id.replace("'", "''")

    params = {
        "$format": "json",
        "$filter": f"НомерПоДаннымКлиента eq '{escaped_id}'",
        "$select": (
            "Ref_Key,Number,Date,"
            "НомерПоДаннымКлиента,Posted"
        ),
        "$top": 2,
    }

    query_string = urlencode(params, quote_via=__import__(
        "urllib.parse", fromlist=["quote"]
    ).quote)

    url = (
        connection.base_url.rstrip("/")
        + "/Document_ЗаказКлиента?"
        + query_string
    )

    response = requests.get(
        url,
        auth=(
            connection.username,
            decrypt_password(connection.encrypted_password),
        ),
        headers={"Accept": "application/json"},
        timeout=connection.timeout,
    )

    if not response.ok:
        raise OneCOrderError(
            f"Ошибка поиска заказа в 1С "
            f"(HTTP {response.status_code}): "
            f"{response.text[:1000]}"
        )

    documents = response.json().get("value", [])

    if len(documents) > 1:
        raise OneCOrderError(
            f"В 1С найдено несколько заказов с UUID {order_id}"
        )

    return documents[0] if documents else None


def post_onec_order(ref_key):
    """
    Проводит существующий заказ клиента в 1С.
    Перед проведением проверяет его состояние.
    После проведения повторно читает документ.
    """
    from decimal import Decimal
    from uuid import UUID

    try:
        ref_key = str(UUID(str(ref_key)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise OneCOrderError("Некорректный Ref_Key заказа 1С") from exc

    connection = get_onec_connection()

    auth = (
        connection.username,
        decrypt_password(connection.encrypted_password),
    )

    url = (
        connection.base_url.rstrip("/")
        + f"/Document_ЗаказКлиента(guid'{ref_key}')"
    )

    def get_document():
        try:
            response = requests.get(
                url,
                params={"$format": "json"},
                auth=auth,
                headers={"Accept": "application/json"},
                timeout=connection.timeout,
            )
            response.raise_for_status()
            return response.json()
        except (requests.exceptions.RequestException, ValueError) as exc:
            raise OneCOrderError(
                f"Не удалось получить заказ 1С {ref_key}: {exc}"
            ) from exc

    document = get_document()

    if document.get("Posted") is True:
        return {
            "ref_key": ref_key,
            "number": document.get("Number"),
            "posted": True,
            "already_posted": True,
        }

    if document.get("СкидкиРассчитаны") is not True:
        raise OneCOrderError(
            "Нельзя провести заказ: СкидкиРассчитаны = False"
        )

    original_amount = Decimal(str(document["СуммаДокумента"]))

    try:
        response = requests.post(
            url + "/Post",
            params={"$format": "json"},
            json={"PostingMode": "NonOperational"},
            auth=auth,
            headers={"Accept": "application/json"},
            timeout=connection.timeout,
        )
    except requests.exceptions.RequestException as exc:
        raise OneCOrderError(
            "Не удалось получить подтверждение проведения заказа. "
            "Необходимо проверить состояние документа в 1С."
        ) from exc

    # Даже после HTTP 500 проверяем фактическое состояние документа.
    result = get_document()

    if result.get("Posted") is not True:
        raise OneCOrderError(
            f"Заказ не проведён. HTTP {response.status_code}: "
            f"{response.text[:1000]}"
        )

    if Decimal(str(result["СуммаДокумента"])) != original_amount:
        raise OneCOrderError(
            "Заказ проведён, но сумма документа изменилась! "
            "Требуется проверка в 1С."
        )

    return {
        "ref_key": ref_key,
        "number": result.get("Number"),
        "date": result.get("Date"),
        "posted": True,
        "agreed": result.get("Согласован"),
        "amount": str(result["СуммаДокумента"]),
        "already_posted": False,
    }