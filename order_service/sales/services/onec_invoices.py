import requests

from datetime import datetime
from decimal import Decimal

from sales.services.onec_orders import get_onec_connection
from sales.services.onec_credentials import decrypt_password


INVOICE_ENTITY = "Document_СчетФактураВыданный"
SHIPMENT_ENTITY = "Document_РеализацияТоваровУслуг"

SHIPMENT_TYPE = "StandardODATA.Document_РеализацияТоваровУслуг"
CONTRACTOR_TYPE = "StandardODATA.Catalog_Контрагенты"
CONTRACT_TYPE = "StandardODATA.Catalog_ДоговорыКонтрагентов"


class OneCInvoiceError(Exception):
    pass


def _get_odata_session():
    connection = get_onec_connection()

    session = requests.Session()
    session.auth = (
        connection.username,
        decrypt_password(connection.encrypted_password),
    )
    session.headers.update({
        "Accept": "application/json",
    })

    return (
        session,
        connection.base_url.rstrip("/"),
        connection.timeout,
    )


def get_onec_shipment_for_invoice(shipment_ref):
    """Получить реализацию, по которой создаём счёт-фактуру."""

    session, base_url, timeout = _get_odata_session()

    url = (
        f"{base_url}/{SHIPMENT_ENTITY}"
        f"(guid'{shipment_ref}')"
    )

    response = session.get(
        url,
        params={"$format": "json"},
        timeout=timeout,
    )
    response.raise_for_status()

    shipment = response.json()

    if shipment.get("DeletionMark"):
        raise OneCInvoiceError(
            "Реализация помечена на удаление"
        )

    if not shipment.get("Posted"):
        raise OneCInvoiceError(
            "Реализация не проведена"
        )

    if not shipment.get("Number"):
        raise OneCInvoiceError(
            "У реализации отсутствует номер"
        )

    return shipment


def find_onec_invoices(shipment_ref):
    """Найти счета-фактуры по реализации."""

    from urllib.parse import quote
    from uuid import UUID

    session, base_url, timeout = _get_odata_session()

    shipment_ref = str(UUID(shipment_ref))

    filter_value = (
        "ДокументОснование eq "
        f"cast(guid'{shipment_ref}',"
        "'Document_РеализацияТоваровУслуг')"
    )

    # Кодируем только кириллицу и пробелы,
    # сохраняя синтаксис cast(guid'...', '...')
    encoded_filter = quote(
        filter_value,
        safe="()',_-",
    )

    url = (
        f"{base_url}/{INVOICE_ENTITY}"
        f"?$format=json"
        f"&$top=5"
        f"&$filter={encoded_filter}"
    )

    response = session.get(
        url,
        timeout=timeout,
    )

    print("OData URL:", response.url)
    print("OData HTTP:", response.status_code)

    if not response.ok:
        print("OData ERROR:", response.text[:2000])

    response.raise_for_status()

    data = response.json()

    if data.get("odata.nextLink") or data.get("@odata.nextLink"):
        raise OneCInvoiceError(
            "Ответ OData содержит следующую страницу. "
            "Нельзя гарантировать отсутствие дубликатов."
        )

    return [
        doc
        for doc in data.get("value", [])
        if (
            doc.get("ДокументОснование") == shipment_ref
            and doc.get("ДокументОснование_Type") == SHIPMENT_TYPE
        )
    ]

def build_invoice_payload(shipment):
    """Подготовить JSON счёта-фактуры по реализации."""

    shipment_ref = shipment["Ref_Key"]
    shipment_number = shipment["Number"].strip()

    shipment_date = shipment["Date"]
    issue_date = datetime.fromisoformat(
        shipment_date
    ).strftime("%Y-%m-%dT00:00:00")

    required_fields = [
        "Организация_Key",
        "Контрагент_Key",
        "Партнер_Key",
        "Договор_Key",
        "Валюта_Key",
        "Подразделение_Key",
        "Склад_Key",
        "НалогообложениеНДС",
    ]

    missing = [
        field for field in required_fields
        if not shipment.get(field)
    ]

    if missing:
        raise OneCInvoiceError(
            f"В реализации отсутствуют реквизиты: {missing}"
        )

    payload = {
        "Number": shipment_number,
        "Date": shipment_date,
        "Posted": False,

        "Организация_Key": shipment["Организация_Key"],

        "Контрагент": shipment["Контрагент_Key"],
        "Контрагент_Type": CONTRACTOR_TYPE,

        "Партнер_Key": shipment["Партнер_Key"],

        "Договор": shipment["Договор_Key"],
        "Договор_Type": CONTRACT_TYPE,

        "Валюта_Key": shipment["Валюта_Key"],
        "Подразделение_Key": shipment["Подразделение_Key"],
        "Склад_Key": shipment["Склад_Key"],

        "НалогообложениеНДС": (
            shipment["НалогообложениеНДС"]
        ),

        "ДокументОснование": shipment_ref,
        "ДокументОснование_Type": SHIPMENT_TYPE,

        "ДатаВыставления": issue_date,
        "КодВидаОперации": "01",

        "Исправление": False,
        "Корректировочный": False,
        "ВыставленВЭлектронномВиде": False,

        "ДокументыОснования": [
            {
                "LineNumber": "1",
                "ДокументОснование": shipment_ref,
                "ДокументОснование_Type": SHIPMENT_TYPE,
                "ХозяйственнаяОперация": (
                    shipment.get("ХозяйственнаяОперация")
                    or "РеализацияКлиенту"
                ),
            }
        ],
    }

    return payload

