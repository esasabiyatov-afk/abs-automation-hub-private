from __future__ import annotations

import argparse
import getpass
import json
import os
import sys
from pathlib import Path
from typing import Any

# Portable/isolated Python builds may ignore PYTHONPATH.  Resolve the bundled
# package relative to this launcher before importing it.
SCRIPT_DIR = Path(__file__).resolve().parent
SOURCE_DIR = SCRIPT_DIR / "src"
if SOURCE_DIR.is_dir() and str(SOURCE_DIR) not in sys.path:
    sys.path.insert(0, str(SOURCE_DIR))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from automation_hub.tolubay import TolubayClient, TolubayConfig


DEFAULT_FIELDS_CONFIG: dict[str, dict[str, bool]] = {
    "customer": {
        "abs_id": True,
        "full_name": True,
        "passport": True,
        "inn": True,
        "residence_address": True,
        "registration_address": True,
        "birth_date": True,
        "phones": True,
        "account_count": True,
        "accounts": True,
    },
    "passport": {
        "document_type": True,
        "series": True,
        "number": True,
        "issued_by": True,
        "issue_date": True,
        "valid_until": True,
    },
    "legal": {
        "abs_id": True,
        "company_name": True,
        "legal_form": True,
        "inn": True,
        "okpo": True,
        "registration_number": True,
        "registration_date": True,
        "registration_authority": True,
        "legal_address": True,
        "actual_address": True,
        "phones": True,
        "account_count": True,
        "accounts": True,
    },
    "account": {
        "status": True,
        "currency": True,
        "name": True,
        "number": True,
        "open_date": True,
        "close_date": True,
    },
}

CUSTOMER_LABELS = {
    "abs_id": "ID_в_ABS",
    "full_name": "ФИО",
    "passport": "паспорт",
    "inn": "ИНН",
    "residence_address": "адрес_проживания",
    "registration_address": "адрес_прописки",
    "birth_date": "дата_рождения",
    "phones": "телефоны",
    "account_count": "количество_счетов",
    "accounts": "счета",
}

PASSPORT_LABELS = {
    "document_type": "тип_документа",
    "series": "серия",
    "number": "номер",
    "issued_by": "кем_выдан",
    "issue_date": "дата_выдачи",
    "valid_until": "действителен_до",
}

LEGAL_LABELS = {
    "abs_id": "ID_в_ABS",
    "company_name": "наименование_организации",
    "legal_form": "организационно_правовая_форма",
    "inn": "ИНН",
    "okpo": "ОКПО",
    "registration_number": "регистрационный_номер",
    "registration_date": "дата_регистрации",
    "registration_authority": "орган_регистрации",
    "legal_address": "юридический_адрес",
    "actual_address": "фактический_адрес",
    "phones": "телефоны",
    "account_count": "количество_счетов",
    "accounts": "счета",
}

ACCOUNT_LABELS = {
    "status": "статус",
    "currency": "валюта",
    "name": "наименование_счета",
    "number": "номер_счета",
    "open_date": "дата_открытия",
    "close_date": "дата_закрытия",
}

CURRENCY_CODES = {
    "417": "KGS",
    "643": "RUB",
    "840": "USD",
    "978": "EUR",
}


def load_fields_config(path: Path | None) -> dict[str, dict[str, bool]]:
    """Load optional field switches while keeping defaults for missing keys."""
    config = {section: values.copy() for section, values in DEFAULT_FIELDS_CONFIG.items()}
    if path is None or not path.is_file():
        return config
    loaded = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(loaded, dict):
        raise ValueError("Файл настроек полей должен содержать JSON-объект")
    for section, defaults in config.items():
        overrides = loaded.get(section, {})
        if not isinstance(overrides, dict):
            raise ValueError(f"Раздел {section!r} в настройках должен быть JSON-объектом")
        for key, enabled in overrides.items():
            if key not in defaults:
                raise ValueError(f"Неизвестное поле в настройках: {section}.{key}")
            if not isinstance(enabled, bool):
                raise ValueError(f"Поле {section}.{key} должно быть true или false")
            defaults[key] = enabled
    return config


def _text(value: Any, *, prefer_label: bool = False) -> str:
    if value is None:
        return ""
    if isinstance(value, dict):
        preferred = ("text", "value") if prefer_label else ("value", "text")
        for key in preferred:
            candidate = value.get(key)
            if candidate not in (None, ""):
                return str(candidate).strip()
        return ""
    return str(value).strip()


def _address(fields: dict[str, Any], prefix: str) -> str:
    country = _text(fields.get(f"{prefix}CountryId"), prefer_label=True)
    city = _text(fields.get(f"{prefix}CityName")) or _text(
        fields.get(f"{prefix}CityId"), prefer_label=True
    )
    street = _text(fields.get(f"{prefix}Street"))
    house = _text(fields.get(f"{prefix}House"))
    housing = _text(fields.get(f"{prefix}Housing"))
    building = _text(fields.get(f"{prefix}Building"))
    flat = _text(fields.get(f"{prefix}Flat"))
    components = [
        country,
        city,
        _text(fields.get(f"{prefix}PostalCode")),
        f"ул. {street}" if street else "",
        f"д. {house}" if house else "",
        f"корп. {housing}" if housing else "",
        f"стр. {building}" if building else "",
        f"кв. {flat}" if flat else "",
    ]
    return ", ".join(item for item in components if item)


