# MCP Static Scanner Validation Survey

A Streamlit web app that collects human risk ratings of Model Context Protocol (MCP)
tools and data assets, so they can be compared with the scores of an MCP static risk
scanner. Participants open one link and complete a guided survey. Each completed
submission is stored in a Supabase (Postgres) database, ready for SQL or CSV analysis.

Participants never need an account and never see the researcher controls or the
scanner's own answers.

## Overview

The static scanner rates every MCP tool and asset on three dimensions. This survey
asks people the same questions, using the scanner's own level definitions, so that
human and scanner judgements can be compared item by item.

**Five MCP servers across four fictional organisations:**

| Server key | Server | Organisation |
| --- | --- | --- |
| `calendar` | Google Calendar | Aurora Airways — commercial airline |
| `github` | GitHub | Helios Grid — electricity transmission |
| `slack` | Slack | Vireo Bio — biopharma, blinded clinical trials |
| `filesystem` | Filesystem | CBG — research organisation |
| `sqlite` | SQL Database | CBG — research organisation |

**Four steps per server:**

| Step (as participants see it) | Key | Earlier name | Question | Answers |
| --- | --- | --- | --- | --- |
| Action Impact | `impact` | Tool Impact | What can one call of this tool do? | 1–5 or Not sure |
| Asset Confidentiality | `sensitivity` | Asset Sensitivity | How harmful would exposure of this asset be? | 1–5 or Not sure |
| Consequence Scope | `blast` | Blast Radius | How far does one call's result reach? (4 tools × 4 assets) | 1–5 or Not sure |
| Inputs That Change the Risk | `inputs` | — | Does this input's value change the risk significantly? (8 inputs; 5 for SQL) | Changes / No change / Not sure |

The earlier names still appear in some code comments and docs; they mean the same
steps.

**How a session runs:**

* A Google-Forms-style wizard: one section per screen, a progress bar, per-section
  validation, and Back / Next navigation.
* An intro page (participant ID, optional email, familiarity with LLM agents and MCP,
  consent), then the assigned servers' steps, then optional feedback.
* Each participant rates **2 of the 5 servers**, assigned least-covered first so
  coverage stays even across the study (`servers_per_participant` in the config).
* A clock shows the time so far (`show_timer` in the config turns it off), and the
  seconds spent on each page are stored either way.
* In the Consequence Scope matrix, every tool × asset pair is one the tool really acts
  on, according to the scanner. Any pair it does not act on is shown read-only as
  `N/A`.
* Only **completed** submissions are stored. An abandoned session leaves nothing.
* A password-protected researcher panel shows and exports everything collected.

All participant-facing text lives in [`survey_config.json`](survey_config.json). The
app contains no question text of its own: to change a question, change the config.

## How it works

```
 Participant ──► Streamlit Community Cloud ──── reads ───► survey_config.json
   browser        streamlit_app.py + survey/                (all question text)
                        │
                        │ one write per completed submission
                        ▼
                  Supabase (Postgres)
                  ├─ responses   one row per participant (+ full answers as JSONB)
                  └─ ratings     one row per individual answer
                        ▲                     ▲
 Researcher ── ?admin=<token> panel           └── GitHub Actions: database health
              SQL editor, CSV export              check every 2 days
```

Code structure and the request flow are described in
[docs/architecture.md](docs/architecture.md).

## Requirements

