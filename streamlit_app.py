"""MCP Static Scanner Validation Survey — a Google-Forms-style Streamlit app.

Every question, tool, asset and scale rendered here comes verbatim from
`survey_config.json`, which is generated from the source Word form. This module
contains no survey content of its own.

Session state is the single source of truth: each answer lives under a stable widget
key, and the submitted row is derived from those keys at submit time.

Run locally:       streamlit run streamlit_app.py
Researcher panel:  add ?admin=<token> to the URL (token set in secrets).
"""

from __future__ import annotations

import hmac
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import streamlit as st

from survey.config import ConfigError, Server, SurveyConfig, lint, load_config
from survey.schema import (
    NOT_APPLICABLE,
    csv_columns,
    long_format_rows,
    missing_required,
    response_to_row,
)
from survey.storage import StorageError, build_storage, to_csv_bytes

APP_ROOT = Path(__file__).resolve().parent
CONFIG_PATH = APP_ROOT / "survey_config.json"
DEFAULT_CSV_PATH = APP_ROOT / "data" / "responses.csv"

STEPS = ("impact", "sensitivity", "blast")
STEP_TITLES = {
    "impact": "Step 1 — MCP Tool Impact scoring",
    "sensitivity": "Step 2 — MCP Asset Sensitivity scoring",
    "blast": "Step 3 — MCP Blast Radius scoring",
}
SCALE_LABELS = {
    "impact": "Tool Impact",
    "sensitivity": "Asset Sensitivity",
    "blast": "Blast Radius",
}
BLAST_OPTIONS = [NOT_APPLICABLE, "1", "2", "3", "4", "5"]
RATING_OPTIONS = [1, 2, 3, 4, 5]

FORM_CSS = """
<style>
  .stApp { background: #f0ebf8; }
  .block-container { max-width: 860px; padding-top: 2rem; padding-bottom: 4rem; }
  /* Every top-level bordered container becomes a Forms-style white card. */
  div[data-testid="stVerticalBlockBorderWrapper"] {
      background: #ffffff;
      border: 1px solid #dadce0 !important;
      border-radius: 8px;
      padding: 4px 8px;
  }
  .form-header {
      background: #ffffff;
      border: 1px solid #dadce0;
      border-top: 10px solid #673ab7;
      border-radius: 8px;
      padding: 22px 24px 18px 24px;
      margin-bottom: 14px;
  }
  .form-header h1 { margin: 0 0 6px 0; font-size: 30px; font-weight: 400; color: #202124; }
  .form-header p  { margin: 0; color: #5f6368; font-size: 14px; }
  .required { color: #d93025; }
  .question-title { font-size: 16px; color: #202124; margin-bottom: 2px; }
  .question-help  { font-size: 13px; color: #5f6368; margin-bottom: 10px; }
  .stProgress > div > div > div > div { background-color: #673ab7; }
</style>
"""


# --------------------------------------------------------------------------- setup


@st.cache_data(show_spinner=False)
def _load() -> SurveyConfig:
    return load_config(CONFIG_PATH)


def get_config() -> SurveyConfig:
    try:
        return _load()
    except ConfigError as exc:
        st.error(f"The survey definition could not be loaded: {exc}")
        st.stop()


def secret(key: str):
    """Read one secret, tolerating the case where no secrets file exists at all.

    Streamlit raises rather than returning None when `secrets.toml` is absent, which
    would otherwise crash the app for every participant on a fresh deployment.
    """
    try:
        return st.secrets[key]
    except Exception:
        return None


def responses_csv_path() -> Path:
    """Where the local CSV backend writes. Overridable so tests and self-hosted
    deployments can point at a durable volume instead of the app directory."""
    configured = secret("responses_csv_path")
    return Path(configured) if configured else DEFAULT_CSV_PATH


def init_state() -> None:
    st.session_state.setdefault("page", 0)
    st.session_state.setdefault("started_at", time.time())
    st.session_state.setdefault("submission_id", str(uuid.uuid4()))
    st.session_state.setdefault("submitted", False)
    st.session_state.setdefault("problems", [])


# ------------------------------------------------------------- state <-> answers


def impact_key(server: Server, tool: str) -> str:
    return f"impact__{server.key}__{tool}"


def sensitivity_key(server: Server, asset: str) -> str:
    return f"sensitivity__{server.key}__{asset}"


def blast_key(server: Server, asset: str, tool: str) -> str:
    return f"blast__{server.key}__{asset}__{tool}"