def create_onec_invoice(shipment_ref):
    """Создать счёт-фактуру по реализации без проведения."""

    shipment = get_onec_shipment_for_invoice(shipment_ref)

    existing = [
        doc for doc in find_onec_invoices(shipment_ref)
        if not doc.get("DeletionMark")
    ]

    if existing:
        raise OneCInvoiceError(
            "По реализации уже существует счёт-фактура: "
            + ", ".join(
                str(doc.get("Number"))
                for doc in existing
            )
        )

    payload = build_invoice_payload(shipment)

    session, base_url, timeout = _get_odata_session()

    url = f"{base_url}/{INVOICE_ENTITY}"

    response = session.post(
        url,
        params={"$format": "json"},
        json=payload,
        timeout=timeout,
    )

    print("POST HTTP:", response.status_code)

    if not response.ok:
        print("POST ERROR:", response.text[:3000])
        raise OneCInvoiceError(
            f"Ошибка создания счёта-фактуры: HTTP {response.status_code}"
        )

    result = response.json()
    invoice_ref = result.get("Ref_Key")

    if not invoice_ref:
        raise OneCInvoiceError(
            "1С не вернула Ref_Key созданного счёта-фактуры"
        )

    # Читаем сохранённый документ из 1С
    get_response = session.get(
        f"{url}(guid'{invoice_ref}')",
        params={"$format": "json"},
        timeout=timeout,
    )
    get_response.raise_for_status()

    invoice = get_response.json()

    if invoice.get("Number", "").strip() != shipment["Number"].strip():
        raise OneCInvoiceError(
            "Счёт-фактура создана, но номер не совпадает "
            f"с реализацией. Ref_Key={invoice_ref}, "
            f"номер={invoice.get('Number')}"
        )

    if invoice.get("ДокументОснование") != shipment_ref:
        raise OneCInvoiceError(
            "Счёт-фактура создана, но основание отличается. "
            f"Ref_Key={invoice_ref}"
        )

    return {
        "ref_key": invoice_ref,
        "number": invoice.get("Number"),
        "date": invoice.get("Date"),
        "posted": invoice.get("Posted"),
        "shipment_ref": invoice.get("ДокументОснование"),
        "responsible": invoice.get("Ответственный_Key"),
        "director": invoice.get("Руководитель_Key"),
        "accountant": invoice.get("ГлавныйБухгалтер_Key"),
        "author": invoice.get("Автор_Key"),
        "documents_count": len(
            invoice.get("ДокументыОснования", [])
        ),
    }


def post_onec_invoice(invoice_ref):
    """Провести существующий счёт-фактуру через OData."""

    session, base_url, timeout = _get_odata_session()

    url = (
        f"{base_url}/{INVOICE_ENTITY}"
        f"(guid'{invoice_ref}')"
    )

    def read_invoice():
        response = session.get(
            url,
            params={"$format": "json"},
            timeout=timeout,
        )
        response.raise_for_status()
        return response.json()

    invoice = read_invoice()

    if invoice.get("DeletionMark"):
        raise OneCInvoiceError(
            "Счёт-фактура помечена на удаление"
        )

    if invoice.get("Posted"):
        return {
            "ref_key": invoice_ref,
            "number": invoice.get("Number"),
            "posted": True,
            "already_posted": True,
        }

    # Проверяем реализацию-основание
    shipment_ref = invoice.get("ДокументОснование")

    if not shipment_ref:
        raise OneCInvoiceError(
            "Не указана реализация-основание"
        )

    shipment = get_onec_shipment_for_invoice(shipment_ref)

    if invoice.get("Number", "").strip() != shipment["Number"].strip():
        raise OneCInvoiceError(
            "Номер счёта-фактуры не совпадает с реализацией"
        )

    post_url = url + "/Post()"

    response = session.post(
        post_url,
        timeout=timeout,
    )

    if not response.ok:
        print("POST ERROR:", response.text[:3000])
        raise OneCInvoiceError(
            f"Ошибка проведения счёта-фактуры: HTTP {response.status_code}"
        )

    # Повторно читаем документ
    invoice = read_invoice()

    if not invoice.get("Posted"):
        raise OneCInvoiceError(
            "1С вернула успешный ответ, "
            "но счёт-фактура осталась непроведённой"
        )

    return {
        "ref_key": invoice_ref,
        "number": invoice.get("Number"),
        "posted": True,
        "already_posted": False,
        "post_http_status": response.status_code,
        "director": invoice.get("Руководитель_Key"),
        "accountant": invoice.get("ГлавныйБухгалтер_Key"),
    }