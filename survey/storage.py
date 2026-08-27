"""Where submitted responses go.

Only completed submissions are stored: the app writes once, when the participant
presses Submit. An abandoned session leaves nothing behind.

Three backends, chosen from Streamlit secrets at startup:

* `LocalCsvStorage`  — appends to a CSV file next to the app. Correct for local runs.
  On Streamlit Community Cloud the container filesystem is ephemeral, so this
  survives restarts only if you accept losing data on redeploy.
* `GoogleSheetsStorage` — appends a row to a worksheet. Survives restarts, and the
  sheet exports to CSV directly.
* `SupabaseStorage` — writes to an external Supabase (Postgres) project. Every
  submission lands in two tables: `responses`, one row per participant with the whole
  answer set as JSONB, and `ratings`, one row per individual rating so the data can be
  queried directly in SQL. This is the backend for a real run.

All three are append-only: a submission is never updated or deleted through this
module.
"""

from __future__ import annotations

import csv
import io
import json
import threading
from pathlib import Path
from typing import Any, Callable, Iterable, Protocol, Sequence


RATING_PREFIXES = {"impact": "impact", "sens": "sensitivity", "blast": "blast"}


def parse_rating_column(name: str) -> tuple[str, str, str, str] | None:
    """`impact__calendar__get-event` -> ("impact", "calendar", "", "get-event").

    Returns None for metadata columns. Keeps the storage layer independent of the
    survey config: the column name already carries the full coordinates.
    """
    parts = name.split("__")
    kind = RATING_PREFIXES.get(parts[0])
    if kind is None:
        return None
    if kind == "impact" and len(parts) == 3:
        return ("impact", parts[1], "", parts[2])
    if kind == "sensitivity" and len(parts) == 3:
        return ("sensitivity", parts[1], parts[2], "")
    if kind == "blast" and len(parts) == 4:
        return ("blast", parts[1], parts[2], parts[3])
    return None


