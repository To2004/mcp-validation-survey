"""Regression tests for defects found in review.

Each of these was reachable in production and invisible to the suite at the time.
"""

import csv

import pytest

from survey.config import load_config, load_config_from_dict
from survey.schema import csv_columns, long_format_rows, missing_required, response_to_row
from survey.storage import LocalCsvStorage, StorageError
from tests.test_config import minimal

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT / "survey_config.json")


def a_row(**overrides):
    row = {column: "" for column in csv_columns(CONFIG)}
    row["submission_id"] = "s1"
    row["participant_id"] = "P01"
    row.update(overrides)
    return row


class TestCsvHeaderMismatch:
    """A survey change must not silently misalign every value in an old file."""

    def test_appending_under_a_stale_header_is_refused(self, tmp_path):
        path = tmp_path / "responses.csv"
        old_columns = ["submission_id", "participant_id", "duration_seconds"]
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=old_columns)
            writer.writeheader()
            writer.writerow({c: "old" for c in old_columns})

        storage = LocalCsvStorage(path)
        with pytest.raises(StorageError, match="different survey version"):
            storage.append(csv_columns(CONFIG), a_row())

    def test_the_stale_file_is_left_untouched(self, tmp_path):
        path = tmp_path / "responses.csv"
        path.write_text("submission_id,participant_id\nx,y\n", encoding="utf-8")
        before = path.read_text(encoding="utf-8")
        with pytest.raises(StorageError):
            LocalCsvStorage(path).append(csv_columns(CONFIG), a_row())
        assert path.read_text(encoding="utf-8") == before

    def test_a_matching_header_still_appends(self, tmp_path):
        path = tmp_path / "responses.csv"
        storage = LocalCsvStorage(path)
        storage.append(csv_columns(CONFIG), a_row())
        storage.append(csv_columns(CONFIG), a_row(submission_id="s2"))
        assert [r["submission_id"] for r in storage.read_all()] == ["s1", "s2"]


class TestConcurrentAppendsShareALock:
    def test_two_instances_of_the_same_path_share_a_lock(self, tmp_path):
        # build_storage returns a new instance per call; a per-instance lock
        # would leave concurrent submissions unserialised.
        path = tmp_path / "responses.csv"
        assert LocalCsvStorage(path)._lock is LocalCsvStorage(path)._lock

    def test_different_paths_do_not_share_a_lock(self, tmp_path):
        assert LocalCsvStorage(tmp_path / "a.csv")._lock is not LocalCsvStorage(tmp_path / "b.csv")._lock


class TestLongExportKeepsEveryResponse:
    """A row with no assignment recorded must not vanish from the export."""

    def test_a_row_without_an_assignment_still_exports(self):
        row = a_row(assigned_servers="")
        records = long_format_rows(CONFIG, [row])
        assert records, "response silently dropped from the long export"

    def test_an_assigned_row_covers_only_its_servers(self):
        row = a_row(assigned_servers="calendar")
        servers = {r["server"] for r in long_format_rows(CONFIG, [row])}
        assert servers == {"calendar"}


class TestValidationRoutesByDimension:
    """Two dimensions sharing a display label must not deadlock a page."""

    def test_duplicate_labels_do_not_leak_problems_across_steps(self):
        raw = minimal()
        raw["scale_labels"] = {"impact": "Score", "sensitivity": "Score", "blast": "Score"}
        config = load_config_from_dict(raw)
        server = config.enabled_servers[0]

        answers = {
            "impact": {server.key: {tool.name: 3 for tool in server.tools}},
            "sensitivity": {server.key: {}},
            "blast": {server.key: {}},
        }
        problems = missing_required(config, server, answers, dimension="impact")
        assert problems == [], problems

    def test_each_dimension_reports_only_its_own(self):
        server = CONFIG.enabled_servers[0]
        answers = {"impact": {}, "sensitivity": {}, "blast": {}}
        for dimension in ("impact", "sensitivity", "blast"):
            problems = missing_required(CONFIG, server, answers, dimension=dimension)
            assert len(problems) == 1, (dimension, problems)


class TestUnsureIsAvailableEverywhereItIsPromised:
    def test_the_intro_promises_not_sure(self):
        assert "Not sure" in CONFIG.intro

    def test_unsure_satisfies_a_blast_cell(self):
        server = CONFIG.enabled_servers[0]
        answers = {
            "impact": {server.key: {t.name: 3 for t in server.tools}},
            "sensitivity": {server.key: {a.name: 3 for a in server.assets}},
            "blast": {server.key: {cell: "unsure" for cell in server.live_blast_cells}},
        }
        assert missing_required(CONFIG, server, answers) == []

    def test_unsure_survives_into_the_row_without_becoming_a_number(self):
        server = CONFIG.enabled_servers[0]
        cell = server.live_blast_cells[0]
        answers = {
            "assigned_servers": [server.key],
            "impact": {server.key: {}},
            "sensitivity": {server.key: {}},
            "blast": {server.key: {cell: "unsure"}},
        }
        row = response_to_row(CONFIG, answers, submission_id="s", submitted_at="t")
        from survey.schema import blast_column

        assert row[blast_column(server.key, cell[0], cell[1])] == "unsure"
