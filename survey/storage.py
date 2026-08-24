"""Where submitted responses go.

Two backends, chosen from Streamlit secrets at startup:

* `LocalCsvStorage`  — appends to a CSV file next to the app. Correct for local runs.
  On Streamlit Community Cloud the container filesystem is ephemeral, so this
  survives restarts only if you accept losing data on redeploy.
* `GoogleSheetsStorage` — appends a row to a worksheet. Survives restarts, and the
  sheet exports to CSV directly. Use this for a real run.

Both are append-only: a submission is never updated or deleted through this module.
"""

from __future__ import annotations

import csv
import io
import threading
from pathlib import Path
from typing import Any, Protocol, Sequence


class StorageError(RuntimeError):
    """Raised when a response could not be persisted."""


class Storage(Protocol):
    """Append-only sink for survey responses."""

    name: str

    def append(self, columns: Sequence[str], row: dict[str, Any]) -> None:
        """Persist one submission. Must not overwrite earlier submissions."""

    def read_all(self) -> list[dict[str, Any]]:
        """Every submission stored so far, oldest first."""


class LocalCsvStorage:
    """Appends rows to a CSV file, writing the header on first use."""

    name = "local CSV file"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def append(self, columns: Sequence[str], row: dict[str, Any]) -> None:
        columns = list(columns)
        try:
            with self._lock:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                is_new = not self.path.exists() or self.path.stat().st_size == 0
                with self.path.open("a", encoding="utf-8", newline="") as handle:
                    writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
                    if is_new:
                        writer.writeheader()
                    writer.writerow({column: row.get(column, "") for column in columns})
        except OSError as exc:
            raise StorageError(f"could not append to {self.path}: {exc}") from exc

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            with self.path.open("r", encoding="utf-8", newline="") as handle:
                return list(csv.DictReader(handle))
        except OSError as exc:
            raise StorageError(f"could not read {self.path}: {exc}") from exc


class GoogleSheetsStorage:
    """Appends rows to the first worksheet of a Google Sheet via a service account."""

    name = "Google Sheets"

    def __init__(self, service_account_info: dict[str, Any], sheet_key: str, worksheet: str = "responses"):
        self._info = service_account_info
        self._sheet_key = sheet_key
        self._worksheet_name = worksheet
        self._lock = threading.Lock()

    def _worksheet(self):
        try:
            import gspread
        except ImportError as exc:  # pragma: no cover - depends on optional extra
            raise StorageError(
                "the Google Sheets backend needs the 'gspread' package; "
                "add it to requirements.txt"
            ) from exc
        try:
            client = gspread.service_account_from_dict(self._info)
            spreadsheet = client.open_by_key(self._sheet_key)
            try:
                return spreadsheet.worksheet(self._worksheet_name)
            except gspread.WorksheetNotFound:
                return spreadsheet.add_worksheet(self._worksheet_name, rows=1000, cols=400)
        except Exception as exc:  # gspread raises a wide range of API errors
            raise StorageError(f"could not open the responses sheet: {exc}") from exc

    def append(self, columns: Sequence[str], row: dict[str, Any]) -> None:
        columns = list(columns)
        with self._lock:
            worksheet = self._worksheet()
            try:
                if not worksheet.row_values(1):
                    worksheet.update("A1", [columns])
                worksheet.append_row(
                    [str(row.get(column, "")) for column in columns],
                    value_input_option="RAW",
                )
            except Exception as exc:
                raise StorageError(f"could not append the response: {exc}") from exc

    def read_all(self) -> list[dict[str, Any]]:
        worksheet = self._worksheet()
        try:
            return worksheet.get_all_records()
        except Exception as exc:
            raise StorageError(f"could not read the responses sheet: {exc}") from exc


def build_storage(secrets: Any, default_csv_path: str | Path) -> Storage:
    """Pick a backend from Streamlit secrets, falling back to a local CSV file.

    Configure Google Sheets by adding to `.streamlit/secrets.toml`:

        sheet_key = "<the id from the sheet URL>"
        [gcp_service_account]
        type = "service_account"
        ...
    """
    try:
        has_sheet = "gcp_service_account" in secrets and "sheet_key" in secrets
    except Exception:
        has_sheet = False

    if has_sheet:
        return GoogleSheetsStorage(
            service_account_info=dict(secrets["gcp_service_account"]),
            sheet_key=str(secrets["sheet_key"]),
            worksheet=str(secrets.get("worksheet_name", "responses")),
        )
    return LocalCsvStorage(default_csv_path)


def to_csv_bytes(columns: Sequence[str], rows: Sequence[dict[str, Any]]) -> bytes:
    """Render rows as UTF-8 CSV bytes with a BOM so Excel opens them correctly."""
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue().encode("utf-8-sig")