def answer_widget_keys(config: SurveyConfig) -> list[str]:
    """Every session-state key that holds a participant's answer."""
    keys = [
        "participant_id",
        "email",
        "familiarity_llm_agents",
        "familiarity_mcp",
        "consent",
        "ambiguity_notes",
        "comments",
        "confidence",
    ]
    for server in config.enabled_servers:
        keys += [impact_key(server, tool.name) for tool in server.tools]
        keys += [sensitivity_key(server, asset.name) for asset in server.assets]
        keys += [blast_key(server, asset, tool) for asset, tool in server.blast_cells]
    return keys


def keep_answers_alive(config: SurveyConfig) -> None:
    """Stop Streamlit discarding the answers on wizard pages that are off screen.

    Streamlit garbage-collects the state of any widget not rendered in the current
    run, so without this every rating in the previous section is dropped the moment
    the participant moves on. Only answer keys are pinned — pinning button state too
    would let a single click re-fire on the following rerun.
    """
    for key in answer_widget_keys(config):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]


def collect_answers(config: SurveyConfig) -> dict:
    """Build the answer structure from session state, the single source of truth."""
    state = st.session_state
    answers: dict = {
        "participant_id": state.get("participant_id", ""),
        "email": state.get("email", ""),
        "familiarity_llm_agents": state.get("familiarity_llm_agents"),
        "familiarity_mcp": state.get("familiarity_mcp"),
        "consent": state.get("consent", False),
        "ambiguity_notes": state.get("ambiguity_notes", ""),
        "comments": state.get("comments", ""),
        "confidence": state.get("confidence"),
        "impact": {},
        "sensitivity": {},
        "blast": {},
    }
    for server in config.enabled_servers:
        answers["impact"][server.key] = {
            tool.name: state.get(impact_key(server, tool.name)) for tool in server.tools
        }
        answers["sensitivity"][server.key] = {
            asset.name: state.get(sensitivity_key(server, asset.name)) for asset in server.assets
        }
        answers["blast"][server.key] = {
            (asset, tool): state.get(blast_key(server, asset, tool), NOT_APPLICABLE)
            for asset, tool in server.blast_cells
        }
    return answers


# ------------------------------------------------------------------- navigation


def pages(config: SurveyConfig) -> list[tuple[str, Server | None]]:
    """Ordered wizard pages: intro, then three steps per server, then feedback."""
    plan: list[tuple[str, Server | None]] = [("intro", None)]
    for server in config.enabled_servers:
        plan += [(step, server) for step in STEPS]
    plan.append(("feedback", None))
    return plan


def validate(config: SurveyConfig, kind: str, server: Server | None) -> list[str]:
    """What is still unanswered on the given page. Read fresh from session state."""
    answers = collect_answers(config)

    if kind == "intro":
        problems = []
        if not str(answers["participant_id"]).strip():
            problems.append("Participant ID is required.")
        if answers["familiarity_llm_agents"] is None:
            problems.append("Familiarity with LLM agents is required.")
        if answers["familiarity_mcp"] is None:
            problems.append("Familiarity with MCP is required.")
        if not answers["consent"]:
            problems.append("Consent is required to take part.")
        return problems

    if kind == "feedback":
        return []

    assert server is not None
    prefix = SCALE_LABELS[kind]
    return [p for p in missing_required(config, server, answers) if p.startswith(prefix)]


def go_back() -> None:
    st.session_state.problems = []
    st.session_state.page = max(0, st.session_state.page - 1)


def go_next(config: SurveyConfig) -> None:
    """Advance, or record what is missing. Runs as a button callback, before the rerun,
    so it sees the widget values the participant just changed."""
    plan = pages(config)
    kind, server = plan[st.session_state.page]
    problems = validate(config, kind, server)
    st.session_state.problems = problems
    if problems:
        return
    if st.session_state.page == len(plan) - 1:
        submit(config)
    else:
        st.session_state.page += 1


# ------------------------------------------------------------------------ widgets


def question_card(title: str, help_text: str = "", required: bool = False):
    """A bordered white card with a Forms-style question heading."""
    card = st.container(border=True)
    with card:
        star = ' <span class="required">*</span>' if required else ""
        st.markdown(f'<div class="question-title">{title}{star}</div>', unsafe_allow_html=True)
        if help_text:
            st.markdown(f'<div class="question-help">{help_text}</div>', unsafe_allow_html=True)
    return card


