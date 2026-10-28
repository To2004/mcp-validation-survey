# Handover

A checklist for taking over the survey from its previous maintainer: what is running,
which access to transfer, which secrets to rotate, and what is still undecided.

## Current state

As of 28 October 2026:

| Item | State |
| --- | --- |
| Participant link | <https://tem6j6jhm5dtyan6mq7mtl.streamlit.app>, built from `main` |
| Repository | <https://github.com/To2004/mcp-validation-survey> (public) |
| Database | Supabase project `hgruwsvuxbwzuanymgyv`, free plan |
| Database health workflow | Active, passing every two days |
| Keep-awake workflow | Disabled, and known not to work — see [deployment.md](deployment.md#keeping-the-app-awake) |
| Survey content | 5 servers across 4 organisations; 2 servers per participant; 4 steps per server |
| `showErrorDetails` | Still on in `.streamlit/config.toml`; remove before recruiting |

The most recent content changes (16 October 2026) added the Inputs That Change the
Risk step, a 4 × 4 Consequence Scope matrix, and per-page times.

## Access to transfer

| System | What the new maintainer needs | How to grant it |
| --- | --- | --- |
| GitHub repository | **Write** to manage the existing app; **admin** to deploy a new one | Repository **Settings → Collaborators → Add people** |
| Streamlit Community Cloud app | Follows GitHub access | Automatic, within about 15 minutes of the GitHub change |
| Supabase project | Membership of the organisation that owns the project | Supabase dashboard → the organisation → **Team → Invite** |
| GitHub Actions secrets | Admin on the repository, to update them | Included with admin access; values can be replaced but not read |

Do not send secret values by email or chat. Anyone who can manage the app can read the
Streamlit secrets, and Supabase members can create their own keys.

## Secrets to rotate

Rotate both at handover, so that only current maintainers hold working credentials.

1. **`admin_token`.** An earlier value was committed to this public repository and is
   still in its git history, so it must not remain valid. Generate a new one
   (`python -c "import secrets; print(secrets.token_urlsafe(32))"`) and replace it in
   **Streamlit → Settings → Secrets**. Old researcher-panel links stop working.
2. **The Supabase secret key.** The current key has passed through a chat transcript.
   Follow [supabase.md](supabase.md#rotating-the-secret-key), which updates the
   Streamlit secret and the GitHub Actions secret in an order that loses no
   submissions.

## Material outside this repository

These are not in the repository on purpose; ask the previous maintainer for them if
you need to regenerate content or analyse results.

* **The source Word form** (`MCP_Static_Scanner_Validation_Form_v9.docx`) and the
  script that turned it into the first `survey_config.json`. The form contains an
  appendix of expected answers that must never reach participants.
* **The scanner results** the current content was built from (experiment
  `five_level_v2_policy_v5r_nacombo`), and the CSVs the level definitions were taken
  from. These are what the human ratings are compared against.

## Open decisions

Recorded in [status-2026-08-28.md](status-2026-08-28.md#still-open--your-call). Not
re-checked since that date except where noted:

1. **Rubric fidelity.** The participant-facing scales were found to diverge from the
   scanner's prompts in several places. Fixable in the config alone.
2. **Pull-request approval on the Helios GitHub server.** Whether approving a pull
   request deploys anything decides the expected level of
   `create_pull_request_review`.
3. **Subsampling the Consequence Scope matrix.** *Resolved* on 16 October 2026: the
   matrix is now 4 tools × 4 assets per server.
4. **An overall-risk question.** Without one, the composite
   `impact × confidentiality × scope` cannot be tested against human judgement.

## First-day checklist

1. Get access to GitHub, Streamlit and Supabase (above).
2. Clone the repository, install it and run the tests — see the
   [README](../README.md#quick-start).
3. Read, in order: [architecture.md](architecture.md), [supabase.md](supabase.md),
   [deployment.md](deployment.md), [data-format.md](data-format.md),
   [known-issues.md](known-issues.md).
4. Rotate both secrets.
5. Disable and re-enable the **Database health** workflow under **Actions**, so that
   failure emails come to you rather than the previous maintainer.
6. Complete the live survey once with participant ID `TEST`, confirm the row in
   Supabase, then delete it.
