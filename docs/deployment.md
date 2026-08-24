
# Deployment

How to put the survey behind a public link and keep the responses in Supabase.

## 1. Set up Supabase

Responses go to an external Supabase (Postgres) project, so they survive redeploys
and can be queried with SQL.

1. Create a project at <https://supabase.com>.
2. Open **SQL Editor** and run this once:

```sql
create table if not exists responses (
    submission_id          text primary key,
    submitted_at_utc       timestamptz,
    participant_id         text,
    email                  text,
    familiarity_llm_agents integer,
    familiarity_mcp        integer,
    consent                text,
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

3. Go to **Project Settings → API** and copy the **Project URL** and the
   **`service_role`** key.

Row level security is enabled with no policies, so the anon key can do nothing. The
app authenticates with the `service_role` key, which bypasses RLS. That key lives in
Streamlit's server-side secrets and is never sent to the browser — but it is a full
admin credential, so do not paste it anywhere client-side or into the repo.

## 2. Deploy the app

1. Push this repository to GitHub. The Streamlit free tier requires a **public**
   repo — safe here, since the repo holds no responses, no credentials and no
   researcher keys (`data/` and `.streamlit/secrets.toml` are gitignored).
2. At <https://share.streamlit.io> choose **Create app**, select the repo and branch,
   and set the entry point to `streamlit_app.py`.
3. Open **Advanced settings → Secrets** and paste:

```toml
admin_token  = "a-long-random-string"
supabase_url = "https://<project-ref>.supabase.co"
supabase_key = "<service_role key>"
```

4. Deploy, then share the `https://<name>.streamlit.app` URL with participants.

The researcher panel is at that URL plus `?admin=<admin_token>`. Without
`admin_token` set it cannot be opened at all. Do not share that link.

## 3. Check it before sending the link out

Complete the survey once yourself, then confirm:

* the researcher panel shows one response, and its backend line reads **Supabase**;
* `select count(*) from responses;` returns 1;
* `select count(*) from ratings;` returns the number of ratings for one participant.

## What gets stored

Only **completed** submissions. The app writes once, when the participant presses
Submit; an abandoned session leaves nothing behind.

Each submission writes two things:

| Table | Shape | Use it for |
| --- | --- | --- |
| `responses` | one row per participant, plus `answers` (JSONB) holding every value | per-participant stats, exporting the wide CSV |
| `ratings` | one row per individual rating | SQL analysis, joining against scanner output |

```sql
-- mean human Tool Impact per tool
select server, tool, avg(value_num) as mean_impact, count(*) as n
from ratings
where dimension = 'impact'
group by server, tool
order by server, mean_impact desc;
```

## Storage fallbacks

The backend is chosen from secrets, most durable first:

| Condition | Backend |
| --- | --- |
| `supabase_url` and `supabase_key` set | Supabase |
| `gcp_service_account` and `sheet_key` set | Google Sheets |
| neither | local CSV at `data/responses.csv` |

The local CSV is for development only: Streamlit Community Cloud runs the app in an
ephemeral container that is restarted on redeploy, on config change, and after
inactivity, and the file goes with it.

## Safety net

Whatever the backend, every participant is offered a **Download my responses (CSV)**
button on the thank-you page. If the write fails, the app says so plainly and asks
them to send you that file, so no completed response is silently lost.