def rating_radio(label: str, key: str, options=RATING_OPTIONS):
    """A horizontal radio whose value lives in session state.

    `index` is passed only when the widget is first created; afterwards the pinned
    session-state value is authoritative and passing both would conflict.
    """
    kwargs = {} if key in st.session_state else {"index": None}
    return st.radio(
        label, options=options, horizontal=True, key=key, label_visibility="collapsed", **kwargs
    )


def scale_reference(config: SurveyConfig, dimension: str) -> None:
    label = SCALE_LABELS[dimension]
    with st.expander(f"{label} levels — click to read the definitions", expanded=False):
        for level in config.scales[dimension]:
            st.markdown(f"**{level.heading}** — {level.meaning}")


def radio_grid(config: SurveyConfig, dimension: str, server: Server, items, key_fn) -> None:
    """One card per item: name, description, and a horizontal 1-5 radio."""
    for item in items:
        with st.container(border=True):
            st.markdown(f'<div class="question-title"><b>{item.name}</b></div>', unsafe_allow_html=True)
            if item.desc:
                st.markdown(f'<div class="question-help">{item.desc}</div>', unsafe_allow_html=True)
            rating_radio(f"{SCALE_LABELS[dimension]} rating for {item.name}", key_fn(server, item.name))


def blast_matrix(server: Server) -> None:
    """Asset x tool matrix. Every cell defaults to N/A — an unscored pair is a finding."""
    st.caption(
        "Each row is a virtual asset, each column a tool. Leave a cell at "
        f"**{NOT_APPLICABLE}** where that tool does not act on that asset."
    )
    with st.expander("What each asset in this matrix holds", expanded=False):
        for asset in server.blast_assets:
            st.markdown(f"**{asset.name}** — {asset.desc}")

    for asset in server.blast_assets:
        with st.container(border=True):
            st.markdown(f'<div class="question-title"><b>{asset.name}</b></div>', unsafe_allow_html=True)
            st.markdown(f'<div class="question-help">{asset.desc}</div>', unsafe_allow_html=True)
            for row_start in range(0, len(server.blast_tools), 4):
                chunk = server.blast_tools[row_start : row_start + 4]
                for column, tool in zip(st.columns(len(chunk)), chunk):
                    with column:
                        key = blast_key(server, asset.name, tool)
                        kwargs = {} if key in st.session_state else {"index": 0}
                        st.selectbox(tool, options=BLAST_OPTIONS, key=key, **kwargs)


# -------------------------------------------------------------------------- pages


def render_intro(config: SurveyConfig) -> None:
    with st.container(border=True):
        st.markdown('<div class="question-title"><b>About this study</b></div>', unsafe_allow_html=True)
        st.write(config.intro)

    with question_card("Participant ID", "Enter the participant ID provided by the researcher.", required=True):
        st.text_input("Participant ID", key="participant_id", label_visibility="collapsed")

    with question_card("Email address", "Optional. Used only if follow-up is required."):
        st.text_input("Email address", key="email", label_visibility="collapsed")

    with question_card("Familiarity with LLM agents", "1 — Not familiar · 5 — Very familiar", required=True):
        rating_radio("Familiarity with LLM agents", "familiarity_llm_agents")

    with question_card(
        "Familiarity with MCP", "1 — Never heard of it · 5 — Very familiar / have used it", required=True
    ):
        rating_radio("Familiarity with MCP", "familiarity_mcp")

    with question_card("Consent", required=True):
        st.checkbox(config.consent, key="consent")


def render_step(config: SurveyConfig, server: Server, step: str) -> None:
    with st.container(border=True):
        st.markdown(f'<div class="question-title"><b>{server.title} MCP</b></div>', unsafe_allow_html=True)
        st.write(server.scenario)

    st.markdown(f"#### {STEP_TITLES[step]}")
    st.write(config.step_prompts[step])
    scale_reference(config, step)

    if step == "impact":
        radio_grid(config, "impact", server, server.tools, impact_key)
    elif step == "sensitivity":
        st.caption("How sensitive is each of these virtual assets to this organization?")
        radio_grid(config, "sensitivity", server, server.assets, sensitivity_key)
    else:
        blast_matrix(server)


def render_feedback(config: SurveyConfig) -> None:
    with st.container(border=True):
        st.markdown('<div class="question-title"><b>Final feedback</b></div>', unsafe_allow_html=True)
        st.write("Optional comments help us find ambiguous cases and definitions worth revising.")

    with question_card(
        "Was any question difficult or ambiguous?",
        "Please mention the tool, asset, or definition and explain briefly.",
    ):
        st.text_area("Ambiguity notes", key="ambiguity_notes", label_visibility="collapsed")

    with question_card("Comments", "Optional free-text feedback."):
        st.text_area("Comments", key="comments", label_visibility="collapsed")

    with question_card("Overall confidence in your ratings", "1 — Very low · 5 — Very high"):
        rating_radio("Overall confidence in your ratings", "confidence")


