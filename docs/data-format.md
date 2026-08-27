# Data format

What is stored and how to read it.

## Where the data lives

Completed submissions go to Supabase in two tables: `responses` (one row per
participant, with every value also kept in an `answers` JSONB column) and `ratings`
(one row per individual rating). The researcher panel exports the same data as the
two CSV shapes below. Partial or abandoned sessions are never stored.

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
| `assigned_servers` | which servers this participant rated, e.g. `calendar\|slack` |
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
| Blast Radius | 1–5 (Negligible to Systemic) |

Blast Radius cells can also hold `N/A`, but participants never choose it. The matrix is
pre-restricted to the pairs the scanner says exist: a tool that acts on no asset has no
row at all, and a dead tool/asset pair renders read-only and is written as `N/A`.
Participants only score live pairs, all of which are required.

`N/A` in the export therefore means "the scanner says this pair does not exist", not a
participant judgement — so it carries no agreement signal. Exclude those cells when
comparing human and scanner blast scores.

**Each participant rates only some of the servers.** Every rating for a server they
were not assigned is blank. Read `assigned_servers` before treating a blank as
missing data — within an assigned server, every rating is required, so a blank there
would mean the row came from an older version of the app.

The long export contains records only for assigned servers, so it needs no such care.

### How servers are assigned

Each participant gets `servers_per_participant` (currently 2) of the five, chosen
**least-covered-first with random tie-breaking** rather than uniformly at random.
Coverage therefore stays within one of even at every point in the study, while an
individual participant still cannot predict their pair. If the storage backend cannot
be read at that moment, the app falls back to an unweighted draw rather than blocking
the participant.

To check coverage mid-study:

```sql
select unnest(string_to_array(assigned_servers, '|')) as server, count(*) as participants
from responses group by 1 order by 2 desc;
```

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
