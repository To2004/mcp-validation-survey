"""Load and validate the survey definition.

The survey is data, not code: `survey_config.json` is generated from the source
Word form and drives every question the app renders. Validation is strict and
happens at load time so a malformed config fails on startup rather than halfway
through a participant's session.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

COLUMN_SEPARATOR = "__"

_REQUIRED_TOP_LEVEL = ("title", "subtitle", "intro", "consent", "scales", "step_prompts", "servers")
_DIMENSIONS = ("impact", "sensitivity", "blast")
#: The step that asks which tool inputs can change the risk. It has no 1-5 scale and
#: is shown only for servers whose config lists `inputs`.
INPUTS_STEP = "inputs"
#: Example values shown next to each input, so a participant sees what it holds.
INPUT_EXAMPLES = 2


class ConfigError(ValueError):
    """Raised when the survey definition is malformed."""


@dataclass(frozen=True)
class Item:
    """A rateable thing: one MCP tool, or one virtual asset."""

    name: str
    desc: str


@dataclass(frozen=True)
class Level:
    """One rung of a 1-5 rating scale."""

    value: int
    label: str
    meaning: str
    examples: tuple[str, ...] = ()

    @property
    def heading(self) -> str:
        return f"{self.value} — {self.label}"


@dataclass(frozen=True)
class InputItem:
    """One input of one tool, asked about in the "which inputs change the risk" step."""

    tool: str
    tool_desc: str
    input: str
    desc: str
    examples: tuple[str, ...]


@dataclass(frozen=True)
class Server:
    """One MCP server section: three rating steps over its tools and assets, and an
    optional fourth asking which tool inputs can change the risk."""

    key: str
    title: str
    enabled: bool
    scenario: str      # what this deployment means to the organisation
    mcp_context: str   # what the server itself exposes, independent of any org
    tools: tuple[Item, ...]
    assets: tuple[Item, ...]
    blast_tools: tuple[str, ...]
    blast_assets: tuple[Item, ...]
    blast_live: frozenset[tuple[str, str]]
    inputs: tuple[InputItem, ...] = ()

    @property
    def input_tools(self) -> list[tuple[str, str]]:
        """(tool, tool description) for each tool with inputs, in config order."""
        seen: dict[str, str] = {}
        for item in self.inputs:
            seen.setdefault(item.tool, item.tool_desc)
        return list(seen.items())

    @property
    def blast_cells(self) -> list[tuple[str, str]]:
        """Every (asset, tool) pair in this server's Blast Radius matrix."""
        return [(asset.name, tool) for asset in self.blast_assets for tool in self.blast_tools]

    def is_live(self, asset: str, tool: str) -> bool:
        """Whether this tool actually acts on this asset.

        Dead pairs are fixed at N/A and shown read-only, so participants rate only
        the pairs that exist on the asset register.
        """
        return (asset, tool) in self.blast_live

    @property
    def live_blast_cells(self) -> list[tuple[str, str]]:
        return [cell for cell in self.blast_cells if cell in self.blast_live]


@dataclass(frozen=True)
class SurveyConfig:
    title: str
    subtitle: str
    intro: str
    consent: str
    scales: dict[str, tuple[Level, ...]]
    step_prompts: dict[str, str]
    servers: tuple[Server, ...]
    servers_per_participant: int
    scale_labels: dict[str, str]
    scale_rules: dict[str, tuple[str, ...]]
    input_choices: dict[str, str] | None = None
    show_timer: bool = True

    @property
    def enabled_servers(self) -> tuple[Server, ...]:
        return tuple(s for s in self.servers if s.enabled)


def _require(raw: dict[str, Any], key: str, where: str) -> Any:
    if key not in raw:
        raise ConfigError(f"{where}: missing required key {key!r}")
    return raw[key]


def _check_name(name: str, where: str) -> str:
    if not name or not name.strip():
        raise ConfigError(f"{where}: name must not be empty")
    if COLUMN_SEPARATOR in name:
        raise ConfigError(
            f"{where}: name {name!r} must not contain {COLUMN_SEPARATOR!r}, "
            "which separates CSV column parts"
        )
    return name


def _parse_items(raw: Sequence[dict[str, Any]], where: str) -> tuple[Item, ...]:
    items = tuple(
        Item(name=_check_name(_require(entry, "name", where), where), desc=entry.get("desc", ""))
        for entry in raw
    )
    names = [item.name for item in items]
    if len(names) != len(set(names)):
        raise ConfigError(f"{where}: duplicate item names")
    return items


def _parse_scale(raw: Sequence[dict[str, Any]], where: str) -> tuple[Level, ...]:
    levels = tuple(
        Level(
            value=int(_require(entry, "value", where)),
            label=_require(entry, "label", where),
            meaning=entry.get("meaning", ""),
            examples=tuple(entry.get("examples", ())),
        )
        for entry in raw
    )
    if [level.value for level in levels] != [1, 2, 3, 4, 5]:
        raise ConfigError(f"{where}: scale must be exactly the levels 1..5, in order")
    return levels


