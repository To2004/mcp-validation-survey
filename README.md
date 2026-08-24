# MCP Static Scanner Validation Survey

A Streamlit web app that runs the *MCP Static Scanner Validation Survey* (Human
Evaluation of MCP Tool and Resource Risk) as a shareable link, and collects every
response into a CSV you can analyse.

Participants get one URL. They never see the researcher keys, and they never need
an account.

## What it does

* Renders the survey as a Google-Forms-style wizard — one section per screen, with a
  progress bar, per-section validation, and Back/Next navigation.
* Covers all five MCP servers from the source form (Google Calendar, GitHub, Slack,
  Filesystem, SQL Database), each with the three scoring steps: **Tool Impact**,
  **Asset Sensitivity** and **Blast Radius**.
* Writes one row per participant to CSV, plus a long-format export (one row per
  rating) that joins cleanly against the scanner's own output.
* Gives the researcher a password-gated panel to view and download everything.

All survey content is generated from the source Word form into
[`survey_config.json`](survey_config.json). The app contains no question text of its
own — to change a question, change the config.

## Quick start

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

The survey opens at <http://localhost:8501>.

## Deploying a public link

1. Push this repository to GitHub (it must be public for the free tier).
2. Go to <https://share.streamlit.io>, click **New app**, and pick this repo with
   `streamlit_app.py` as the entry point.
3. In **Advanced settings → Secrets**, paste at least:

   ```toml
   admin_token = "some-long-random-string"
   ```

4. Deploy. Share the resulting `https://<name>.streamlit.app` URL with participants.

**Before a real run, set up the Google Sheets backend** (see
[docs/deployment.md](docs/deployment.md)). Without it responses go to a file inside
the container, which Streamlit Cloud wipes on every restart or redeploy.

## Getting the results

Open your app URL with `?admin=<admin_token>` appended. The researcher panel shows
the response count, a table of everything collected, and two download buttons:

| Export | Shape | Use it for |
| --- | --- | --- |
| **wide** | one row per participant | opening in Excel, per-participant stats |
| **long** | one row per rating | joining to scanner output, agreement analysis |

Column naming in the wide CSV:

```
impact__<server>__<tool>            e.g. impact__calendar__get-event
sens__<server>__<asset>             e.g. sens__calendar__executive
blast__<server>__<asset>__<tool>    e.g. blast__calendar__executive__get-event
```

Every rating a participant makes is `1`–`5`. The Blast Radius matrix is pre-restricted
to the tool × asset pairs the scanner says exist: dead pairs render read-only as `N/A`,
and a tool that acts on no asset is dropped from the matrix. Participants score every
live cell before moving on.

## Running only some servers

Set `"enabled": false` on any server in `survey_config.json` to drop it from the
survey and from the CSV. To pilot with just Google Calendar, disable the other four.

## Documentation

| Document | Contents |
| --- | --- |
| [docs/deployment.md](docs/deployment.md) | Hosting, secrets, Google Sheets backend |
| [docs/data-format.md](docs/data-format.md) | CSV columns, value meanings, analysis notes |
| [docs/editing-the-survey.md](docs/editing-the-survey.md) | Changing questions, regenerating the config |
| [docs/known-issues.md](docs/known-issues.md) | Discrepancies found in the source form |
| [docs/design-notes.md](docs/design-notes.md) | Layout, accessibility and colour choices |

## Tests

```bash
python -m pytest tests -q
```

Covers config validation, the CSV mapping, and end-to-end runs of the real app via
Streamlit's `AppTest` harness.
