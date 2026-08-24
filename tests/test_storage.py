"""Tests for the storage backends and the wide-row -> table mapping."""

import json

import pytest

from survey.storage import (
    GoogleSheetsStorage,
    LocalCsvStorage,
    StorageError,
    SupabaseStorage,
    build_storage,
    parse_rating_column,
    rating_payloads,
    response_payload,
    split_row,
)

ROW = {
    "submission_id": "sub-1",
    "submitted_at_utc": "2026-08-24T10:00:00+00:00",
    "participant_id": "P42",
    "email": "tester@example.com",
    "familiarity_llm_agents": 4,
    "familiarity_mcp": 3,
    "consent": "yes",
    "duration_seconds": 812,
    "impact__calendar__get-event": 3,
    "sens__calendar__executive": 4,
    "blast__calendar__executive__get-event": 2,
    "blast__calendar__executive__list-calendars": "N/A",
    "ambiguity_notes": "unclear",
    "comments": "",
    "confidence": 5,
}


class FakeTable:
    def __init__(self, name, log):
        self.name = name
        self.log = log
        self._rows = []

    def insert(self, payload):
        self.log.append((self.name, "insert", payload))
        return self

    def select(self, *_):
        return self

    def order(self, *_):
        return self

    def execute(self):
        return type("Result", (), {"data": self._rows})()


class FakeSupabase:
    def __init__(self):
        self.log = []
        self.tables = {}
        self.responses_data = []

    def table(self, name):
        table = self.tables.setdefault(name, FakeTable(name, self.log))
        if name == "responses":
            table._rows = self.responses_data
        return table


class TestColumnParsing:
    def test_metadata_columns_are_not_ratings(self):
        assert parse_rating_column("participant_id") is None
        assert parse_rating_column("submitted_at_utc") is None

    def test_impact_column_has_a_tool_and_no_asset(self):
        assert parse_rating_column("impact__calendar__get-event") == (
            "impact",
            "calendar",
            "",
            "get-event",
        )

    def test_sensitivity_column_has_an_asset_and_no_tool(self):
        assert parse_rating_column("sens__calendar__executive") == (
            "sensitivity",
            "calendar",
            "executive",
            "",
        )

    def test_blast_column_has_both(self):
        assert parse_rating_column("blast__calendar__executive__get-event") == (
            "blast",
            "calendar",
            "executive",
            "get-event",
        )

    def test_underscores_inside_names_are_preserved(self):
        assert parse_rating_column("impact__github__create_or_update_file") == (
            "impact",
            "github",
            "",
            "create_or_update_file",
        )

    def test_split_row_separates_metadata_from_ratings(self):
        metadata, ratings = split_row(ROW)
        assert metadata["participant_id"] == "P42"
        assert "impact__calendar__get-event" not in metadata
        assert len(ratings) == 4


class TestSupabasePayloads:
    def test_response_payload_carries_scalar_metadata(self):
        payload = response_payload(ROW)
        assert payload["submission_id"] == "sub-1"
        assert payload["participant_id"] == "P42"
        assert payload["consent"] == "yes"

    def test_numeric_metadata_is_stored_as_integers(self):
        payload = response_payload(ROW)
        assert payload["familiarity_llm_agents"] == 4
        assert payload["duration_seconds"] == 812
        assert payload["confidence"] == 5

    def test_blank_numeric_metadata_becomes_null(self):
        payload = response_payload({**ROW, "confidence": ""})
        assert payload["confidence"] is None

    def test_the_whole_row_is_kept_as_json(self):
        payload = response_payload(ROW)
        assert payload["answers"]["blast__calendar__executive__get-event"] == 2
        assert payload["answers"]["impact__calendar__get-event"] == 3

    def test_rating_payloads_have_one_record_per_rating(self):
        payloads = rating_payloads(ROW)
        assert len(payloads) == 4
        assert all(p["submission_id"] == "sub-1" for p in payloads)

    def test_rating_payload_carries_coordinates_and_numeric_value(self):
        payloads = {(p["dimension"], p["asset"], p["tool"]): p for p in rating_payloads(ROW)}
        blast = payloads[("blast", "executive", "get-event")]
        assert blast["server"] == "calendar"
        assert blast["value"] == "2"
        assert blast["value_num"] == 2

    def test_na_rating_keeps_its_text_and_has_no_numeric_value(self):
        payloads = {(p["dimension"], p["asset"], p["tool"]): p for p in rating_payloads(ROW)}
        na = payloads[("blast", "executive", "list-calendars")]
        assert na["value"] == "N/A"
        assert na["value_num"] is None


