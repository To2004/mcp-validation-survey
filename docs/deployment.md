# Deployment

How to put the survey behind a public link and keep the responses.

## Streamlit Community Cloud (free)

1. Push this repository to GitHub. The free tier requires a **public** repo — this is
   safe, because the repository contains no responses, no credentials and no
   researcher keys (`data/` and `.streamlit/secrets.toml` are gitignored).
2. At <https://share.streamlit.io> choose **New app**, select the repo and branch, and
   set the entry point to `streamlit_app.py`.
3. Under **Advanced settings → Secrets**, paste your secrets (see below).
4. Deploy, then share the `https://<name>.streamlit.app` URL.

## Secrets

Copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` for local runs, or
paste the same content into the Streamlit Cloud secrets box.

```toml
admin_token = "a-long-random-string"
# responses_csv_path = "/mount/data/responses.csv"   # optional, local backend only
```

The researcher panel is reachable only at `?admin=<admin_token>`. Without
`admin_token` set, the panel cannot be opened at all.

## Storage backends

The app picks a backend automatically:

| Condition | Backend | Durability |
| --- | --- | --- |
| `gcp_service_account` and `sheet_key` in secrets | Google Sheets | Survives restarts |
| otherwise | local CSV at `data/responses.csv` | **Lost when the container restarts** |

Streamlit Community Cloud runs the app in an ephemeral container: it restarts on
redeploy, on config change, and after periods of inactivity. Use the local CSV backend
for development and pilots only.

### Setting up Google Sheets

1. In the Google Cloud console, create a project and enable the **Google Sheets API**
   and **Google Drive API**.
2. Create a **service account** and download its JSON key.
3. Create a Google Sheet for the responses. Share it with the service account's
   `client_email`, giving **Editor** access.
4. Copy the sheet id — the part of the URL between `/d/` and `/edit`.
5. Add to secrets:

```toml
sheet_key = "<the sheet id>"
worksheet_name = "responses"

[gcp_service_account]
type = "service_account"
project_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "...@....iam.gserviceaccount.com"
```

Include the remaining fields from the downloaded JSON key. The app creates the
worksheet and writes the header row on the first submission.

## Safety net

Whatever the backend, every participant is offered a **Download my responses (CSV)**
button on the thank-you page. If the central write fails, the app says so plainly and
asks them to send that file to you, so no response is silently lost.
