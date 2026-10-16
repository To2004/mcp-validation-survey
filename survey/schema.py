"""Map a completed survey response onto the analysis CSV.

Two shapes are produced from the same submission:

* **wide** — one row per participant, one column per rating. This is the on-disk
  format, and the one to open in Excel or `pandas.read_csv`.
* **long** — one record per rating, produced on demand for the researcher. This is
  the shape that joins cleanly against the scanner's own per-tool/per-asset output.

Every rating a participant makes is 1-5. Blast Radius cells the scanner marks as
non-existent are fixed at N/A and shown read-only, so participants score only the
tool/asset pairs that actually exist.

Each participant rates a balanced subset of the servers, not all of them, so the
columns of the servers they were not assigned are blank. `assigned_servers` records
which ones they saw - always read it before treating a blank as missing data.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from survey.assignment import format_assigned, parse_assigned
from survey.config import COLUMN_SEPARATOR, INPUTS_STEP, Server, SurveyConfig

NOT_APPLICABLE = "N/A"
# A participant who cannot judge an item says so, rather than guessing. This is an
# answer in its own right: a tool or asset that many people cannot place is a
# finding about the definitions, which a forced guess would hide.
UNSURE = "unsure"

METADATA_COLUMNS = (
    "submission_id",
    "submitted_at_utc",
    "participant_id",
    "email",
    "familiarity_llm_agents",
    "familiarity_mcp",
    "consent",
    "assigned_servers",
    "duration_seconds",
)
FEEDBACK_COLUMNS = ("ambiguity_notes", "comments", "confidence")

# Answers to the "which inputs change the risk" step. Not sure is UNSURE, as elsewhere.
INPUT_CHANGES = "changes"
INPUT_NO_CHANGE = "no_change"
INPUT_VALUES = (INPUT_CHANGES, INPUT_NO_CHANGE, UNSURE)
#: The rating steps in page order, for the per-page time columns.
STEP_ORDER = ("impact", "sensitivity", "blast", INPUTS_STEP)


def impact_column(server_key: str, tool: str) -> str:
    return COLUMN_SEPARATOR.join(("impact", server_key, tool))


def sensitivity_column(server_key: str, asset: str) -> str:
    return COLUMN_SEPARATOR.join(("sens", server_key, asset))


def blast_column(server_key: str, asset: str, tool: str) -> str:
    return COLUMN_SEPARATOR.join(("blast", server_key, asset, tool))


def input_column(server_key: str, tool: str, input_name: str) -> str:
    return COLUMN_SEPARATOR.join(("input", server_key, tool, input_name))


def server_steps(server: Server) -> list[str]:
    """The rating steps this server's section has: the inputs step only if it lists inputs."""
    return [step for step in STEP_ORDER if step != INPUTS_STEP or server.inputs]


def page_id(kind: str, server_key: str | None = None) -> str:
    """A stable name for one wizard page: `intro`, `feedback` or `<server>__<step>`."""
    return kind if server_key is None else COLUMN_SEPARATOR.join((server_key, kind))


def seconds_column(page: str) -> str:
    return COLUMN_SEPARATOR.join(("seconds", page))


def server_columns(server: Server) -> list[str]:
    """Every rating column contributed by one server section, in question order."""
    columns = [impact_column(server.key, tool.name) for tool in server.tools]
    columns += [sensitivity_column(server.key, asset.name) for asset in server.assets]
    columns += [blast_column(server.key, asset, tool) for asset, tool in server.blast_cells]
    columns += [input_column(server.key, item.tool, item.input) for item in server.inputs]
    return columns


def timing_columns(config: SurveyConfig) -> list[str]:
    """Seconds spent on each page, in page order. Pages a participant never saw are blank."""
    pages = [page_id("intro")]
    for server in config.enabled_servers:
        pages += [page_id(step, server.key) for step in server_steps(server)]
    pages.append(page_id("feedback"))
    return [seconds_column(page) for page in pages]