def _phones(fields: dict[str, Any], summary_phones: str) -> list[str]:
    candidates = [
        fields.get("AdditionalInfoModel.ContactPhone1"),
        fields.get("AdditionalInfoModel.ContactPhone2"),
        fields.get("AdditionalInfoModel.WhatsAppPhone"),
        fields.get("BusinessInfoModel.WorkPhone"),
        summary_phones,
    ]
    result: list[str] = []
    for candidate in candidates:
        value = _text(candidate)
        if value and value not in result:
            result.append(value)
    return result


def _enabled_values(
    values: dict[str, Any], switches: dict[str, bool], labels: dict[str, str]
) -> dict[str, Any]:
    return {
        labels[key]: values[key]
        for key in labels
        if switches.get(key, True) and key in values
    }


def compact_customer(
    customer: Any,
    questionnaire: Any,
    accounts: list[Any],
    fields_config: dict[str, dict[str, bool]],
) -> dict[str, Any]:
    fields = dict(questionnaire.fields)
    name_parts = [
        _text(fields.get("GeneralInfoModel.Surname")),
        _text(fields.get("GeneralInfoModel.CustomerName")),
        _text(fields.get("GeneralInfoModel.Otchestvo")),
    ]
    full_name = " ".join(part for part in name_parts if part) or customer.name
    passport_values = {
        "document_type": _text(
            fields.get("GeneralInfoModel.DocumentTypeId"), prefer_label=True
        ),
        "series": _text(fields.get("GeneralInfoModel.DocumentSeries")),
        "number": _text(fields.get("GeneralInfoModel.DocumentNo")),
        "issued_by": _text(fields.get("GeneralInfoModel.IssueAuthority")),
        "issue_date": _text(fields.get("GeneralInfoModel.IssueDate")),
        "valid_until": _text(fields.get("GeneralInfoModel.DocumentValidTill")),
    }

    compact_accounts: list[dict[str, Any]] = []
    for account in accounts:
        raw = dict(account.data)
        currency_id = _text(raw.get("CurrencyID") or account.currency_id)
        currency = _text(raw.get("CurrencySymbol")) or CURRENCY_CODES.get(
            currency_id, currency_id
        )
        account_values = {
            "status": "закрыт" if account.is_closed else "активный",
            "currency": currency,
            "name": _text(raw.get("AccountName")),
            "number": account.account_no or _text(raw.get("MainAccountNo")),
            "open_date": _text(raw.get("OpenDate")),
            "close_date": _text(raw.get("CloseDate")) if account.is_closed else "",
        }
        compact_accounts.append(
            _enabled_values(account_values, fields_config["account"], ACCOUNT_LABELS)
        )

    is_legal = questionnaire.customer_type.lower() == "legal" or bool(
        _text(fields.get("GeneralInfoModel.CompanyName"))
    )
    if is_legal:
        legal_values = {
            "abs_id": customer.customer_id,
            "company_name": _text(fields.get("GeneralInfoModel.CompanyName"))
            or customer.name,
            "legal_form": _text(
                fields.get("GeneralInfoModel.LegalFormId"), prefer_label=True
            ),
            "inn": _text(fields.get("GeneralInfoModel.IdentificationNumber"))
            or customer.identity,
            "okpo": _text(fields.get("GeneralInfoModel.Okpo")),
            "registration_number": _text(
                fields.get("GeneralInfoModel.EvidenceRegistrationNo")
            ),
            "registration_date": _text(
                fields.get("GeneralInfoModel.DateOfRegistration")
            ),
            "registration_authority": _text(
                fields.get("GeneralInfoModel.RegistrationAuthority")
            ),
            "legal_address": _address(fields, "GeneralInfoModel.Registration"),
            "actual_address": _address(fields, "GeneralInfoModel.Residence"),
            "phones": _phones(fields, customer.phones),
            "account_count": len(accounts),
            "accounts": compact_accounts,
        }
        return _enabled_values(legal_values, fields_config["legal"], LEGAL_LABELS)

    customer_values = {
        "abs_id": customer.customer_id,
        "full_name": full_name,
        "passport": _enabled_values(
            passport_values, fields_config["passport"], PASSPORT_LABELS
        ),
        "inn": _text(fields.get("GeneralInfoModel.IdentificationNumber"))
        or customer.identity,
        "residence_address": _address(fields, "GeneralInfoModel.Residence"),
        "registration_address": _address(fields, "GeneralInfoModel.Registration"),
        "birth_date": _text(fields.get("GeneralInfoModel.DateOfBirth"))
        or customer.birth_date,
        "phones": _phones(fields, customer.phones),
        "account_count": len(accounts),
        "accounts": compact_accounts,
    }
    return _enabled_values(
        customer_values, fields_config["customer"], CUSTOMER_LABELS
    )


