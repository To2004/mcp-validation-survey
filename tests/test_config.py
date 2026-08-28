"""Tests for survey configuration loading and validation."""

import json
from pathlib import Path

import pytest

from survey.config import ConfigError, lint, load_config, load_config_from_dict

REPO_ROOT = Path(__file__).resolve().parents[1]


def minimal(**overrides) -> dict:
    raw = {
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
                "tools": [{"name": "get-event", "desc": "d"}],
                "assets": [{"name": "executive", "desc": "d"}],
                "blast": {
                    "tools": ["get-event"],
                    "assets": [{"name": "executive", "desc": "d"}],
                    "live": ["executive|get-event"],
                },
            }
        ],
    }
    raw.update(overrides)
    return raw


class TestValidation:
    def test_loads_a_well_formed_config(self):
        config = load_config_from_dict(minimal())
        assert config.servers[0].key == "calendar"
        assert config.enabled_servers[0].title == "Google Calendar"

    def test_rejects_config_with_no_enabled_server(self):
        raw = minimal()
        raw["servers"][0]["enabled"] = False
        with pytest.raises(ConfigError, match="at least one enabled server"):
            load_config_from_dict(raw)

    def test_rejects_duplicate_server_keys(self):
        raw = minimal()
        raw["servers"].append(dict(raw["servers"][0]))
        with pytest.raises(ConfigError, match="duplicate server key"):
            load_config_from_dict(raw)

    def test_rejects_names_containing_the_column_separator(self):
        raw = minimal()
        raw["servers"][0]["tools"][0]["name"] = "get__event"
        with pytest.raises(ConfigError, match="must not contain"):
            load_config_from_dict(raw)

    def test_rejects_blast_tool_not_in_the_tool_list(self):
        raw = minimal()
        raw["servers"][0]["blast"]["tools"] = ["ghost-tool"]
        with pytest.raises(ConfigError, match="not in the tool list"):
            load_config_from_dict(raw)

    def test_allows_blast_asset_outside_the_sensitivity_list_but_lints_it(self):
        # The v9 form genuinely rates a different asset set per step; rendering it
        # faithfully matters more than enforcing a subset the source does not have.
        raw = minimal()
        raw["servers"][0]["blast"]["assets"] = [{"name": "ghost-asset", "desc": "d"}]
        raw["servers"][0]["blast"]["live"] = ["ghost-asset|get-event"]
        config = load_config_from_dict(raw)
        warnings = lint(config)
        assert any("ghost-asset" in w and "never rated for Asset Sensitivity" in w for w in warnings)
        assert any("executive" in w and "never appear in the Blast Radius" in w for w in warnings)

    def test_a_consistent_config_lints_clean(self):
        assert lint(load_config_from_dict(minimal())) == []

    def test_rejects_scale_that_is_not_one_to_five(self):
        raw = minimal()
        raw["scales"]["impact"] = raw["scales"]["impact"][:3]
        with pytest.raises(ConfigError, match="1..5"):
            load_config_from_dict(raw)

    def test_rejects_missing_top_level_key(self):
        raw = minimal()
        del raw["consent"]
        with pytest.raises(ConfigError, match="consent"):
            load_config_from_dict(raw)


class TestShippedConfig:
    """The generated survey_config.json must stay loadable and match the v9 form."""

    @pytest.fixture
    def config(self):
        return load_config(REPO_ROOT / "survey_config.json")

    def test_shipped_config_is_valid(self, config):
        assert len(config.servers) == 5

    def test_server_shapes_match_the_source_form(self, config):
        shapes = {
            s.key: (len(s.tools), len(s.assets), len(s.blast_assets), len(s.blast_tools))
            for s in config.servers
        }
        # (tools, assets, blast assets, blast tools). Blast tools can be fewer
        # than tools: a tool reaching none of the chosen assets stays in Tool
        # Impact but would contribute a row of nothing but N/A to the matrix.
        assert shapes == {
            "calendar": (6, 7, 7, 5),
            "github": (6, 7, 7, 6),
            "slack": (6, 7, 7, 6),
            "filesystem": (6, 7, 7, 6),
            "sqlite": (5, 7, 7, 4),
        }

    def test_no_researcher_key_material_leaked_into_the_config(self):
        text = (REPO_ROOT / "survey_config.json").read_text(encoding="utf-8").lower()
        # Match the appendix's own markers, not the bare word "researcher" - asset
        # descriptions legitimately mention a project's lead researcher.
        for forbidden in (
            "researcher appendix",
            "researcher only",
            "researcher-only",
            "expected level",
            "five_level_v2",
            "do not send",
        ):
            assert forbidden not in text

    def test_live_cells_are_a_subset_of_the_matrix(self, config):
        # A server whose every pair is live is fine - SQL Database is one - so this
        # asserts containment, not strict containment.
        for server in config.servers:
            assert server.blast_live
            assert set(server.live_blast_cells) <= set(server.blast_cells)

    def test_most_of_each_matrix_is_answerable(self, config):
        # A grid that is mostly N/A wastes the screen and teaches nothing.
        for server in config.servers:
            live = len(server.live_blast_cells) / len(server.blast_cells)
            assert live >= 0.7, (server.key, round(live, 2))

    def test_dead_pairs_are_marked_not_live(self, config):
        calendar = next(s for s in config.servers if s.key == "calendar")
        assert calendar.is_live("team-calendar", "list-events")
        assert not calendar.is_live("holidays", "delete-event")

    def test_rejects_a_live_cell_outside_the_matrix(self):
        raw = minimal()
        raw["servers"][0]["blast"]["live"] = ["ghost|get-event"]
        with pytest.raises(ConfigError, match="not in the matrix"):
            load_config_from_dict(raw)

    def test_no_description_states_the_answer(self, config):
        """Descriptions must say what a thing is, never how bad it would be.

        A description that states a consequence ("revealing it early ruins the
        trial") or a reassurance ("No file contents") hands the participant the
        score, and the agreement statistic then measures reading rather than
        judgement. Independent review found this in 25 of 64 items.
        """
        banned = (
            "anyone can see it", "everyone can read it", "anyone can read them",
            "ruins the trial", "enough to get into another system",
            "there is no rollback", "nothing changes", "no file contents",
            "no cell values", "no columns, no rows", "nothing is merged yet",
            "leaves the rest untouched", "most sensitive file",
            "the people who can stop",
        )
        for server in config.servers:
            for item in list(server.tools) + list(server.assets):
                lowered = item.desc.lower()
                for phrase in banned:
                    assert phrase not in lowered, f"{server.key}/{item.name}: {phrase!r}"

    def test_no_description_is_a_placeholder(self, config):
        # "Whatever X acts on" gives a participant nothing to score.
        for server in config.servers:
            for item in list(server.tools) + list(server.assets):
                assert not item.desc.lower().startswith("whatever"), f"{server.key}/{item.name}"

    def test_every_item_has_a_description(self, config):
        for server in config.servers:
            assert all(t.desc for t in server.tools), server.key
            assert all(a.desc for a in server.assets), server.key
