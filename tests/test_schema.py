"""Tests for the response -> CSV row mapping."""

import pytest

from survey.config import SurveyConfig, load_config_from_dict
from survey.schema import (
    blast_column,
    csv_columns,
    impact_column,
    long_format_rows,
    response_to_row,
    sensitivity_column,
)


@pytest.fixture
def config() -> SurveyConfig:
    return load_config_from_dict(
        {
            "title": "T",
            "subtitle": "S",
            "intro": "I",
            "consent": "C",
            "scales": {
                "impact": [{"value": n, "label": f"L{n}", "meaning": "m"} for n in range(1, 6)],
                "sensitivity": [{"value": n, "label": f"L{n}", "meaning": "m"} for n in range(1, 6)],
                "blast": [{"value": n, "label": f"L{n}", "meaning": "m"} for n in range(1, 6)],
            },
            "step_prompts": {"impact": "a", "sensitivity": "b", "blast": "c"},
            "servers": [
                {
                    "key": "calendar",
                    "title": "Google Calendar",
                    "enabled": True,
                    "scenario": "sc",
                    "tools": [
                        {"name": "get-event", "desc": "d"},
                        {"name": "delete-event", "desc": "d"},
                    ],
                    "assets": [
                        {"name": "executive", "desc": "d"},
                        {"name": "personal", "desc": "d"},
                    ],
                    "blast": {
                        "tools": ["get-event", "delete-event"],
                        "assets": [{"name": "executive", "desc": "d"}],
                    },
                },
                {
                    "key": "github",
                    "title": "GitHub",
                    "enabled": False,
                    "scenario": "sc",
                    "tools": [{"name": "list_commits", "desc": "d"}],
                    "assets": [{"name": "internal-docs", "desc": "d"}],
                    "blast": {
                        "tools": ["list_commits"],
                        "assets": [{"name": "internal-docs", "desc": "d"}],
                    },
                },
            ],
        }
    )


@pytest.fixture
def answers() -> dict:
    return {
        "participant_id": "P01",
        "email": "a@b.c",
        "familiarity_llm_agents": 4,
        "familiarity_mcp": 3,
        "consent": True,
        "impact": {"calendar": {"get-event": 3, "delete-event": 5}},
        "sensitivity": {"calendar": {"executive": 4, "personal": 3}},
        "blast": {"calendar": {("executive", "get-event"): 2, ("executive", "delete-event"): 4}},
        "ambiguity_notes": "none",
        "comments": "",
        "confidence": 4,
    }


class TestColumnNames:
    def test_column_names_are_stable_and_prefixed(self):
        assert impact_column("calendar", "get-event") == "impact__calendar__get-event"
        assert sensitivity_column("calendar", "executive") == "sens__calendar__executive"
        assert (
            blast_column("calendar", "executive", "get-event")
            == "blast__calendar__executive__get-event"
        )

    def test_columns_cover_only_enabled_servers(self, config):
        columns = csv_columns(config)
        assert "impact__calendar__get-event" in columns
        assert not any(c.endswith("__github__list_commits") for c in columns)

    def test_metadata_columns_come_first(self, config):
        columns = csv_columns(config)
        assert columns[0] == "submission_id"
        assert columns.index("participant_id") < columns.index("impact__calendar__get-event")

    def test_free_text_and_confidence_are_last(self, config):
        columns = csv_columns(config)
        assert columns[-3:] == ["ambiguity_notes", "comments", "confidence"]

    def test_no_duplicate_columns(self, config):
        columns = csv_columns(config)
        assert len(columns) == len(set(columns))


class TestResponseToRow:
    def test_row_has_exactly_the_declared_columns(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="2026-08-24T10:00:00Z")
        assert list(row.keys()) == csv_columns(config)

    def test_ratings_are_written_as_integers(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        assert row["impact__calendar__delete-event"] == 5
        assert row["sens__calendar__executive"] == 4
        assert row["blast__calendar__executive__get-event"] == 2

    def test_unrated_blast_cell_is_written_as_blank(self, config, answers):
        # The matrix has no N/A option, so a blank can only mean "not answered".
        answers["blast"]["calendar"].pop(("executive", "delete-event"))
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        assert row["blast__calendar__executive__delete-event"] == ""

    def test_blast_values_are_written_as_integers(self, config, answers):
        answers["blast"]["calendar"][("executive", "get-event")] = "5"
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        assert row["blast__calendar__executive__get-event"] == 5

    def test_consent_is_written_as_boolean_word(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        assert row["consent"] == "yes"

    def test_missing_optional_email_becomes_empty_string(self, config, answers):
        answers["email"] = None
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        assert row["email"] == ""

    def test_identifiers_are_carried_through(self, config, answers):
        row = response_to_row(config, answers, submission_id="abc", submitted_at="2026-01-01T00:00:00Z")
        assert row["submission_id"] == "abc"
        assert row["submitted_at_utc"] == "2026-01-01T00:00:00Z"
        assert row["participant_id"] == "P01"


class TestLongFormat:
    def test_one_record_per_rating(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        records = long_format_rows(config, [row])
        # 2 impact + 2 sensitivity + 2 blast cells
        assert len(records) == 6

    def test_records_carry_dimension_server_target_and_value(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        records = long_format_rows(config, [row])
        blast = [r for r in records if r["dimension"] == "blast"]
        assert {
            "submission_id": "s1",
            "participant_id": "P01",
            "dimension": "blast",
            "server": "calendar",
            "asset": "executive",
            "tool": "get-event",
            "value": 2,
        } in blast

    def test_impact_records_have_no_asset(self, config, answers):
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        impact = [r for r in long_format_rows(config, [row]) if r["dimension"] == "impact"]
        assert all(r["asset"] == "" for r in impact)
        assert {r["tool"] for r in impact} == {"get-event", "delete-event"}

    def test_every_blast_cell_appears_even_when_unanswered(self, config, answers):
        answers["blast"]["calendar"].pop(("executive", "get-event"))
        row = response_to_row(config, answers, submission_id="s1", submitted_at="t")
        blast = [r for r in long_format_rows(config, [row]) if r["dimension"] == "blast"]
        assert len(blast) == 2
        assert [r for r in blast if r["value"] == ""]