def fio_criteria(fio: str) -> dict[str, str]:
    """Convert 'Фамилия Имя Отчество' to Tolubay search fields."""
    parts = fio.strip().split()
    if not parts:
        raise ValueError("ФИО не может быть пустым")
    criteria = {"SearchSurname": parts[0]}
    if len(parts) > 1:
        criteria["SearchCustomerName"] = parts[1]
    if len(parts) > 2:
        criteria["SearchOtchestvo"] = " ".join(parts[2:])
    return criteria


def build_queries(
    inn_values: list[str],
    fio_values: list[str],
    company_values: list[str] | None = None,
) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    for value in inn_values:
        normalized = value.strip()
        if normalized:
            queries.append(
                {
                    "kind": "ИНН",
                    "value": normalized,
                    "criteria": {"SearchIdentificationNo": normalized},
                }
            )
    for value in fio_values:
        normalized = value.strip()
        if normalized:
            queries.append(
                {"kind": "ФИО", "value": normalized, "criteria": fio_criteria(normalized)}
            )
    for value in company_values or []:
        normalized = value.strip()
        if normalized:
            queries.append(
                {
                    "kind": "Юрлицо",
                    "value": normalized,
                    "criteria": {"SearchCompanyName": normalized},
                }
            )
    if not queries:
        raise ValueError("Укажите хотя бы один --inn, --fio или --company")
    return queries


def lookup(
    client: TolubayClient,
    queries: list[dict[str, Any]],
    fields_config: dict[str, dict[str, bool]] | None = None,
) -> dict[str, Any]:
    fields_config = fields_config or load_fields_config(None)
    results: list[dict[str, Any]] = []
    unique_customers: dict[str, dict[str, Any]] = {}

    for query in queries:
        customers = client.search_customers(query["criteria"])
        if not customers:
            results.append(
                {
                    "тип": query["kind"],
                    "значение": query["value"],
                    "найден": False,
                    "сообщение": "Клиент не найден",
                }
            )
            continue

        ids: list[str] = []
        for customer in customers:
            if customer.customer_id in unique_customers:
                if (
                    query["kind"] == "Юрлицо"
                    and "наименование_организации"
                    not in unique_customers[customer.customer_id]
                ):
                    continue
                ids.append(customer.customer_id)
                continue
            questionnaire = client.get_customer_questionnaire(customer.customer_id)
            is_legal = questionnaire.customer_type.lower() == "legal" or bool(
                _text(questionnaire.fields.get("GeneralInfoModel.CompanyName"))
            )
            if query["kind"] == "Юрлицо" and not is_legal:
                continue
            accounts = client.get_accounts(customer.customer_id, include_closed=True)
            ids.append(customer.customer_id)
            unique_customers[customer.customer_id] = compact_customer(
                customer, questionnaire, accounts, fields_config
            )

        results.append(
            {
                "тип": query["kind"],
                "значение": query["value"],
                "найден": bool(ids),
                "сообщение": (
                    f"Найдено клиентов: {len(ids)}" if ids else "Клиент не найден"
                ),
            }
        )

    return {
        "поиск": results,
        "клиенты": list(unique_customers.values()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read-only поиск физлиц и юрлиц Tolubay"
    )
    parser.add_argument("--inn", action="append", default=[], help="ИНН; можно повторять")
    parser.add_argument(
        "--fio",
        action="append",
        default=[],
        help='ФИО в порядке "Фамилия Имя Отчество"; можно повторять',
    )
    parser.add_argument(
        "--company",
        action="append",
        default=[],
        help="Наименование юрлица/ОсОО; можно повторять",
    )
    parser.add_argument(
        "--fields-config",
        type=Path,
        default=SCRIPT_DIR / "client_lookup_fields.json",
        help="JSON-файл с переключателями полей итогового файла",
    )
    parser.add_argument(
        "--base-url", default=os.getenv("TOLUBAY_BASE_URL", "https://ob.tolubay.kg")
    )
    parser.add_argument("--login", default=os.getenv("TOLUBAY_LOGIN"))
    parser.add_argument("--ca-file", default=os.getenv("TOLUBAY_CA_FILE"))
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить TLS-проверку только для временной диагностики",
    )
    args = parser.parse_args()

    try:
        queries = build_queries(args.inn, args.fio, args.company)
        username = args.login or input("Логин Tolubay: ").strip()
        password = os.getenv("TOLUBAY_PASSWORD") or getpass.getpass("Пароль Tolubay: ")
        client = TolubayClient(
            TolubayConfig(
                base_url=args.base_url,
                ca_file=args.ca_file,
                verify_tls=not args.insecure,
                lookup_only=True,
            )
        )
        client.login(username, password)
        fields_config = load_fields_config(args.fields_config)
        payload = lookup(client, queries, fields_config)
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    except Exception as exc:  # concise CLI boundary; secrets are never included
        print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