def csv_columns(config: SurveyConfig) -> list[str]:
    """Full ordered column list for the wide CSV. Disabled servers contribute nothing."""
    columns = list(METADATA_COLUMNS)
    for server in config.enabled_servers:
        columns += server_columns(server)
    columns += timing_columns(config)
    columns += list(FEEDBACK_COLUMNS)
    return columns


def _rating(value: Any) -> Any:
    """Normalise a rating to an int, "unsure", or empty string when unanswered."""
    if value is None or value == "":
        return ""
    if value == UNSURE:
        return UNSURE
    return int(value)


def _choice(value: Any) -> str:
    """An inputs-step answer as stored, or empty string when unanswered."""
    return str(value) if value in INPUT_VALUES else ""


def response_to_row(
    config: SurveyConfig,
    answers: dict[str, Any],
    *,
    submission_id: str,
    submitted_at: str,
) -> dict[str, Any]:
    """Flatten one participant's answers into a single wide CSV row."""
    row: dict[str, Any] = {
        "submission_id": submission_id,
        "submitted_at_utc": submitted_at,
        "participant_id": (answers.get("participant_id") or "").strip(),
        "email": (answers.get("email") or "").strip(),
        "familiarity_llm_agents": _rating(answers.get("familiarity_llm_agents")),
        "familiarity_mcp": _rating(answers.get("familiarity_mcp")),
        "consent": "yes" if answers.get("consent") else "no",
        "assigned_servers": format_assigned(parse_assigned(answers.get("assigned_servers"))),
        "duration_seconds": _rating(answers.get("duration_seconds")),
    }

    impact = answers.get("impact", {})
    sensitivity = answers.get("sensitivity", {})
    blast = answers.get("blast", {})
    inputs = answers.get(INPUTS_STEP, {})
    assigned = set(parse_assigned(answers.get("assigned_servers")))

    for server in config.enabled_servers:
        if server.key not in assigned:
            # Not shown to this participant: leave every column blank rather than
            # inventing a value. `assigned_servers` says why.
            for column in server_columns(server):
                row[column] = ""
            continue
        for tool in server.tools:
            row[impact_column(server.key, tool.name)] = _rating(
                impact.get(server.key, {}).get(tool.name)
            )
        for asset in server.assets:
            row[sensitivity_column(server.key, asset.name)] = _rating(
                sensitivity.get(server.key, {}).get(asset.name)
            )
        for asset, tool in server.blast_cells:
            if not server.is_live(asset, tool):
                row[blast_column(server.key, asset, tool)] = NOT_APPLICABLE
                continue
            row[blast_column(server.key, asset, tool)] = _rating(
                blast.get(server.key, {}).get((asset, tool))
            )
        for item in server.inputs:
            row[input_column(server.key, item.tool, item.input)] = _choice(
                inputs.get(server.key, {}).get((item.tool, item.input))
            )

    seconds = answers.get("page_seconds", {})
    for column in timing_columns(config):
        page = column.split(COLUMN_SEPARATOR, 1)[1]
        row[column] = int(seconds[page]) if page in seconds else ""
    row["ambiguity_notes"] = (answers.get("ambiguity_notes") or "").strip()
    row["comments"] = (answers.get("comments") or "").strip()
    row["confidence"] = _rating(answers.get("confidence"))
    return row


