from __future__ import annotations

import unittest
from dataclasses import dataclass

from client_lookup import build_queries, fio_criteria, load_fields_config, lookup
from automation_hub.tolubay import AccountRecord, CustomerQuestionnaire, CustomerSummary


@dataclass
class _FakeClient:
    def search_customers(self, criteria):
        if criteria.get("SearchIdentificationNo") == "missing":
            return []
        return [
            CustomerSummary(
                customer_id="42",
                name="Иванов Иван Иванович",
                identity="12345678901234",
                birth_date="",
                address="",
                phones="0555000000",
            )
        ]

    def get_customer_questionnaire(self, customer_id):
        return CustomerQuestionnaire(
            customer_id=str(customer_id),
            customer_type="Private",
            fields={
                "GeneralInfoModel.Surname": "Иванов",
                "GeneralInfoModel.CustomerName": "Иван",
                "GeneralInfoModel.Otchestvo": "Иванович",
                "GeneralInfoModel.IdentificationNumber": "12345678901234",
                "GeneralInfoModel.DateOfBirth": "01.01.1990",
                "GeneralInfoModel.DocumentTypeId": {"value": "1", "text": "ID-карта"},
                "GeneralInfoModel.DocumentSeries": "AN",
                "GeneralInfoModel.DocumentNo": "1234567",
                "GeneralInfoModel.IssueAuthority": "MKK",
                "GeneralInfoModel.IssueDate": "02.02.2020",
                "GeneralInfoModel.DocumentValidTill": "02.02.2030",
                "GeneralInfoModel.ResidenceCityName": "Бишкек",
                "GeneralInfoModel.ResidenceStreet": "Мира",
                "GeneralInfoModel.ResidenceHouse": "1",
                "GeneralInfoModel.RegistrationCityName": "Ош",
                "GeneralInfoModel.RegistrationStreet": "Ленина",
                "AdditionalInfoModel.ContactPhone1": "0555000000",
            },
            source_url="https://example.test/view",
        )

    def get_accounts(self, customer_id, *, include_closed=False):
        assert include_closed
        return [
            AccountRecord(
                customer_id=str(customer_id),
                account_no="1001",
                currency_id=417,
                status_id=1,
                is_closed=False,
                data={
                    "MainAccountNo": "1001",
                    "CurrencyID": 417,
                    "AccountName": "Текущий счет",
                    "OpenDate": "03.03.2020",
                    "CloseDate": None,
                },
            )
        ]


@dataclass
class _FakeLegalClient:
    def search_customers(self, criteria):
        return [
            CustomerSummary(
                customer_id="77",
                name='ОсОО "Тест"',
                identity="12345678901234",
                birth_date="",
                address="",
                phones="0312000000",
            )
        ]

    def get_customer_questionnaire(self, customer_id):
        return CustomerQuestionnaire(
            customer_id=str(customer_id),
            customer_type="Legal",
            fields={
                "GeneralInfoModel.CompanyName": 'ОсОО "Тест"',
                "GeneralInfoModel.LegalFormId": {"value": "2", "text": "ОсОО"},
                "GeneralInfoModel.IdentificationNumber": "12345678901234",
                "GeneralInfoModel.Okpo": "12345678",
                "GeneralInfoModel.EvidenceRegistrationNo": "REG-1",
                "GeneralInfoModel.DateOfRegistration": "01.01.2020",
                "GeneralInfoModel.RegistrationAuthority": "Минюст",
                "GeneralInfoModel.RegistrationCityName": "Бишкек",
                "GeneralInfoModel.RegistrationStreet": "Мира",
                "GeneralInfoModel.ResidenceCityName": "Бишкек",
                "GeneralInfoModel.ResidenceStreet": "Чуй",
                "AdditionalInfoModel.ContactPhone1": "0312000000",
            },
            source_url="https://example.test/legal",
        )

    def get_accounts(self, customer_id, *, include_closed=False):
        assert include_closed
        return [
            AccountRecord(
                customer_id=str(customer_id),
                account_no="2001",
                currency_id=840,
                status_id=1,
                is_closed=False,
                data={
                    "MainAccountNo": "2001",
                    "CurrencyID": 840,
                    "AccountName": "Расчетный счет",
                    "OpenDate": "02.02.2020",
                    "CloseDate": None,
                },
            )
        ]

