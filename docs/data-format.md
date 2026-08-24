# Data format

What the exported CSVs contain and how to read them.

## Wide export — one row per participant

Metadata columns come first, then every rating in question order, then the free-text
feedback.

| Column | Meaning |
| --- | --- |
| `submission_id` | UUID generated per session |
| `submitted_at_utc` | ISO-8601 UTC timestamp of submission |
| `participant_id` | The ID you issued to the participant |
| `email` | Optional, blank if not given |
| `familiarity_llm_agents`, `familiarity_mcp` | 1–5 self-report |
| `consent` | `yes` or `no` |
| `duration_seconds` | Wall-clock time from first page load to submit |
| `ambiguity_notes`, `comments` | Free text |
| `confidence` | 1–5 overall self-rated confidence |

Rating columns are named by dimension, server and target:

```
impact__<server>__<tool>            impact__calendar__get-event
sens__<server>__<asset>             sens__calendar__executive
blast__<server>__<asset>__<tool>    blast__calendar__executive__get-event
```

Server keys are `calendar`, `github`, `slack`, `filesystem`, `sqlite`. The `__`
separator never appears inside a tool or asset name; the config loader rejects any
name that would break this.

## Values

| Dimension | Values |
| --- | --- |
| Tool Impact | 1–5 (Liveness to Irreversible) |
| Asset Sensitivity | 1–5 (Public to Critical) |
| Blast Radius | 1–5 (Negligible to Systemic), or `N/A` |

**`N/A` is an answer, not a gap.** It records the participant's judgement that the
tool does not act on that asset. Treat it as a structural zero: exclude it from mean
blast scores, but count it when comparing the participant's reachability judgement
against the scanner's own N/A cells — that agreement is itself a result.

Every rating is required except inside the Blast Radius matrix, where the app requires
only that at least one cell per matrix is scored. Blank rating cells therefore should
not occur.

## Long export — one row per rating

Columns: `submission_id`, `participant_id`, `dimension`, `server`, `asset`, `tool`,
`value`.

`dimension` is `impact`, `sensitivity` or `blast`. `asset` is blank for impact rows;
`tool` is blank for sensitivity rows. This is the shape to join against the scanner's
per-tool and per-asset output for agreement analysis.

## Analysis caveat

The Blast Radius matrix and the Asset Sensitivity step rate **different asset sets** on
every server. See [known-issues.md](known-issues.md) before pairing sensitivity with
blast scores.
