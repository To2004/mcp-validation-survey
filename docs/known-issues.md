# Known issues in the source form

Findings from converting `MCP_Static_Scanner_Validation_Form_v9.docx` into this app.
The app reproduces the form as written and does **not** silently correct it. Read this
before analysing results.

## 1. Blast Radius rates different assets from Asset Sensitivity

On every server, the Step 3 matrix rows are not the Step 2 asset list. Some assets are
rated for sensitivity but never appear in the matrix; others appear in the matrix but
are never rated for sensitivity.

| Server | In the matrix but never rated for sensitivity | Rated for sensitivity but not in the matrix |
| --- | --- | --- |
| Google Calendar | `calendar-records`, `free-busy-availability`, `recruiting` | `calendar-directory`, `connected-account-config`, `holidays`, `team` |
| GitHub | `backend-api`, `issues-and-comments`, `payments-service` | `internal-docs`, `public-website`, `repository-catalog`, `repository-contents` |
| Slack | `exec-private`, `read-markers` | `announcements`, `engineering`, `incident-response` |
| Filesystem | `product-source` | `project-material`, `public-overview` |
| SQL Database | `database-records`, `grants`, `table-catalog` | `datasets`, `projects`, `publications`, `table-metadata` |

**Consequence.** For an asset in the left column you have a human blast score but no
human sensitivity score, so no human `sensitivity x blast` risk value can be computed
for it. For an asset in the right column the reverse holds. Only the overlapping
assets support a full human-side risk score.

**Options.** Either (a) analyse the three dimensions separately against the scanner,
which needs no change; or (b) align the two asset lists in `survey_config.json` before
collecting data. The app surfaces this list in the researcher panel under *Survey
design warnings*.

## 2. Blast Radius level 5 refers to three routes that are not in the form

The Blast Radius scale defines level 5 as: the consequences escape the asset, and
"Award 5 only through one of the three routes listed below." Those three routes do not
appear anywhere in the document — the sentence is a dangling reference.

**Consequence.** Participants are told level 5 is gated on criteria they are never
shown, so any 5 in the Blast Radius data is unguided.

**Fix.** Add the three routes to `scales.blast[4].meaning` in `survey_config.json`
before running the study.

## 3. Tool Impact does not span 1–5 on most servers

This one is intentional and documented in the form's own provenance note: Google
Calendar covers 1–5, GitHub only 2–4, Slack 2–5, Filesystem 2–4, SQL Database 2–5.
Only Google Calendar has a liveness (level 1) tool.

**Consequence.** Do not expect the full range per server, and do not treat a missing
level as participant error.

## 4. The form says "five MCP servers", the tool counts are subsets

The scenarios describe the real catalogs (13 Calendar tools, 26 GitHub, 16 Slack, 14
Filesystem, 5 SQL), but participants rate a 7-tool subset of each (5 for SQL). This is
deliberate sampling; the scenario wording keeps the real numbers so participants judge
against the real surface. Worth stating explicitly in your write-up.
