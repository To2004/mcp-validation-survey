# Architecture

How the code is organised and how a submission moves through it. Read this before
changing anything outside `survey_config.json`.

## Design principles

* **The survey is data.** Every question, tool, asset, scale and context text comes
  from `survey_config.json`. The Python code contains no survey wording, so content
  changes never need a code change.
* **Fail at startup, not mid-session.** The config is validated strictly when it is
  loaded. A malformed file stops the app with an error message before any participant
  sees a page.
* **Session state is the single source of truth.** Every answer lives in
  `st.session_state` under a stable widget key. The submitted row is derived from those
  keys at Submit time, never accumulated along the way.
* **Write once, append only.** Storage is touched once per participant, at Submit.
  Nothing is updated or deleted by the app.

## Modules

| File | Responsibility |
| --- | --- |
| `streamlit_app.py` | The UI: page plan, navigation, per-page validation, rating widgets, page timer, Submit, thank-you page, researcher panel |
| `survey/config.py` | Loads `survey_config.json` into frozen dataclasses (`SurveyConfig`, `Server`, `Item`, `Level`, `InputItem`), validates it (`ConfigError`), and `lint()`s it for design warnings shown in the researcher panel |
| `survey/schema.py` | The data contract: column names, the ordered wide-CSV column list, answers → wide row, wide rows → long records, and which answers are still missing on a page |
| `survey/storage.py` | Storage backends (`SupabaseStorage`, `GoogleSheetsStorage`, `LocalCsvStorage`), backend selection from secrets, the Supabase schema SQL, and CSV rendering |
| `survey/assignment.py` | Balanced assignment of servers to participants |
| `survey_config.json` | All participant-facing content and the survey settings |

Dependencies run one way: `streamlit_app.py` → `schema`, `storage`, `assignment` →
`config`. Only `streamlit_app.py` imports Streamlit, which is what makes the `survey`
package testable without a running app.

## A participant's session

```
open link ─► init_state()              submission_id, start time, empty answers
          ─► intro page                participant ID, email, familiarity, consent
          ─► Next ─► assign_servers()  reads assigned_servers from storage,
                                        picks the least-covered servers
          ─► for each assigned server:
               impact ─► sensitivity ─► blast ─► inputs (only if the server has inputs)
          ─► feedback page
          ─► Submit ─► response_to_row() ─► storage.append()
          ─► thank-you page            submission ID + "Download my responses (CSV)"
```

* **Pages.** `pages()` builds the plan: intro, then each assigned server's steps, then
  feedback. Before assignment the progress bar projects the final page count, so it
  never shows a misleading total.
* **Validation.** Next runs `validate()` for the current page. Every live cell of an
  assigned server is required; "Not sure" counts as an answer. The feedback page is
  optional.
* **Timing.** `record_page_time()` adds the time spent on a page each time the
  participant leaves it, so Back-then-Next accumulates both visits. The clock at the
  top of the page ticks in the browser, starting from the elapsed time measured on the
  server.
* **Submit.** `submit()` builds the wide row and calls `storage.append()`. A
  `StorageError` does not lose the response: the thank-you page shows the error and
  the download button.

## The researcher panel

Opening the app with `?admin=<token>` renders `render_admin()` instead of the survey.
The token is compared with `admin_token` using `hmac.compare_digest`. The panel shows
the backend name, any `lint()` warnings, the response count and table, and the wide
and long CSV downloads, all rebuilt from `storage.read_all()`.

## Identifiers

* **Server keys** — `calendar`, `github`, `slack`, `filesystem`, `sqlite`.
* **Step keys** — `impact`, `sensitivity`, `blast`, `inputs`. Participants see the
  display names from `scale_labels` in the config (Action Impact, Asset
  Confidentiality, Consequence Scope, Inputs That Change the Risk). Older docs and
  comments use the earlier names Tool Impact, Asset Sensitivity and Blast Radius for
  the first three.
* **Column names** — parts joined with `__`: `impact__<server>__<tool>`,
  `sens__<server>__<asset>`, `blast__<server>__<asset>__<tool>`,
  `input__<server>__<tool>__<input>`, `seconds__<page>`. The config loader rejects any
  name containing `__`. `storage.parse_rating_column()` turns a column name back into
  `(dimension, server, asset, tool)` for the `ratings` table.

## Tests

`python -m pytest tests -q` runs the whole suite in about 30 seconds, offline. The
Supabase and Google Sheets clients are replaced by fakes.

| File | Covers |
| --- | --- |
| `test_config.py` | Loading and validating the real config; that no researcher answer key leaks into it; that descriptions do not hint at the answer |
| `test_schema.py` | Answers → wide row, column order, long-format records, required-answer checks |
| `test_storage.py` | Each backend, backend selection, the `ratings` mapping, and that the schema in `docs/supabase.md` matches the code |
| `test_assignment.py` | Balanced assignment and coverage |
| `test_inputs_step.py` | The inputs step and per-page times |
| `test_regressions.py` | Defects found in review, one test each |
| `test_app.py` | End-to-end runs of the real app with Streamlit's `AppTest` |

## Extending

* **Add or change a server, tool or asset** — edit `survey_config.json` only; see
  [editing-the-survey.md](editing-the-survey.md).
* **Add a storage backend** — implement the `Storage` protocol in `survey/storage.py`
  (`name`, `append`, `read_all`, `server_counts`), raise `StorageError` on failure,
  and add it to `build_storage()`.
* **Add a step** — touch `STEP_ORDER` and the column helpers in `survey/schema.py`, the
  prefix map in `storage.RATING_PREFIXES`, the parsing in `survey/config.py`, and the
  rendering in `render_step()`. Follow the `inputs` step, which was added this way.