* **Python 3.11.** This is the version the test suite is run on.
* For a real study: a [Streamlit Community Cloud](https://share.streamlit.io) account
  (sign in with GitHub) and a [Supabase](https://supabase.com) project. Both free
  plans are enough.

## Quick start

Run the survey on your own machine:

```bash
git clone https://github.com/To2004/mcp-validation-survey.git
cd mcp-validation-survey
python3.11 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements-dev.txt
streamlit run streamlit_app.py
```

The survey opens at <http://localhost:8501>. With no secrets configured, responses are
written to `data/responses.csv` (gitignored).

To open the researcher panel locally, copy the secrets template and set a token:

```bash
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# edit admin_token in .streamlit/secrets.toml, then open:
# http://localhost:8501/?admin=<admin_token>
```

Adding `supabase_url` and `supabase_key` to the same file makes the local app write to
Supabase. Use a separate test project for that, or delete your test rows afterwards
— see [docs/supabase.md](docs/supabase.md#removing-test-submissions).

## Configuration

**Secrets** — in `.streamlit/secrets.toml` locally, or **Settings → Secrets** on
Streamlit Cloud. Never commit them; the repository is public.

| Key | Required | Purpose |
| --- | --- | --- |
| `admin_token` | To use the researcher panel | Password for `?admin=<token>` |
| `supabase_url` | For a real run | `https://<project-ref>.supabase.co` |
| `supabase_key` | For a real run | Supabase secret key (`sb_secret_…`) |

Optional fallbacks (Google Sheets, a custom CSV path) are listed in
[docs/deployment.md](docs/deployment.md#secrets).

**Survey settings** — in `survey_config.json`:

| Setting | Effect |
| --- | --- |
| `servers_per_participant` | How many servers each participant rates (currently 2) |
| `show_timer` | Show the time-so-far clock (default `true`) |
| `"enabled": false` on a server | Drop that server from the survey and the CSV — e.g. disable four to pilot with one |

See [docs/editing-the-survey.md](docs/editing-the-survey.md) for the full structure.

## Supabase

Supabase holds every completed response. Setting it up takes about five minutes:

1. Create a project at <https://supabase.com>.
2. Run the schema from [docs/supabase.md](docs/supabase.md#schema) in the **SQL
   Editor**. It creates two tables, `responses` and `ratings`.
3. Copy the **Project URL** and a **secret key** (`sb_secret_…`) into the app's
   secrets as `supabase_url` and `supabase_key`.
4. Add the same two values as GitHub Actions secrets `SUPABASE_URL` and
   `SUPABASE_SECRET_KEY`, for the health check.

Things to know:

* Use the **secret** key, not the publishable / `anon` key. Row level security is on
  with no policies, so a publishable key cannot write and every submission would fail.
* A free project **pauses after about 7 days** without activity. The *Database health*
  workflow queries it every two days to prevent that, and fails loudly if a table is
  missing.
* `ratings` stores a row for every question in the survey, including blank rows for
  servers a participant was not assigned. Filter on `value <> ''`.

[docs/supabase.md](docs/supabase.md) covers the schema, security model, key rotation,
example queries, exporting, pausing and troubleshooting.

## Deployment

1. Sign in at <https://share.streamlit.io>, choose **Create app**, and pick this
   repository, branch `main`, entry point `streamlit_app.py`.
2. Under **Advanced settings**, choose Python 3.11 and paste the secrets:

   ```toml
   admin_token  = "a-long-random-string"
   supabase_url = "https://<project-ref>.supabase.co"
   supabase_key = "sb_secret_..."
   ```

3. Deploy, then share the `https://<name>.streamlit.app` URL with participants.

Every push to `main` redeploys the app. **After a change under `survey/`, also reboot
the app** (**Manage app → ⋮ → Reboot app**), or it keeps running the old modules.
The pre-launch checklist and operating notes are in
[docs/deployment.md](docs/deployment.md).

## Getting the results

Query Supabase directly, or open the app URL with `?admin=<admin_token>` appended. The
researcher panel shows the response count, a table of everything collected, and two
downloads:

| Export | Shape | Use it for |
| --- | --- | --- |
| **wide** | one row per participant | Excel, per-participant statistics |
| **long** | one row per rating | joining to scanner output, agreement analysis |

Column naming in the wide CSV:

```
impact__<server>__<tool>            e.g. impact__calendar__get-event
sens__<server>__<asset>             e.g. sens__calendar__executive
blast__<server>__<asset>__<tool>    e.g. blast__calendar__executive__get-event
input__<server>__<tool>__<input>    e.g. input__calendar__list-events__timeZone
seconds__<page>                     e.g. seconds__calendar__inputs, seconds__intro
```

Every rating is `1`–`5` or `unsure`; an inputs answer is `changes`, `no_change` or
`unsure`. `N/A` marks a Consequence Scope pair the scanner says does not exist; it is
never a participant's answer. A blank means the participant was not assigned that
server. Read [docs/data-format.md](docs/data-format.md) before analysing: it lists the
caveats that matter for agreement statistics.

## Project layout

```
.
├── streamlit_app.py          UI: pages, navigation, validation, submit, researcher panel
├── survey_config.json        All participant-facing content and survey settings
├── survey/
│   ├── config.py             Loads and validates survey_config.json
│   ├── schema.py             Answers → CSV columns and rows (wide and long)
│   ├── storage.py            Supabase / Google Sheets / local-CSV backends, SQL schema
│   └── assignment.py         Balanced assignment of servers to participants
├── tests/                    pytest suite, including end-to-end runs with AppTest
├── docs/                     Detailed documentation (index below)
├── .streamlit/
│   ├── config.toml           Theme and client settings
│   └── secrets.toml.example  Template for the secrets
├── .github/workflows/
│   ├── database-health.yml   Keeps Supabase awake; fails if a table is missing
│   └── keep-awake.yml        Retired app keep-awake ping (disabled)
├── requirements.txt          Runtime dependencies (installed by Streamlit Cloud)
└── requirements-dev.txt      Runtime + test dependencies
```

## Testing

```bash
python -m pytest tests -q
```

The suite runs offline in about 30 seconds. It covers config validation (including
that no expected answers leak into the participant-facing config), the CSV mapping,
each storage backend, balanced assignment, regressions found in review, and
end-to-end runs of the real app with Streamlit's `AppTest` harness. Run it before
every push to `main`.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/handover.md](docs/handover.md) | **Start here if you are taking over the project:** current state, access, secrets to rotate, open decisions |
| [docs/architecture.md](docs/architecture.md) | Code structure, request flow, identifiers, tests, how to extend |
| [docs/supabase.md](docs/supabase.md) | Database setup, schema, keys, queries, exports, pausing, troubleshooting |
| [docs/deployment.md](docs/deployment.md) | Streamlit Cloud hosting, secrets, shipping changes, pre-launch checklist |
| [docs/editing-the-survey.md](docs/editing-the-survey.md) | Changing questions, servers and settings in `survey_config.json` |
| [docs/data-format.md](docs/data-format.md) | CSV columns, value meanings, analysis caveats |
| [docs/known-issues.md](docs/known-issues.md) | Discrepancies found in the source form, and how they were handled |
| [docs/design-notes.md](docs/design-notes.md) | Layout, accessibility and colour choices |
| [docs/status-2026-08-28.md](docs/status-2026-08-28.md) | Review findings and open questions as of 28 August 2026 |

## Security

* The repository is public. It holds no responses and no credentials: `data/` and
  `.streamlit/secrets.toml` are gitignored.
* The researcher-panel link (`?admin=<token>`) and the Supabase secret key each give
  full access to every response. Keep them out of the repository, issues and chat.
  Rotate them when people leave the project — see
  [docs/handover.md](docs/handover.md#secrets-to-rotate).