# ------------------------------------------------------------------------- submit


def submit(config: SurveyConfig) -> None:
    answers = collect_answers(config)
    answers["duration_seconds"] = int(time.time() - st.session_state.started_at)

    columns = csv_columns(config)
    row = response_to_row(
        config,
        answers,
        submission_id=st.session_state.submission_id,
        submitted_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )

    storage = build_storage(st.secrets, responses_csv_path())
    try:
        storage.append(columns, row)
        st.session_state.save_error = None
    except StorageError as exc:
        # The response is never lost: it is still offered as a download below.
        st.session_state.save_error = str(exc)

    st.session_state.submitted_row = row
    st.session_state.submitted = True


def render_thank_you(config: SurveyConfig) -> None:
    st.success("Thank you — your responses have been recorded.")
    st.caption(f"Submission ID: `{st.session_state.submission_id}`")

    if st.session_state.get("save_error"):
        st.error(
            "Your answers could not be written to the central store "
            f"({st.session_state.save_error}). **Please download the file below and send "
            "it to the researcher** so your response is not lost."
        )

    row = st.session_state.submitted_row
    st.download_button(
        "Download my responses (CSV)",
        data=to_csv_bytes(csv_columns(config), [row]),
        file_name=f"mcp_survey_{row['participant_id'] or 'response'}.csv",
        mime="text/csv",
    )


# ------------------------------------------------------------------ researcher panel


def admin_authorised() -> bool:
    token = st.query_params.get("admin")
    expected = secret("admin_token")
    return bool(token and expected and hmac.compare_digest(str(token), str(expected)))


def render_admin(config: SurveyConfig) -> None:
    st.title("Researcher panel")
    storage = build_storage(st.secrets, responses_csv_path())
    st.caption(f"Backend: {storage.name}")

    warnings = lint(config)
    if warnings:
        with st.expander(f"Survey design warnings ({len(warnings)})", expanded=False):
            for warning in warnings:
                st.warning(warning)

    try:
        rows = storage.read_all()
    except StorageError as exc:
        st.error(f"Could not read responses: {exc}")
        return

    st.metric("Responses", len(rows))
    if not rows:
        st.info("No responses yet.")
        return

    st.dataframe(rows, use_container_width=True)

    st.download_button(
        "Download all responses — wide (one row per participant)",
        data=to_csv_bytes(csv_columns(config), rows),
        file_name="mcp_survey_responses_wide.csv",
        mime="text/csv",
    )
    st.download_button(
        "Download all responses — long (one row per rating)",
        data=to_csv_bytes(
            ["submission_id", "participant_id", "dimension", "server", "asset", "tool", "value"],
            long_format_rows(config, rows),
        ),
        file_name="mcp_survey_responses_long.csv",
        mime="text/csv",
    )


# ---------------------------------------------------------------------------- main


def main() -> None:
    config = get_config()
    st.set_page_config(page_title=config.title, page_icon="🛡️", layout="centered")
    st.markdown(FORM_CSS, unsafe_allow_html=True)

    if admin_authorised():
        render_admin(config)
        return

    init_state()
    keep_answers_alive(config)

    st.markdown(
        f'<div class="form-header"><h1>{config.title}</h1><p>{config.subtitle}</p></div>',
        unsafe_allow_html=True,
    )

    if st.session_state.submitted:
        render_thank_you(config)
        return

    plan = pages(config)
    index = st.session_state.page
    kind, server = plan[index]
    st.progress((index + 1) / len(plan), text=f"Section {index + 1} of {len(plan)}")

    if kind == "intro":
        render_intro(config)
    elif kind == "feedback":
        render_feedback(config)
    else:
        render_step(config, server, kind)

    if st.session_state.problems:
        bullets = "\n".join(f"- {problem}" for problem in st.session_state.problems)
        st.error("Please complete this section before continuing:\n\n" + bullets)

    st.write("")
    back, forward = st.columns(2)
    with back:
        st.button(
            "← Back",
            on_click=go_back,
            disabled=index == 0,
            use_container_width=True,
            key="nav_back",
        )
    with forward:
        st.button(
            "Submit" if index == len(plan) - 1 else "Next →",
            on_click=go_next,
            args=(config,),
            type="primary",
            use_container_width=True,
            key="nav_next",
        )


if __name__ == "__main__":
    main()