def _parse_inputs(raw: Sequence[dict[str, Any]], where: str) -> tuple[InputItem, ...]:
    """The `inputs` rows of one server: each a tool, an input of it and example values."""
    items = []
    for entry in raw:
        tool = _check_name(_require(entry, "tool", where), f"{where} tool")
        name = _check_name(_require(entry, "input", where), f"{where} input")
        examples = tuple(str(e) for e in _require(entry, "examples", where))
        if len(examples) != INPUT_EXAMPLES:
            raise ConfigError(f"{where}: {tool}.{name} needs exactly {INPUT_EXAMPLES} examples")
        items.append(InputItem(tool=tool, tool_desc=entry.get("tool_desc", ""), input=name,
                               desc=_require(entry, "desc", where), examples=examples))
    pairs = [(item.tool, item.input) for item in items]
    if len(pairs) != len(set(pairs)):
        raise ConfigError(f"{where}: an input is listed twice for the same tool")
    return tuple(items)


def _parse_server(raw: dict[str, Any]) -> Server:
    key = _check_name(_require(raw, "key", "server"), "server key")
    where = f"server {key!r}"
    tools = _parse_items(_require(raw, "tools", where), f"{where} tools")
    assets = _parse_items(_require(raw, "assets", where), f"{where} assets")

    blast = _require(raw, "blast", where)
    blast_tools = tuple(_check_name(name, f"{where} blast tools") for name in blast.get("tools", []))
    blast_assets = _parse_items(blast.get("assets", []), f"{where} blast assets")

    tool_names = {tool.name for tool in tools}
    for name in blast_tools:
        if name not in tool_names:
            raise ConfigError(f"{where}: blast tool {name!r} is not in the tool list")

    cells = {(asset.name, tool) for asset in blast_assets for tool in blast_tools}
    blast_live = set()
    for entry in blast.get("live", []):
        asset, _, tool = str(entry).partition("|")
        if (asset, tool) not in cells:
            raise ConfigError(
                f"{where}: live blast cell {entry!r} is not in the matrix"
            )
        blast_live.add((asset, tool))

    # Blast assets are deliberately NOT required to be a subset of the sensitivity
    # assets: the v9 form rates a different asset set in each step. That mismatch is
    # reported by `lint()` rather than rejected here, so the app renders the form as
    # written. See docs/known-issues.md.

    return Server(
        key=key,
        title=_require(raw, "title", where),
        enabled=bool(raw.get("enabled", True)),
        scenario=raw.get("scenario", ""),
        mcp_context=raw.get("mcp_context", ""),
        tools=tools,
        assets=assets,
        blast_tools=blast_tools,
        blast_assets=blast_assets,
        blast_live=frozenset(blast_live),
        inputs=_parse_inputs(raw.get("inputs", []), f"{where} inputs"),
    )


def load_config_from_dict(raw: dict[str, Any]) -> SurveyConfig:
    """Validate a raw config mapping and return an immutable SurveyConfig."""
    for key in _REQUIRED_TOP_LEVEL:
        _require(raw, key, "config")

    scales_raw = raw["scales"]
    scales = {dim: _parse_scale(_require(scales_raw, dim, "scales"), f"scale {dim!r}") for dim in _DIMENSIONS}

    prompts_raw = raw["step_prompts"]
    prompts = {dim: _require(prompts_raw, dim, "step_prompts") for dim in _DIMENSIONS}

    servers = tuple(_parse_server(entry) for entry in raw["servers"])
    keys = [server.key for server in servers]
    if len(keys) != len(set(keys)):
        raise ConfigError("config: duplicate server key")
    if not any(server.enabled for server in servers):
        raise ConfigError("config: at least one enabled server is required")

    choices = raw.get("input_choices")
    if any(server.inputs for server in servers):
        _require(prompts_raw, INPUTS_STEP, "step_prompts")
        if not (isinstance(choices, dict) and {"changes", "no_change"} <= set(choices)):
            raise ConfigError("config: input_choices needs the labels 'changes' and 'no_change'")
        prompts[INPUTS_STEP] = prompts_raw[INPUTS_STEP]

    per_participant = int(raw.get("servers_per_participant", len(servers)))
    if per_participant < 1:
        raise ConfigError("config: servers_per_participant must be at least 1")

    return SurveyConfig(
        title=raw["title"],
        subtitle=raw["subtitle"],
        intro=raw["intro"],
        consent=raw["consent"],
        scales=scales,
        step_prompts=prompts,
        servers=servers,
        servers_per_participant=per_participant,
        scale_labels=dict(raw.get("scale_labels", {})),
        scale_rules={
            dim: tuple(rules) for dim, rules in raw.get("scale_rules", {}).items()
        },
        input_choices=dict(choices) if isinstance(choices, dict) else None,
        show_timer=bool(raw.get("show_timer", True)),
    )


def lint(config: SurveyConfig) -> list[str]:
    """Non-fatal consistency warnings about the survey design itself.

    These are properties of the source form, not of the app. They are surfaced in the
    researcher panel so the analysis is not built on an assumption the data cannot support.
    """
    warnings: list[str] = []
    for server in config.servers:
        rated = {asset.name for asset in server.assets}
        in_matrix = {asset.name for asset in server.blast_assets}
        only_matrix = sorted(in_matrix - rated)
        # The matrix samples 4 of the rated assets on purpose, so a rated asset left
        # out of it is not a warning; a matrix asset that is never rated still is.
        if only_matrix:
            warnings.append(
                f"{server.title}: {len(only_matrix)} asset(s) appear in the Blast Radius "
                f"matrix but are never rated for Asset Sensitivity — "
                f"{', '.join(only_matrix)}. No sensitivity x blast pairing is possible for them."
            )
    return warnings


def load_config(path: str | Path) -> SurveyConfig:
    """Read and validate the survey definition at `path`."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"survey config not found at {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"survey config at {path} is not valid JSON: {exc}") from exc
    return load_config_from_dict(raw)
