# Supabase

How the survey stores responses in Supabase, and how to set up, operate, query and
troubleshoot the database. This is the backend for every real data-collection run.

## What Supabase does in this project

[Supabase](https://supabase.com) is a hosted Postgres database. The app talks to it
through the official `supabase` Python client, from the server side only:

* **One write per completed submission.** When a participant presses Submit, the app
  inserts one row into `responses`, then one row per individual answer into
  `ratings`. Nothing is written for a session that is abandoned before Submit.
* **Two kinds of read.** At the start of every session the app reads
  `responses.assigned_servers` to decide which servers the new participant gets
  (least-covered first). The researcher panel reads `responses.answers` to show and
  export everything collected.
* **No Supabase Auth, no browser access.** Participants never talk to Supabase
  directly, and the database key never reaches the browser.

If a write fails, the participant is told so on the thank-you page and offered a CSV
download of their answers to send to the researcher, so a completed response is never
silently lost.

## Setting up a new project

Do this once per study. It takes about five minutes.

1. **Create the project.** Sign in at <https://supabase.com>, choose **New project**,
   and pick a region close to your participants. The free plan is enough.
2. **Create the tables.** Open **SQL Editor**, paste the schema below, and run it.
   It is safe to run more than once.
3. **Copy the credentials.** Open **Project Settings → API Keys** and copy:
   * the **Project URL** — `https://<project-ref>.supabase.co`;
   * a **secret key** — it starts with `sb_secret_`. The legacy `service_role` key
     also works.

   Do **not** use the publishable (`sb_publishable_…`) or legacy `anon` key. Row level
   security is on with no policies, so those keys can neither read nor write, and
   every submission would fail.
4. **Give the app the credentials.** In Streamlit Community Cloud open the app's
   **Settings → Secrets** and add:

   ```toml
   supabase_url = "https://<project-ref>.supabase.co"
   supabase_key = "sb_secret_..."
   ```

5. **Give the health check the credentials.** In GitHub open the repository's
   **Settings → Secrets and variables → Actions** and add `SUPABASE_URL` and
   `SUPABASE_SECRET_KEY` with the same two values. See
   [Pausing and the health check](#pausing-and-the-health-check).
6. **Verify.** Complete the survey once yourself, then check that:
   * the researcher panel (`<app-url>/?admin=<admin_token>`) reads
     **Backend: Supabase** and shows one response;
   * `select count(*) from responses;` returns 1;
   * `select count(*) from ratings;` returns the number of rating columns in the
     survey (203 with the current config — see the note under
     [`ratings`](#ratings--one-row-per-answer)).

   Then delete the test row (see [Removing test submissions](#removing-test-submissions)).

## Schema

The same SQL is kept in `survey/storage.py` as `SUPABASE_SCHEMA_SQL`;
`tests/test_storage.py` fails if the two copies drift apart.

```sql
create table if not exists responses (
    submission_id          text primary key,
    submitted_at_utc       timestamptz,
    participant_id         text,
    email                  text,
    familiarity_llm_agents integer,
    familiarity_mcp        integer,
    consent                text,
    assigned_servers       text,
    duration_seconds       integer,
    ambiguity_notes        text,
    comments               text,
    confidence             integer,
    answers                jsonb not null
);

create table if not exists ratings (
    submission_id text not null references responses(submission_id) on delete cascade,
    dimension     text not null,
    server        text not null,
    asset         text not null default '',
    tool          text not null default '',
    value         text not null,
    value_num     integer,
    primary key (submission_id, dimension, server, asset, tool)
);

create index if not exists ratings_dimension_idx on ratings (dimension, server);

alter table responses enable row level security;
alter table ratings   enable row level security;
```

### `responses` — one row per participant

The metadata columns hold the intro and feedback answers. `answers` holds the
**complete** wide row as JSON — every rating, every page time and every metadata
field — so it can rebuild the CSV export on its own.

| Column | Contents |
| --- | --- |
| `submission_id` | UUID created when the session starts |
| `submitted_at_utc` | When Submit was pressed |
| `participant_id`, `email` | As entered on the intro page; email is optional |
| `familiarity_llm_agents`, `familiarity_mcp` | Self-reported, 1–5 |
| `consent` | `yes` |
| `assigned_servers` | The servers this participant rated, e.g. `calendar\|slack` |
| `duration_seconds` | Time from opening the survey to Submit |
| `ambiguity_notes`, `comments`, `confidence` | Final feedback page |
| `answers` | The full wide row (JSONB) |

### `ratings` — one row per answer

| Column | Contents |
| --- | --- |
| `dimension` | `impact`, `sensitivity`, `blast`, `inputs`, or `seconds` (time on a page) |
| `server` | Server key: `calendar`, `github`, `slack`, `filesystem`, `sqlite`; blank for the intro and feedback page times |
| `asset` | The asset (sensitivity, blast), the input name (inputs), or the page (seconds) |
| `tool` | The tool (impact, blast, inputs) |
| `value` | The answer as text: `1`–`5`, `unsure`, `N/A`, `changes`, `no_change`, or a number of seconds |
| `value_num` | `value` as an integer, or null when it is not a number |

**Blank rows.** Each submission writes one `ratings` row for *every* rating column in
the survey, not only for what the participant answered. Servers the participant was
not assigned, and pages they never saw, appear with `value = ''`. Filter them out
with `value <> ''`, or count with `count(value_num)` instead of `count(*)`.

Because `value_num` is null for blanks, `unsure`, `N/A` and the inputs answers,
`avg(value_num)` skips them automatically. Value meanings and analysis caveats are in
[data-format.md](data-format.md).

### Changing the schema

`create table if not exists` does not add columns to a table that already exists. If
the code starts writing a new column, add it to the live database explicitly, for
example:

```sql
alter table responses add column if not exists assigned_servers text;
```

Update `SUPABASE_SCHEMA_SQL` and this page in the same commit.

## Security model

* Row level security is enabled on both tables with **no policies**. The publishable
  and `anon` keys therefore have no access at all.
* The app uses a secret key, which bypasses row level security. It is a full admin
  credential for the database: anyone holding it can read and delete every response.
* It lives in two places only: Streamlit's server-side secrets and the GitHub Actions
  secrets. Never put it in the repository (it is public), in a chat message, or in
  client-side code.

### Rotating the secret key

Rotate it when the project changes hands, when someone leaves, or if it may have been
exposed.

1. **Project Settings → API Keys → Create new secret key.**
2. Replace `supabase_key` in the Streamlit app's secrets.
3. Replace `SUPABASE_SECRET_KEY` in the GitHub Actions secrets.
4. Complete one test submission and confirm it lands.
5. Delete the old secret key in Supabase.

Doing it in this order means no submission fails while the key changes.

## Querying the data

Use **SQL Editor** in the Supabase dashboard. Results can be downloaded as CSV from
the results pane.

```sql
-- Responses collected so far
select count(*) from responses;

-- Coverage: how many participants rated each server
select unnest(string_to_array(assigned_servers, '|')) as server, count(*) as participants
from responses group by 1 order by 2 desc;

-- Mean human Action Impact per tool (n = numeric ratings only)
select server, tool, avg(value_num) as mean_impact, count(value_num) as n
from ratings where dimension = 'impact'
group by server, tool order by server, mean_impact desc;

-- "Not sure" rate per item (report this alongside any agreement figure)
select dimension, server, asset, tool,
       round(avg((value = 'unsure')::int), 2) as unsure_rate, count(*) as n
from ratings
where dimension in ('impact', 'sensitivity', 'blast', 'inputs')
  and value not in ('', 'N/A')
group by dimension, server, asset, tool order by unsure_rate desc;

-- Mean seconds per page
select server, asset as page, avg(value_num) as mean_seconds, count(value_num) as n
from ratings where dimension = 'seconds'
group by server, asset order by server, asset;
```

### Exporting

* **Researcher panel** — wide and long CSVs, built from `responses.answers`. Column
  layout is in [data-format.md](data-format.md).
* **Table Editor** — select a table, then **Export → Export table as CSV**.
* **SQL Editor** — run any query and download the result.

Export the data after each recruiting wave and keep a copy outside Supabase. A free
project that was paused and later restored once came back with both tables gone.

### Removing test submissions

Mark test runs with a recognisable participant ID such as `TEST`. Deleting the
`responses` row removes its `ratings` rows too (`on delete cascade`):

```sql
select submission_id, submitted_at_utc from responses where participant_id = 'TEST';
delete from responses where participant_id = 'TEST';
```

Check the `select` before running the `delete`; there is no undo.

## Pausing and the health check

A free Supabase project **pauses after about 7 days without database activity**. While
it is paused the hostname stops resolving, every submission fails at the very end of
the survey, and new participants get an unbalanced server assignment.

The **Database health** workflow (`.github/workflows/database-health.yml`) prevents
this. Every two days it queries both tables, which resets the inactivity timer, and it
fails if either table is missing or unreachable. A failed run sends an email, so
silence means healthy.

Things to know about it:

* It needs the `SUPABASE_URL` and `SUPABASE_SECRET_KEY` repository secrets. Update
  `SUPABASE_SECRET_KEY` whenever the key is rotated, or the workflow starts failing.
* GitHub emails scheduled-workflow failures to the person who last changed the
  workflow's `cron` line (or who last re-enabled it), not to every maintainer. A new
  maintainer should re-enable the workflow, or watch the **Actions** tab.
* GitHub disables scheduled workflows in a public repository after 60 days without
  commits. If the **Actions** tab shows the workflow as disabled, enable it again.
* You can run it on demand: **Actions → Database health → Run workflow**.

**If the project is paused,** open it in the Supabase dashboard and choose
**Restore project**. When it is back, run `select count(*) from responses;`. If the
tables are missing, run the schema again, and recover any lost data from your most
recent export.

## Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Researcher panel reads **Backend: local CSV file** | `supabase_url` or `supabase_key` missing from the Streamlit secrets | Add both, then reboot the app |
| Thank-you page says the answers *could not be written*, with a name-resolution or connection error | Project paused | Restore it (see above) |
| … with `Invalid API key` or HTTP 401 | The key was rotated or mistyped | Put the current secret key in the Streamlit secrets |
| … with `row-level security` or error `42501` | A publishable / `anon` key was used | Use a secret key |
| … with `relation "responses" does not exist` | Tables never created, or the project was reset | Run the schema |
| … with `Could not find the '<column>' column` (`PGRST204`) | The table is older than the code | `alter table … add column if not exists …` |
| *The response was saved but its individual ratings were not* | The `ratings` insert failed after `responses` succeeded | Nothing is lost: `responses.answers` holds every value. Fix the cause; the missing `ratings` rows can be rebuilt from `answers` |
| Database health workflow fails with a 404 | A table is missing | Run the schema; check whether data was lost |
| Database health workflow fails with status `000` | Project paused | Restore it |

## References

* [Supabase: Understanding API keys](https://supabase.com/docs/guides/api/api-keys)
* [Supabase: Migrating to publishable and secret API keys](https://supabase.com/docs/guides/getting-started/migrating-to-new-api-keys)
* [GitHub: Disabling and enabling a workflow](https://docs.github.com/en/actions/managing-workflow-runs-and-deployments/managing-workflow-runs/disabling-and-enabling-a-workflow)
