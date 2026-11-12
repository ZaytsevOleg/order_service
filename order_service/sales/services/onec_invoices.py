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
    """Найти счета-фактуры по ссылке на реализацию."""

    session, base_url, timeout = _get_odata_session()

    filter_value = (
        "ДокументОснование eq "
        f"cast(guid'{shipment_ref}',"
        "'Document_РеализацияТоваровУслуг')"
    )

    response = session.get(
        f"{base_url}/{INVOICE_ENTITY}",
        params={
            "$format": "json",
            "$filter": filter_value,
        },
        timeout=timeout,
    )
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

