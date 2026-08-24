"""Map a completed survey response onto the analysis CSV.

Two shapes are produced from the same submission:

* **wide** — one row per participant, one column per rating. This is the on-disk
  format, and the one to open in Excel or `pandas.read_csv`.
* **long** — one record per rating, produced on demand for the researcher. This is
  the shape that joins cleanly against the scanner's own per-tool/per-asset output.
"""

from __future__ import annotations

from typing import Any, Iterable, Sequence

from survey.config import COLUMN_SEPARATOR, Server, SurveyConfig

NOT_APPLICABLE = "N/A"

METADATA_COLUMNS = (
    "submission_id",
    "submitted_at_utc",
    "participant_id",
    "email",
    "familiarity_llm_agents",
    "familiarity_mcp",
    "consent",
    "duration_seconds",
)
FEEDBACK_COLUMNS = ("ambiguity_notes", "comments", "confidence")


def impact_column(server_key: str, tool: str) -> str:
    return COLUMN_SEPARATOR.join(("impact", server_key, tool))


def sensitivity_column(server_key: str, asset: str) -> str:
    return COLUMN_SEPARATOR.join(("sens", server_key, asset))


def blast_column(server_key: str, asset: str, tool: str) -> str:
    return COLUMN_SEPARATOR.join(("blast", server_key, asset, tool))


def server_columns(server: Server) -> list[str]:
    """Every rating column contributed by one server section, in question order."""
    columns = [impact_column(server.key, tool.name) for tool in server.tools]
    columns += [sensitivity_column(server.key, asset.name) for asset in server.assets]
    columns += [blast_column(server.key, asset, tool) for asset, tool in server.blast_cells]
    return columns


def csv_columns(config: SurveyConfig) -> list[str]:
    """Full ordered column list for the wide CSV. Disabled servers contribute nothing."""
    columns = list(METADATA_COLUMNS)
    for server in config.enabled_servers:
        columns += server_columns(server)
    columns += list(FEEDBACK_COLUMNS)
    return columns


def _rating(value: Any) -> Any:
    """Normalise a rating to an int, or empty string when unanswered."""
    if value is None or value == "":
        return ""
    return int(value)


def _blast_rating(value: Any) -> Any:
    """Blast cells are 1-5 or the explicit N/A marker; an unset cell means N/A.

    An unscored pair is a finding, not a gap, so it is recorded rather than blanked.
    """
    if value is None or value == "" or value == NOT_APPLICABLE:
        return NOT_APPLICABLE
    return int(value)


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
        "duration_seconds": _rating(answers.get("duration_seconds")),
    }

    impact = answers.get("impact", {})
    sensitivity = answers.get("sensitivity", {})
    blast = answers.get("blast", {})

    for server in config.enabled_servers:
        for tool in server.tools:
            row[impact_column(server.key, tool.name)] = _rating(
                impact.get(server.key, {}).get(tool.name)
            )
        for asset in server.assets:
            row[sensitivity_column(server.key, asset.name)] = _rating(
                sensitivity.get(server.key, {}).get(asset.name)
            )
        for asset, tool in server.blast_cells:
            row[blast_column(server.key, asset, tool)] = _blast_rating(
                blast.get(server.key, {}).get((asset, tool))
            )

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
        for server in config.enabled_servers:
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
    return records


def missing_required(config: SurveyConfig, server: Server, answers: dict[str, Any]) -> list[str]:
    """Human-readable list of what is still unanswered in one server section.

    Blast cells default to N/A and are never individually required, but a matrix
    left entirely N/A is treated as unanswered.
    """
    problems: list[str] = []
    impact = answers.get("impact", {}).get(server.key, {})
    unrated_tools = [tool.name for tool in server.tools if impact.get(tool.name) in (None, "")]
    if unrated_tools:
        problems.append("Tool Impact: " + ", ".join(unrated_tools))

    sensitivity = answers.get("sensitivity", {}).get(server.key, {})
    unrated_assets = [
        asset.name for asset in server.assets if sensitivity.get(asset.name) in (None, "")
    ]
    if unrated_assets:
        problems.append("Asset Sensitivity: " + ", ".join(unrated_assets))

    blast = answers.get("blast", {}).get(server.key, {})
    scored = [value for value in blast.values() if value not in (None, "", NOT_APPLICABLE)]
    if not scored:
        problems.append("Blast Radius: every cell is N/A — score at least one tool/asset pair")
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
