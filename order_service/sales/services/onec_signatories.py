from datetime import date, datetime
from urllib.parse import urlencode, quote

import requests

from sales.services.onec_credentials import decrypt_password


class OneCSignatoriesError(Exception):
    pass


def _parse_date(value):
    if not value or value.startswith("0001-01-01"):
        return None
    return date.fromisoformat(value[:10])


def get_onec_signatories(connection, organization_guid, document_date):
    if isinstance(document_date, datetime):
        target_date = document_date.date()
    elif isinstance(document_date, date):
        target_date = document_date
    else:
        target_date = date.fromisoformat(str(document_date)[:10])

    params = {
        "$format": "json",
        "$filter": (
            f"Owner_Key eq guid'{organization_guid}' "
            "and DeletionMark eq false"
        ),
        "$select": (
            "Ref_Key,Owner_Key,ОтветственноеЛицо,"
            "ДатаНачала,ДатаОкончания,DeletionMark"
        ),
        "$top": 100,
    }

    url = (
        connection.base_url.rstrip("/")
        + "/Catalog_ОтветственныеЛицаОрганизаций?"
        + urlencode(params, quote_via=quote)
    )

    try:
        response = requests.get(
            url,
            auth=(
                connection.username,
                decrypt_password(connection.encrypted_password),
            ),
            headers={"Accept": "application/json"},
            timeout=connection.timeout,
        )
        response.raise_for_status()
        records = response.json().get("value", [])
    except (requests.RequestException, ValueError, TypeError) as exc:
        raise OneCSignatoriesError(
            f"Не удалось получить ответственных лиц организации: {exc}"
        ) from exc

    if len(records) >= 100:
        raise OneCSignatoriesError(
            "Получено 100 записей ответственных лиц. "
            "Необходимо проверить полноту результата."
        )

    roles = {
        "Руководитель": "Руководитель_Key",
        "ГлавныйБухгалтер": "ГлавныйБухгалтер_Key",
    }

    result = {}

    for role, field_name in roles.items():
        matches = []

        for record in records:
            if record.get("ОтветственноеЛицо") != role:
                continue

            if record.get("Owner_Key", "").lower() != organization_guid.lower():
                continue

            if record.get("DeletionMark") is not False:
                continue

            start = _parse_date(record.get("ДатаНачала"))
            end = _parse_date(record.get("ДатаОкончания"))

            if start and start > target_date:
                continue
            if end and end < target_date:
                continue

            matches.append(record["Ref_Key"])

        if len(matches) != 1:
            raise OneCSignatoriesError(
                f"Для роли '{role}' на {target_date} "
                f"найдено действующих записей: {len(matches)} "
                f"(ожидается ровно одна)"
            )

        result[field_name] = matches[0]

    return result