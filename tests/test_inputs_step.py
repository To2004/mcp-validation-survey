"""Tests for the "which inputs change the risk" step and the per-page times: config,
CSV columns and storage. The app itself is covered in tests/test_app.py."""

from pathlib import Path

import pytest

from survey.config import ConfigError, load_config, load_config_from_dict
from survey.schema import (
    csv_columns,
    long_format_rows,
    missing_required,
    response_to_row,
    timing_columns,
)
from survey.storage import parse_rating_column, rating_payloads
from tests.test_config import minimal

CONFIG = load_config(Path(__file__).resolve().parents[1] / "survey_config.json")

ROW = {"tool": "create-event", "tool_desc": "Creates an event.", "input": "start",
       "desc": "When the event starts", "examples": ["10:00", "05:00"]}


def with_inputs(rows, **extra) -> dict:
    raw = minimal(**extra)
    raw["servers"][0]["inputs"] = rows
    raw["step_prompts"]["inputs"] = "Which inputs change the risk?"
    raw["input_choices"] = {"changes": "Changes", "no_change": "No change"}
    return raw


class TestConfig:
    def test_every_server_asks_about_five_inputs_with_two_examples(self):
        for server in CONFIG.enabled_servers:
            assert len(server.inputs) == 5, server.key
            assert all(len(item.examples) == 2 for item in server.inputs)

    def test_inputs_parse_and_group_by_tool(self):
        config = load_config_from_dict(with_inputs([ROW, {**ROW, "input": "timeZone"}]))
        server = config.servers[0]
        assert [i.input for i in server.inputs] == ["start", "timeZone"]
        assert server.input_tools == [("create-event", "Creates an event.")]

    def test_one_example_is_rejected(self):
        with pytest.raises(ConfigError, match="examples"):
            load_config_from_dict(with_inputs([{**ROW, "examples": ["10:00"]}]))

    def test_the_same_input_twice_is_rejected(self):
        with pytest.raises(ConfigError, match="twice"):
            load_config_from_dict(with_inputs([ROW, ROW]))

    def test_inputs_need_a_prompt_and_answer_labels(self):
        raw = with_inputs([ROW])
        del raw["input_choices"]
        with pytest.raises(ConfigError, match="input_choices"):
            load_config_from_dict(raw)

    def test_a_config_without_inputs_still_loads(self):
        assert load_config_from_dict(minimal()).servers[0].inputs == ()


class TestColumns:
    def test_each_input_has_a_column_and_each_page_a_time(self):
        columns = csv_columns(CONFIG)
        assert "input__calendar__create-event__timeZone" in columns
        assert "seconds__intro" in columns and "seconds__calendar__inputs" in columns
        assert columns.index("seconds__feedback") < columns.index("ambiguity_notes")

    def test_answers_and_seconds_are_written_and_unknown_values_are_blank(self):
        server = CONFIG.enabled_servers[0]
        first, second = server.inputs[0], server.inputs[1]
        answers = {"assigned_servers": [server.key], "page_seconds": {"intro": 41.7},
                   "inputs": {server.key: {(first.tool, first.input): "changes",
                                           (second.tool, second.input): "maybe"}}}
        row = response_to_row(CONFIG, answers, submission_id="s", submitted_at="t")
        assert row[f"input__{server.key}__{first.tool}__{first.input}"] == "changes"
        assert row[f"input__{server.key}__{second.tool}__{second.input}"] == ""
        assert row["seconds__intro"] == 41
        assert row["seconds__feedback"] == ""

    def test_the_long_export_puts_the_input_in_asset_and_its_tool_in_tool(self):
        server = CONFIG.enabled_servers[0]
        item = server.inputs[0]
        row = {"submission_id": "s", "assigned_servers": server.key,
               f"input__{server.key}__{item.tool}__{item.input}": "no_change"}
        records = [r for r in long_format_rows(CONFIG, [row]) if r["dimension"] == "inputs"]
        assert len(records) == len(server.inputs)
        assert records[0]["asset"] == item.input and records[0]["tool"] == item.tool
        assert records[0]["value"] == "no_change"

    def test_unanswered_inputs_are_reported_and_not_sure_counts(self):
        server = CONFIG.enabled_servers[0]
        problems = missing_required(CONFIG, server, {}, dimension="inputs")
        assert problems and server.inputs[0].input in problems[0]
        answers = {"inputs": {server.key: {(i.tool, i.input): "unsure" for i in server.inputs}}}
        assert missing_required(CONFIG, server, answers, dimension="inputs") == []

    def test_timing_columns_follow_the_page_order(self):
        columns = timing_columns(CONFIG)
        assert columns[0] == "seconds__intro" and columns[-1] == "seconds__feedback"


class TestStorage:
    def test_an_input_column_parses_with_the_input_as_asset(self):
        assert parse_rating_column("input__github__create_pull_request__base") == (
            "inputs", "github", "base", "create_pull_request")

    def test_seconds_columns_are_metadata_not_ratings(self):
        assert parse_rating_column("seconds__github__impact") is None

    def test_an_input_answer_has_no_number(self):
        payload = rating_payloads({"submission_id": "s",
                                   "input__github__create_pull_request__base": "changes"})
        assert payload == [{"submission_id": "s", "dimension": "inputs", "server": "github",
                            "asset": "base", "tool": "create_pull_request", "value": "changes",
                            "value_num": None}]