def split_row(row: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Separate a wide row into scalar metadata and one record per rating."""
    metadata: dict[str, Any] = {}
    ratings: list[dict[str, Any]] = []
    for name, value in row.items():
        parsed = parse_rating_column(name)
        if parsed is None:
            metadata[name] = value
            continue
        dimension, server, asset, tool = parsed
        ratings.append(
            {
                "dimension": dimension,
                "server": server,
                "asset": asset,
                "tool": tool,
                "value": "" if value is None else str(value),
            }
        )
    return metadata, ratings


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



# The tables the Supabase backend writes to. Run this once in the Supabase SQL
# editor - the client library cannot issue DDL. Repeated in docs/deployment.md.
SUPABASE_SCHEMA_SQL = """
create table if not exists responses (
    submission_id          text primary key,
    submitted_at_utc       timestamptz,
    participant_id         text,
    email                  text,
    familiarity_llm_agents integer,
    familiarity_mcp        integer,
    consent                text,
    duration_seconds       integer,
    ambiguity_notes        text,
    comments               text,
    confidence             integer,
    answers                jsonb not null
);

create table if not exists ratings (
    submission_id text not null references responses(submission_id) on delete cascade,
    dimension     text not null,
    server        text not null,
    asset         text not null default '',
    tool          text not null default '',
    value         text not null,
    value_num     integer,
    primary key (submission_id, dimension, server, asset, tool)
);

create index if not exists ratings_dimension_idx on ratings (dimension, server);

alter table responses enable row level security;
alter table ratings   enable row level security;
"""

RESPONSE_FIELDS = (
    "submission_id",
    "submitted_at_utc",
    "participant_id",
    "email",
    "familiarity_llm_agents",
    "familiarity_mcp",
    "consent",
    "duration_seconds",
    "ambiguity_notes",
    "comments",
    "confidence",
)
_INT_FIELDS = {"familiarity_llm_agents", "familiarity_mcp", "duration_seconds", "confidence"}


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def response_payload(row: dict[str, Any]) -> dict[str, Any]:
    """The `responses` row: scalar metadata plus the full answer set as JSON."""
    metadata, _ = split_row(row)
    payload: dict[str, Any] = {}
    for field in RESPONSE_FIELDS:
        raw = metadata.get(field, "")
        if field in _INT_FIELDS:
            payload[field] = _as_int(raw)
        elif field == "submitted_at_utc":
            payload[field] = raw or None
        else:
            payload[field] = "" if raw is None else str(raw)
    payload["answers"] = row
    return payload


def rating_payloads(row: dict[str, Any]) -> list[dict[str, Any]]:
    """The `ratings` rows: one per individual rating, ready for SQL analysis."""
    _, ratings = split_row(row)
    submission_id = str(row.get("submission_id", ""))
    return [
        {
            "submission_id": submission_id,
            "dimension": rating["dimension"],
            "server": rating["server"],
            "asset": rating["asset"],
            "tool": rating["tool"],
            "value": rating["value"],
            "value_num": _as_int(rating["value"]),
        }
        for rating in ratings
    ]


class SupabaseStorage:
    """Writes each submission to a Supabase project via the official client."""

    name = "Supabase"

    def __init__(
        self,
        url: str,
        key: str,
        client_factory: Callable[[str, str], Any] | None = None,
    ):
        self._url = url
        self._key = key
        self._client_factory = client_factory or self._create_client
        self._client: Any = None
        self._lock = threading.Lock()

    @staticmethod
    def _create_client(url: str, key: str):  # pragma: no cover - needs the package
        try:
            from supabase import create_client
        except ImportError as exc:
            raise StorageError(
                "the Supabase backend needs the 'supabase' package; "
                "add it to requirements.txt"
            ) from exc
        return create_client(url, key)

    def client(self):
        if self._client is None:
            try:
                self._client = self._client_factory(self._url, self._key)
            except StorageError:
                raise
            except Exception as exc:
                raise StorageError(f"could not connect to Supabase: {exc}") from exc
        return self._client

    def append(self, columns: Sequence[str], row: dict[str, Any]) -> None:
        ordered = {column: row.get(column, "") for column in columns}
        client = self.client()
        with self._lock:
            try:
                client.table("responses").insert(response_payload(ordered)).execute()
            except Exception as exc:
                raise StorageError(f"could not write the response to Supabase: {exc}") from exc
            try:
                client.table("ratings").insert(rating_payloads(ordered)).execute()
            except Exception as exc:
                # The response row is already safe and `answers` holds every value.
                # Surface the partial failure rather than pretending it all worked.
                raise StorageError(
                    "the response was saved but its individual ratings were not "
                    f"({exc}); the full answer set is still in responses.answers"
                ) from exc

    def read_all(self) -> list[dict[str, Any]]:
        client = self.client()
        try:
            result = (
                client.table("responses").select("answers").order("submitted_at_utc").execute()
            )
        except Exception as exc:
            raise StorageError(f"could not read responses from Supabase: {exc}") from exc

        rows: list[dict[str, Any]] = []
        for record in getattr(result, "data", None) or []:
            answers = record.get("answers")
            if isinstance(answers, (str, bytes)):
                answers = json.loads(answers)
            rows.append(dict(answers or {}))
        return rows


def _secret(secrets: Any, key: str) -> Any:
    try:
        return secrets[key] if key in secrets else None
    except Exception:
        return None


def build_storage(secrets: Any, default_csv_path: str | Path) -> Storage:
    """Pick a backend from Streamlit secrets, most durable first.

    Supabase wins if `supabase_url` and `supabase_key` are set; then Google Sheets if
    a service account and `sheet_key` are set; otherwise a local CSV file, which is
    for development only and does not survive a Streamlit Cloud restart.
    """
    supabase_url = _secret(secrets, "supabase_url")
    supabase_key = _secret(secrets, "supabase_key")
    if supabase_url and supabase_key:
        return SupabaseStorage(str(supabase_url), str(supabase_key))

    has_sheet = bool(_secret(secrets, "gcp_service_account")) and bool(_secret(secrets, "sheet_key"))
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