def long_format_rows(
    config: SurveyConfig, rows: Iterable[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Explode wide rows into one record per rating, ready to join with scanner output."""
    records: list[dict[str, Any]] = []
    for row in rows:
        base = {
            "submission_id": row.get("submission_id", ""),
            "participant_id": row.get("participant_id", ""),
        }
        # Only the servers this participant was assigned produced ratings; emitting
        # empty records for the others would pad the long export with non-answers.
        #
        # A row with no assignment recorded predates that column. Falling back to
        # every enabled server keeps it in the export: returning nothing for it
        # loses the response silently, which is far worse than a few blank cells.
        covered = assigned_servers(config, row) or list(config.enabled_servers)
        for server in covered:
            for tool in server.tools:
                records.append(
                    {
                        **base,
                        "dimension": "impact",
                        "server": server.key,
                        "asset": "",
                        "tool": tool.name,
                        "value": row.get(impact_column(server.key, tool.name), ""),
                    }
                )
            for asset in server.assets:
                records.append(
                    {
                        **base,
                        "dimension": "sensitivity",
                        "server": server.key,
                        "asset": asset.name,
                        "tool": "",
                        "value": row.get(sensitivity_column(server.key, asset.name), ""),
                    }
                )
            for asset, tool in server.blast_cells:
                records.append(
                    {
                        **base,
                        "dimension": "blast",
                        "server": server.key,
                        "asset": asset,
                        "tool": tool,
                        "value": row.get(blast_column(server.key, asset, tool), ""),
                    }
                )
            # The inputs step: `asset` holds the input's name, `tool` its tool.
            for item in server.inputs:
                records.append(
                    {
                        **base,
                        "dimension": INPUTS_STEP,
                        "server": server.key,
                        "asset": item.input,
                        "tool": item.tool,
                        "value": row.get(input_column(server.key, item.tool, item.input), ""),
                    }
                )
    return records


def assigned_servers(config: SurveyConfig, row: dict[str, Any]) -> list[Server]:
    """The servers a stored response actually covers."""
    keys = set(parse_assigned(row.get("assigned_servers")))
    return [server for server in config.enabled_servers if server.key in keys]


def missing_required(
    config: SurveyConfig,
    server: Server,
    answers: dict[str, Any],
    dimension: str | None = None,
) -> list[str]:
    """Human-readable list of what is still unanswered in one server section.

    Only live cells are required; read-only N/A cells are not. "Not sure" counts as
    answered, exactly as it does on the other two steps - the intro promises the
    option on every question, so the matrix must honour it too. The count is
    reported rather than the cell names, since a matrix has up to 42 of them.
    """
    labels = getattr(config, "scale_labels", {})
    impact_label = labels.get("impact", "Action Impact")
    sensitivity_label = labels.get("sensitivity", "Asset Confidentiality")
    blast_label = labels.get("blast", "Consequence Scope")

    problems: list[str] = []

    if dimension in (None, "impact"):
        impact = answers.get("impact", {}).get(server.key, {})
        unrated_tools = [tool.name for tool in server.tools if impact.get(tool.name) in (None, "")]
        if unrated_tools:
            problems.append(f"{impact_label}: " + ", ".join(unrated_tools))

    if dimension in (None, "sensitivity"):
        sensitivity = answers.get("sensitivity", {}).get(server.key, {})
        unrated_assets = [
            asset.name for asset in server.assets if sensitivity.get(asset.name) in (None, "")
        ]
        if unrated_assets:
            problems.append(f"{sensitivity_label}: " + ", ".join(unrated_assets))

    if dimension in (None, INPUTS_STEP):
        chosen = answers.get(INPUTS_STEP, {}).get(server.key, {})
        unanswered = [f"{item.tool}.{item.input}" for item in server.inputs
                      if chosen.get((item.tool, item.input)) in (None, "")]
        if unanswered:
            label = labels.get(INPUTS_STEP, "Inputs That Change the Risk")
            problems.append(f"{label}: " + ", ".join(unanswered))

    if dimension not in (None, "blast"):
        return problems

    blast = answers.get("blast", {}).get(server.key, {})
    unrated_cells = [cell for cell in server.live_blast_cells if blast.get(cell) in (None, "")]
    if unrated_cells:
        total = len(server.live_blast_cells)
        problems.append(
            f"{blast_label}: {len(unrated_cells)} of {total} tool/asset cells are not yet rated"
        )
    return problems


def rows_to_csv(columns: Sequence[str], rows: Iterable[dict[str, Any]]) -> str:
    """Render rows as CSV text with a stable column order."""
    import csv
    import io

    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=list(columns), extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return buffer.getvalue()
