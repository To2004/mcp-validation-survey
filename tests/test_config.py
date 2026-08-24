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
        assert shapes == {
            "calendar": (7, 6, 5, 6),  # get-current-time acts on nothing, so it is not in the matrix
            "github": (7, 6, 5, 7),
            "slack": (7, 6, 5, 7),
            "filesystem": (7, 6, 5, 7),
            "sqlite": (5, 6, 5, 5),
        }

    def test_no_researcher_key_material_leaked_into_the_config(self):
        text = (REPO_ROOT / "survey_config.json").read_text(encoding="utf-8").lower()
        for forbidden in ("researcher", "expected level", "five_level_v2", "do not send"):
            assert forbidden not in text

    def test_live_cells_are_a_strict_subset_of_the_matrix(self, config):
        for server in config.servers:
            assert server.blast_live
            assert set(server.live_blast_cells) <= set(server.blast_cells)
            assert len(server.live_blast_cells) < len(server.blast_cells)

    def test_dead_pairs_are_marked_not_live(self, config):
        calendar = next(s for s in config.servers if s.key == "calendar")
        assert calendar.is_live("executive", "get-event")
        assert not calendar.is_live("free-busy-availability", "delete-event")

    def test_rejects_a_live_cell_outside_the_matrix(self):
        raw = minimal()
        raw["servers"][0]["blast"]["live"] = ["ghost|get-event"]
        with pytest.raises(ConfigError, match="not in the matrix"):
            load_config_from_dict(raw)

    def test_every_item_has_a_description(self, config):
        for server in config.servers:
            assert all(t.desc for t in server.tools), server.key
            assert all(a.desc for a in server.assets), server.key