class ClientLookupTests(unittest.TestCase):
    def test_fio_mapping(self):
        self.assertEqual(
            fio_criteria("Иванов Иван Иванович"),
            {
                "SearchSurname": "Иванов",
                "SearchCustomerName": "Иван",
                "SearchOtchestvo": "Иванович",
            },
        )

    def test_company_query_mapping(self):
        queries = build_queries([], [], ['ОсОО "Тест"'])
        self.assertEqual(
            queries,
            [
                {
                    "kind": "Юрлицо",
                    "value": 'ОсОО "Тест"',
                    "criteria": {"SearchCompanyName": 'ОсОО "Тест"'},
                }
            ],
        )

    def test_multiple_queries_found_and_missing(self):
        queries = build_queries(["123", "missing"], ["Иванов Иван"])
        payload = lookup(_FakeClient(), queries)
        self.assertEqual(len(payload["поиск"]), 3)
        self.assertTrue(payload["поиск"][0]["найден"])
        self.assertFalse(payload["поиск"][1]["найден"])
        self.assertEqual(payload["поиск"][1]["сообщение"], "Клиент не найден")
        self.assertEqual(len(payload["клиенты"]), 1)
        customer = payload["клиенты"][0]
        self.assertEqual(customer["ID_в_ABS"], "42")
        self.assertEqual(customer["ФИО"], "Иванов Иван Иванович")
        self.assertEqual(customer["ИНН"], "12345678901234")
        self.assertEqual(customer["количество_счетов"], 1)
        self.assertEqual(customer["счета"][0]["валюта"], "KGS")
        self.assertEqual(customer["счета"][0]["статус"], "активный")
        self.assertEqual(customer["счета"][0]["номер_счета"], "1001")

    def test_fields_can_be_disabled_without_changing_code(self):
        config = load_fields_config(None)
        config["customer"]["abs_id"] = False
        config["customer"]["phones"] = False
        config["passport"]["issued_by"] = False
        config["account"]["close_date"] = False
        payload = lookup(_FakeClient(), build_queries(["123"], []), config)
        customer = payload["клиенты"][0]
        self.assertNotIn("ID_в_ABS", customer)
        self.assertNotIn("телефоны", customer)
        self.assertNotIn("кем_выдан", customer["паспорт"])
        self.assertNotIn("дата_закрытия", customer["счета"][0])

    def test_legal_entity_has_its_own_compact_schema(self):
        payload = lookup(
            _FakeLegalClient(),
            build_queries([], [], ['ОсОО "Тест"']),
        )
        customer = payload["клиенты"][0]
        self.assertEqual(customer["ID_в_ABS"], "77")
        self.assertEqual(customer["наименование_организации"], 'ОсОО "Тест"')
        self.assertEqual(customer["организационно_правовая_форма"], "ОсОО")
        self.assertEqual(customer["ОКПО"], "12345678")
        self.assertEqual(customer["количество_счетов"], 1)
        self.assertEqual(customer["счета"][0]["валюта"], "USD")
        self.assertNotIn("паспорт", customer)
        self.assertNotIn("дата_рождения", customer)

    def test_company_search_filters_out_private_customers(self):
        payload = lookup(_FakeClient(), build_queries([], [], ["а"]))
        self.assertFalse(payload["поиск"][0]["найден"])
        self.assertEqual(payload["поиск"][0]["сообщение"], "Клиент не найден")
        self.assertEqual(payload["клиенты"], [])


if __name__ == "__main__":
    unittest.main()
