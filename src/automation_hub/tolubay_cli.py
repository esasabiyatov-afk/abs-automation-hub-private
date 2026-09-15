from __future__ import annotations

import argparse
import getpass
import os
from pathlib import Path

from .tolubay import TolubayClient, TolubayConfig


def main() -> None:
    parser = argparse.ArgumentParser(description="Сформировать отчет Tolubay по XLSX-шаблону без браузера")
    parser.add_argument("--template", required=True, type=Path)
    parser.add_argument("--date", required=True, help="Дата отчета, например 21.08.2026")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--base-url", default=os.getenv("TOLUBAY_BASE_URL", "https://ob.tolubay.kg"))
    parser.add_argument("--login", default=os.getenv("TOLUBAY_LOGIN"))
    parser.add_argument("--ca-file", default=os.getenv("TOLUBAY_CA_FILE"))
    parser.add_argument("--timeout", type=float, default=180.0)
    parser.add_argument("--use-cache", action="store_true")
    parser.add_argument("--include-formulas", action="store_true")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Отключить проверку TLS-сертификата (только для временной диагностики)",
    )
    args = parser.parse_args()

    username = args.login or input("Логин Tolubay: ").strip()
    password = os.getenv("TOLUBAY_PASSWORD") or getpass.getpass("Пароль Tolubay: ")
    client = TolubayClient(
        TolubayConfig(
            base_url=args.base_url,
            ca_file=args.ca_file,
            verify_tls=not args.insecure,
        )
    )
    client.login(username, password)
    result = client.generate_template_report(
        args.template,
        args.date,
        args.output,
        use_cache=args.use_cache,
        include_formula_as_comment=args.include_formulas,
        timeout_seconds=args.timeout,
    )
    print(result.path)


if __name__ == "__main__":
    main()