class TestSupabaseStorage:
    @pytest.fixture
    def fake(self):
        return FakeSupabase()

    @pytest.fixture
    def storage(self, fake):
        return SupabaseStorage("https://x.supabase.co", "key", client_factory=lambda u, k: fake)

    def test_append_writes_the_response_then_its_ratings(self, storage, fake):
        storage.append(list(ROW), ROW)
        tables = [entry[0] for entry in fake.log]
        assert tables == ["responses", "ratings"]

    def test_append_sends_one_ratings_batch(self, storage, fake):
        storage.append(list(ROW), ROW)
        _, _, payload = fake.log[1]
        assert isinstance(payload, list)
        assert len(payload) == 4

    def test_append_reports_a_failed_response_write(self, fake):
        def explode(*_):
            raise RuntimeError("permission denied")

        fake.table("responses").insert = explode
        storage = SupabaseStorage("u", "k", client_factory=lambda u, k: fake)
        with pytest.raises(StorageError, match="could not write the response"):
            storage.append(list(ROW), ROW)

    def test_append_reports_a_failed_ratings_write_without_claiming_success(self, fake):
        def explode(*_):
            raise RuntimeError("boom")

        fake.table("ratings").insert = explode
        storage = SupabaseStorage("u", "k", client_factory=lambda u, k: fake)
        with pytest.raises(StorageError, match="ratings were not"):
            storage.append(list(ROW), ROW)

    def test_read_all_rebuilds_the_wide_rows(self, storage, fake):
        fake.responses_data.append({"answers": ROW})
        assert storage.read_all() == [ROW]

    def test_read_all_accepts_json_encoded_answers(self, storage, fake):
        fake.responses_data.append({"answers": json.dumps(ROW)})
        assert storage.read_all()[0]["participant_id"] == "P42"

    def test_read_all_is_empty_when_nothing_is_stored(self, storage):
        assert storage.read_all() == []

    def test_a_connection_failure_is_reported_as_a_storage_error(self):
        def explode(url, key):
            raise RuntimeError("bad url")

        storage = SupabaseStorage("u", "k", client_factory=explode)
        with pytest.raises(StorageError, match="could not connect to Supabase"):
            storage.append(list(ROW), ROW)


class TestBackendSelection:
    def test_supabase_is_chosen_when_configured(self, tmp_path):
        secrets = {"supabase_url": "https://x.supabase.co", "supabase_key": "k"}
        assert isinstance(build_storage(secrets, tmp_path / "r.csv"), SupabaseStorage)

    def test_supabase_wins_over_sheets(self, tmp_path):
        secrets = {
            "supabase_url": "https://x.supabase.co",
            "supabase_key": "k",
            "gcp_service_account": {"type": "service_account"},
            "sheet_key": "abc",
        }
        assert isinstance(build_storage(secrets, tmp_path / "r.csv"), SupabaseStorage)

    def test_sheets_is_used_when_supabase_is_absent(self, tmp_path):
        secrets = {"gcp_service_account": {"type": "service_account"}, "sheet_key": "abc"}
        assert isinstance(build_storage(secrets, tmp_path / "r.csv"), GoogleSheetsStorage)

    def test_local_csv_is_the_fallback(self, tmp_path):
        assert isinstance(build_storage({}, tmp_path / "r.csv"), LocalCsvStorage)

    def test_half_configured_supabase_does_not_win(self, tmp_path):
        secrets = {"supabase_url": "https://x.supabase.co"}
        assert isinstance(build_storage(secrets, tmp_path / "r.csv"), LocalCsvStorage)


class TestLocalCsvStorage:
    def test_appends_rather_than_overwrites(self, tmp_path):
        storage = LocalCsvStorage(tmp_path / "r.csv")
        storage.append(list(ROW), ROW)
        storage.append(list(ROW), {**ROW, "submission_id": "sub-2", "participant_id": "P43"})
        rows = storage.read_all()
        assert [r["participant_id"] for r in rows] == ["P42", "P43"]

    def test_read_all_is_empty_before_the_first_write(self, tmp_path):
        assert LocalCsvStorage(tmp_path / "missing.csv").read_all() == []
