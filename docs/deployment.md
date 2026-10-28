# Deployment and operations

How the survey is hosted on Streamlit Community Cloud, and how to keep it healthy while
data is being collected. Database setup is covered separately in
[supabase.md](supabase.md).

## Hosting overview

| Piece | Where it runs | What it needs |
| --- | --- | --- |
| The survey app (`streamlit_app.py`) | Streamlit Community Cloud, built from `main` | The secrets below |
| Response storage | A Supabase project | Tables from [supabase.md](supabase.md) |
| Database health check | GitHub Actions, every two days | `SUPABASE_URL`, `SUPABASE_SECRET_KEY` repository secrets |

Streamlit Community Cloud redeploys automatically on every push to the branch the app
is built from (`main`).

## Secrets

The app reads its secrets from **Streamlit → app → Settings → Secrets**, or from
`.streamlit/secrets.toml` when run locally. A commented template is in
[`.streamlit/secrets.toml.example`](../.streamlit/secrets.toml.example).

| Key | Needed for | Value |
| --- | --- | --- |
| `admin_token` | The researcher panel | A long random string, e.g. from `python -c "import secrets; print(secrets.token_urlsafe(32))"` |
| `supabase_url` | Storing responses | `https://<project-ref>.supabase.co` |
| `supabase_key` | Storing responses | A Supabase secret key (`sb_secret_…`) |
| `responses_csv_path` | Optional | Where the local-CSV fallback writes |
| `sheet_key`, `worksheet_name`, `[gcp_service_account]` | Optional | The Google Sheets fallback; also add `gspread` to `requirements.txt` |

Without `admin_token` the researcher panel cannot be opened at all. Without the two
Supabase keys, responses go to a file inside the container, which Streamlit Cloud
deletes on every restart (see [Storage fallbacks](#storage-fallbacks)).

## Deploying the app

1. Sign in at <https://share.streamlit.io> with a GitHub account that has **admin**
   access to the repository.
2. Choose **Create app**, select the repository and branch `main`, and set the entry
   point to `streamlit_app.py`.
3. Open **Advanced settings**, choose **Python 3.11** (the version the tests run on),
   and paste the secrets:

   ```toml
   admin_token  = "a-long-random-string"
   supabase_url = "https://<project-ref>.supabase.co"
   supabase_key = "sb_secret_..."
   ```

4. Deploy, then share the `https://<name>.streamlit.app` URL with participants.

The researcher panel is the same URL with `?admin=<admin_token>` appended. Anyone
holding that link can read every response: treat it as a password and never commit it.

**Public or private repository.** The repository is public, which is safe because it
holds no responses and no credentials (`data/` and `.streamlit/secrets.toml` are
gitignored). Community Cloud can also deploy from a private repository, but an app
built from one is private by default and participants would be asked to sign in. If
you make the repository private, set the app's sharing to public.

## Managing the app

* **Who can manage it.** Community Cloud takes permissions from GitHub: anyone with
  write access to the repository can manage the app (secrets, reboot, logs). Changes to
  repository access take up to 15 minutes to apply.
* **Do not rename the repository or the GitHub account.** The app is identified by its
  GitHub coordinates; renaming either loses admin access to it.
* **Logs.** Open the app while signed in, then **Manage app** (bottom right) to see the
  live log.
* **Changing secrets.** Edit them under **Settings → Secrets**; the app picks them up
  without a redeploy.

## Shipping a change

1. Change the code or `survey_config.json` on a branch, and run the tests
   (`python -m pytest tests -q`).
2. Merge to `main`. Streamlit Cloud redeploys on its own.
3. **If anything under `survey/` changed, reboot the app**: **Manage app → ⋮ → Reboot
   app**. A plain redeploy re-runs `streamlit_app.py` in the existing Python process,
   which keeps the old `survey.*` modules imported, so the new entry script runs
   against the old classes and fails with an `AttributeError`. Changes to
   `survey_config.json` or `streamlit_app.py` alone do not need a reboot.
4. Open the app in a private browser window and click through one server.

Do not rename tools, assets or servers once data collection has started: their names
are column names, and renaming one splits the data across two columns. See
[editing-the-survey.md](editing-the-survey.md).

## Keeping the app awake

Community Cloud puts an app to sleep after **12 hours without traffic**. A sleeping
link shows a "Zzzz" screen and takes about two minutes to wake, which loses
participants.

`.github/workflows/keep-awake.yml` was written to prevent this by requesting the app
every 30 minutes. It **does not work**: Streamlit answers a plain HTTP request with a
static shell, so `curl` gets `200` whether the app is awake or asleep and never starts
a session. Its collection window (`COLLECTION_ENDS`) has also passed, so it has
disabled itself. A headless-browser version does work and is in the commit history if
it is needed again.

In practice: **open the participant link yourself shortly before each recruiting
wave**, and wait for the survey to load.

The Supabase project has a separate inactivity limit, handled by the database health
check — see [supabase.md](supabase.md#pausing-and-the-health-check).

## Before sending the link out

1. Reboot the app if anything under `survey/` changed since the last reboot.
2. Remove the `[client] showErrorDetails = true` section from
   `.streamlit/config.toml`. It was added for debugging and shows real tracebacks to
   participants.
3. Make sure `admin_token` and the Supabase secret key are current, and rotated if they
   were ever shared in plain text.
4. Check the **Database health** workflow ran green recently (GitHub → **Actions**).
5. Open the link in a private window and complete the survey once, using the
   participant ID `TEST`. This is the only check that shows what a participant sees.
6. Confirm the row landed (`select count(*) from responses;`), then delete it — see
   [supabase.md](supabase.md#removing-test-submissions).

## Storage fallbacks

The backend is chosen from the secrets, most durable first:

| Condition | Backend |
| --- | --- |
| `supabase_url` and `supabase_key` set | Supabase |
| `gcp_service_account` and `sheet_key` set | Google Sheets |
| neither | local CSV at `data/responses.csv` |

The researcher panel names the backend in use on its first line.

The local CSV is for development only: Streamlit Community Cloud runs the app in an
ephemeral container that is replaced on redeploy, on config change and after
inactivity, and the file goes with it. The CSV backend also refuses to append under a
header written by an older version of the survey, rather than misaligning every value;
move the old file aside if that happens.

## Safety net

Whatever the backend, the thank-you page offers every participant a **Download my
responses (CSV)** button. If the write failed, the page says so plainly and asks them
to send that file to the researcher, so a completed response is never silently lost.

## References

* [Streamlit: Deploy your app on Community Cloud](https://docs.streamlit.io/deploy/streamlit-community-cloud/deploy-your-app)
* [Streamlit: Share your app](https://docs.streamlit.io/deploy/streamlit-community-cloud/share-your-app)
* [Streamlit: Trust and security](https://docs.streamlit.io/deploy/streamlit-community-cloud/get-started/trust-and-security)
