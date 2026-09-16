from __future__ import annotations

import subprocess
from pathlib import Path


class MemorialOrderProcessingError(RuntimeError):
    """The downloaded memorial-order file could not be prepared for printing."""


def _processor_path() -> Path:
    return Path(__file__).with_name("memorial_order_xls.ps1")


def process_memorial_order_xls(path: str | Path, *, print_after_processing: bool = False) -> Path:
    """Prepare one downloaded XLS/XLSX memorial order in place for printing."""
    report_path = Path(path).expanduser().resolve()
    if report_path.suffix.lower() not in {".xls", ".xlsx"}:
        raise ValueError("Мемориальный ордер должен быть файлом XLS или XLSX")
    if not report_path.is_file():
        raise FileNotFoundError(report_path)

    script_path = _processor_path()
    if not script_path.is_file():
        raise MemorialOrderProcessingError(f"Не найден обработчик Excel: {script_path}")

    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script_path),
            "-InputPath",
            str(report_path),
            *( ["-PrintAfterProcessing"] if print_after_processing else [] ),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode:
        detail = completed.stderr.strip() or completed.stdout.strip() or "неизвестная ошибка Excel"
        raise MemorialOrderProcessingError(f"Не удалось подготовить мемориальный ордер: {detail}")
    return report_path


def print_memorial_order_xls(path: str | Path) -> Path:
    """Compatibility helper for explicitly requested print processing."""
    return process_memorial_order_xls(path, print_after_processing=True)
