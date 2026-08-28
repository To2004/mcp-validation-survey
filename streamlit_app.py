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

from survey.assignment import choose_servers, format_assigned, parse_assigned
from survey.config import ConfigError, Server, SurveyConfig, lint, load_config
from survey.schema import (
    UNSURE,
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
# Display names come from the config so they can be changed without touching code.
FALLBACK_LABELS = {
    "impact": "Action Impact",
    "sensitivity": "Asset Confidentiality",
    "blast": "Consequence Scope",
}
STEP_NUMBER = {"impact": 1, "sensitivity": 2, "blast": 3}


def scale_label(config: SurveyConfig, dimension: str) -> str:
    return config.scale_labels.get(dimension, FALLBACK_LABELS[dimension])


def step_title(config: SurveyConfig, dimension: str) -> str:
    return f"Step {STEP_NUMBER[dimension]} — {scale_label(config, dimension)}"
BLAST_OPTIONS = ["1", "2", "3", "4", "5", UNSURE]
RATING_LABEL_WIDTH = 3.2
UNSURE_WIDTH = 1.5
RATING_OPTIONS = [1, 2, 3, 4, 5]

FORM_CSS = """
<style>
  :root {
      --accent: #2563eb;
      --ink: #0f172a;
      --ink-soft: #475569;
      --line: #d8e0ec;
      --zebra: #f8fafc;
  }
  .stApp { background: #eef2f7; }
  .block-container { max-width: 1280px; padding: 1.5rem 1.5rem 4rem 1.5rem; }
  html, body, [class*="css"] { color: var(--ink); }

  div[data-testid="stVerticalBlockBorderWrapper"] {
      background: #ffffff;
      border: 1px solid var(--line) !important;
      border-radius: 10px;
      padding: 10px 18px;
  }
  .form-header {
      background: #ffffff;
      border: 1px solid var(--line);
      border-top: 8px solid var(--accent);
      border-radius: 10px;
      padding: 24px 28px 20px 28px;
      margin-bottom: 16px;
  }
  .form-header h1 { margin: 0 0 8px 0; font-size: 32px; font-weight: 600; color: var(--ink); }
  .form-header p  { margin: 0; color: var(--ink-soft); font-size: 16px; }
  .required { color: #d93025; }

  .question-title { font-size: 19px; font-weight: 600; color: var(--ink); margin-bottom: 4px; }
  .row-name { font-size: 18px; font-weight: 600; color: var(--ink); margin: 2px 0 4px 0; }
  .question-help {
      font-size: 16px;
      line-height: 1.55;
      color: var(--ink-soft);
      background: #f1f5f9;
      border-left: 4px solid var(--accent);
      padding: 10px 14px;
      border-radius: 4px;
      margin: 4px 0 8px 0;
  }
  .level-def {
      font-size: 16px;
      line-height: 1.6;
      color: var(--ink-soft);
      background: #f8fafc;
      border-left: 4px solid var(--accent);
      padding: 12px 16px;
      border-radius: 4px;
      margin-bottom: 8px;
  }
  .level-def b { color: var(--accent); }
  .level-example {
      font-size: 14px;
      color: #64748b;
      padding: 3px 0 0 16px;
      position: relative;
  }
  .level-example::before {
      content: "–";
      position: absolute;
      left: 2px;
  }
  .howto {
      background: #eff6ff;
      border: 1px solid #bfdbfe;
      border-radius: 8px;
      padding: 14px 18px;
      margin: 12px 0 16px 0;
      font-size: 16px;
      line-height: 1.6;
      color: #1e3a8a;
  }
  .howto b { color: #1e40af; }

  /* ---- rating grid ----
     One Streamlit column per scale point, so the buttons align with the header
     by construction. No dependence on the internals of any widget. */
  .grid-head {
      font-size: 13px;
      font-weight: 700;
      color: var(--ink-soft);
      text-transform: uppercase;
      letter-spacing: .6px;
      padding: 10px 0 6px 0;
  }
  .scale-num {
      text-align: center;
      font-size: 17px;
      font-weight: 700;
      color: var(--ink);
      padding: 8px 2px 6px 2px;
      line-height: 1.2;
  }
  .scale-num small {
      display: block;
      font-size: 12px;
      font-weight: 500;
      color: var(--ink-soft);
      line-height: 1.3;
      min-height: 1.3em;
  }
  /* Rating buttons: circular, large enough to be an easy target. */
  div[data-testid="stButton"] > button {
      border-radius: 999px;
      font-size: 17px;
      font-weight: 600;
      min-height: 46px;
      border: 2px solid var(--line);
      transition: none;
  }
  div[data-testid="stButton"] > button:hover {
      border-color: var(--accent);
      color: var(--accent);
      background: #eff6ff;
  }

  /* Row separators and faint zebra striping on grid rows. */
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"] {
      align-items: center;
      border-top: 1px solid var(--line);
      padding: 6px 0;
  }
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"]:nth-of-type(even) {
      background: var(--zebra);
  }
  div[data-testid="stVerticalBlockBorderWrapper"] div[data-testid="stHorizontalBlock"]:first-of-type {
      border-top: none;
  }

  /* Text fields: a real border and a focus ring, so it is obvious where to type. */
  div[data-testid="stTextInput"] div[data-baseweb="input"],
  div[data-testid="stTextArea"] div[data-baseweb="textarea"],
  div[data-testid="stTextArea"] div[data-baseweb="base-input"] {
      background: #ffffff !important;
      border: 1px solid #b9c4d4 !important;
      border-radius: 6px !important;
  }
  div[data-testid="stTextInput"] div[data-baseweb="input"]:focus-within,
  div[data-testid="stTextArea"] div[data-baseweb="textarea"]:focus-within,
  div[data-testid="stTextArea"] div[data-baseweb="base-input"]:focus-within {
      border-color: var(--accent) !important;
      box-shadow: 0 0 0 3px rgba(37, 99, 235, 0.15) !important;
  }
  div[data-testid="stTextInput"] input,
  div[data-testid="stTextArea"] textarea {
      background: transparent !important;
      font-size: 16px !important;
  }

  .rule-line {
      font-size: 15px;
      line-height: 1.5;
      color: var(--ink-soft);
      padding: 4px 0 4px 18px;
      position: relative;
  }
  .rule-line::before { content: "•"; position: absolute; left: 4px; color: var(--accent); }

  .na-cell {
      text-align: center;
      color: #94a3b8;
      background: #f1f5f9;
      border: 1px dashed var(--line);
      border-radius: 6px;
      padding: 11px 0;
      font-size: 14px;
      letter-spacing: .5px;
  }
  .stProgress > div > div > div > div { background-color: var(--accent); }
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
    st.session_state.setdefault("assigned", [])


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
    for server in assigned_servers(config):
        keys += [impact_key(server, tool.name) for tool in server.tools]
        keys += [sensitivity_key(server, asset.name) for asset in server.assets]
        keys += [blast_key(server, asset, tool) for asset, tool in server.live_blast_cells]
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
        "assigned_servers": list(state.get("assigned", [])),
        "impact": {},
        "sensitivity": {},
        "blast": {},
    }
    for server in assigned_servers(config):
        answers["impact"][server.key] = {
            tool.name: state.get(impact_key(server, tool.name)) for tool in server.tools
        }
        answers["sensitivity"][server.key] = {
            asset.name: state.get(sensitivity_key(server, asset.name)) for asset in server.assets
        }
        answers["blast"][server.key] = {
            (asset, tool): state.get(blast_key(server, asset, tool))
            for asset, tool in server.live_blast_cells
        }
    return answers


# ------------------------------------------------------------------- navigation


def assigned_servers(config: SurveyConfig) -> list[Server]:
    """The servers this participant was given. Empty until they start."""
    keys = st.session_state.get("assigned", [])
    by_key = {server.key: server for server in config.enabled_servers}
    return [by_key[key] for key in keys if key in by_key]


def assign_servers(config: SurveyConfig) -> None:
    """Give this participant a balanced subset of the servers, once per session.

    Counts come from the responses already stored, so coverage evens out as the
    study runs. If the backend cannot be read we fall back to an unweighted draw
    rather than blocking the participant - a slightly lumpy assignment beats a
    survey that will not start.
    """
    if st.session_state.get("assigned"):
        return
    try:
        counts = build_storage(st.secrets, responses_csv_path()).server_counts()
    except Exception:
        counts = {}
    chosen = choose_servers(
        config.enabled_servers, counts, config.servers_per_participant
    )
    st.session_state.assigned = [server.key for server in chosen]


def pages(config: SurveyConfig) -> list[tuple[str, Server | None]]:
    """Ordered wizard pages: intro, then three steps per assigned server, then feedback."""
    plan: list[tuple[str, Server | None]] = [("intro", None)]
    for server in assigned_servers(config):
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
    # Filter by dimension key, never by the display label: two dimensions sharing
    # a label would make a page impossible to pass.
    return missing_required(config, server, answers, dimension=kind)


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
    if kind == "intro":
        # Assign before advancing, so the page plan below already includes the
        # participant's servers.
        assign_servers(config)
        plan = pages(config)
    if st.session_state.page == len(plan) - 1:
        submit(config)
    else:
        st.session_state.page += 1


# ------------------------------------------------------------------------ widgets


def simple_scale(key: str, low_label: str, high_label: str) -> None:
    """A standalone 1-5 scale: numbers spread across five columns, ends named."""
    current = st.session_state.get(key)
    columns = st.columns(5)
    for index, (column, value) in enumerate(zip(columns, RATING_OPTIONS)):
        with column:
            anchor = low_label if index == 0 else (high_label if index == 4 else "")
            st.markdown(
                f'<div class="scale-num">{value}<small>{anchor}</small></div>',
                unsafe_allow_html=True,
            )
            st.button(
                str(value),
                key=f"{key}__opt{value}",
                type="primary" if current == value else "secondary",
                on_click=set_rating,
                args=(key, value),
                use_container_width=True,
            )


def question_card(title: str, help_text: str = "", required: bool = False):
    """A bordered white card with a Forms-style question heading."""
    card = st.container(border=True)
    with card:
        star = ' <span class="required">*</span>' if required else ""
        st.markdown(f'<div class="question-title">{title}{star}</div>', unsafe_allow_html=True)
        if help_text:
            st.markdown(f'<div class="question-help">{help_text}</div>', unsafe_allow_html=True)
    return card


def set_rating(key: str, value: int) -> None:
    st.session_state[key] = value


def rating_cells(key: str, levels) -> None:
    """One column per scale point, so alignment is Streamlit's job, not CSS's.

    Buttons rather than a radio group: a horizontal `st.radio` lays its options out
    at their natural width, which cannot be made to line up under a column header
    reliably. The selected one is rendered in the accent colour. No tooltip - a
    hover card popping up over the row above it obscured the grid; the level
    definitions live in the expander at the top of the step instead.
    """
    current = st.session_state.get(key)
    for column, level in zip(st.columns(len(levels)), levels):
        with column:
            st.button(
                str(level.value),
                key=f"{key}__opt{level.value}",
                type="primary" if current == level.value else "secondary",
                on_click=set_rating,
                args=(key, level.value),
                use_container_width=True,
            )


def grid_widths(levels) -> list:
    """Label column, one column per level, then the Not sure column."""
    return [RATING_LABEL_WIDTH] + [1] * len(levels) + [UNSURE_WIDTH]


def scale_header(levels, first_column_label: str) -> None:
    """Header row for a rating grid: the numbers, with both ends named."""
    columns = st.columns(grid_widths(levels))
    columns[0].markdown(
        f'<div class="grid-head">{first_column_label}</div>', unsafe_allow_html=True
    )
    for column, level in zip(columns[1:], levels):
        # Label every level, not just the ends: unlabelled middle numbers turn a
        # defined ordinal rubric into a bare intensity scale.
        anchor = f"<small>{level.label}</small>"
        column.markdown(
            f'<div class="scale-num">{level.value}{anchor}</div>', unsafe_allow_html=True
        )
    columns[-1].markdown(
        '<div class="scale-num">?<small>not sure</small></div>', unsafe_allow_html=True
    )


HOWTO = {
    "impact": (
        "<b>How to answer:</b> each row is one tool. Click one number per row — the "
        "column number is the Action Impact level. Open <i>Tool Impact levels</i> above "
        "for the definitions. Judge each tool on its own, not against the others; "
        "levels may repeat. If you cannot judge one, click <b>Not sure</b> rather than "
        "guessing."
    ),
    "sensitivity": (
        "<b>How to answer:</b> each row is one virtual asset. Click one number per row "
        "— the column number is the Asset Confidentiality level. Judge each asset on its "
        "own; levels may repeat. If you cannot judge one, click <b>Not sure</b> rather "
        "than guessing."
    ),
    "blast": (
        "<b>How to answer:</b> each row is a tool, each column a virtual asset. Choose "
        "1–5 in every open cell, or <b>not sure</b> if you cannot judge it. Cells "
        "shown as <b>N/A</b> are pairs the tool does not act on — they are fixed and "
        "need no answer."
    ),
}


def how_to_answer(dimension: str) -> None:
    st.markdown(f'<div class="howto">{HOWTO[dimension]}</div>', unsafe_allow_html=True)


def scale_reference(config: SurveyConfig, dimension: str) -> None:
    label = scale_label(config, dimension)
    # Open by default: a participant who never expands this is answering a bare
    # 1-5 intensity scale, which is not the same instrument the scanner applies.
    with st.expander(f"{label} levels", expanded=True):
        for level in config.scales[dimension]:
            # Examples carry most of the weight at the boundaries: "major change" is
            # hard to place, "creates or replaces a resource" is not.
            examples = "".join(
                f'<div class="level-example">{example}</div>' for example in level.examples
            )
            st.markdown(
                f'<div class="level-def"><b>{level.heading}</b> — {level.meaning}'
                f"{examples}</div>",
                unsafe_allow_html=True,
            )
        rules = config.scale_rules.get(dimension, [])
        if rules:
            st.markdown("**Rules**")
            for rule in rules:
                st.markdown(f'<div class="rule-line">{rule}</div>', unsafe_allow_html=True)


def radio_grid(config: SurveyConfig, dimension: str, server: Server, items, key_fn, noun: str) -> None:
    """One table: a row per item, five rating columns, header and rows sharing a spec."""
    levels = config.scales[dimension]
    widths = grid_widths(levels)

    with st.container(border=True):
        scale_header(levels, noun)
        for item in items:
            row = st.columns(widths)
            with row[0]:
                st.markdown(
                    f'<div class="row-name">{item.name}</div>', unsafe_allow_html=True
                )
                if item.desc:
                    st.markdown(f'<div class="question-help">{item.desc}</div>', unsafe_allow_html=True)
            key = key_fn(server, item.name)
            current = st.session_state.get(key)
            for column, level in zip(row[1:], levels):
                with column:
                    st.button(
                        str(level.value),
                        key=f"{key}__opt{level.value}",
                        type="primary" if current == level.value else "secondary",
                        on_click=set_rating,
                        args=(key, level.value),
                        use_container_width=True,
                    )
            # "Not sure" is a real answer, not a skip: a participant who cannot
            # judge an item tells us something a forced guess would hide.
            with row[-1]:
                st.button(
                    "Not sure",
                    key=f"{key}__opt{UNSURE}",
                    type="primary" if current == UNSURE else "secondary",
                    on_click=set_rating,
                    args=(key, UNSURE),
                    use_container_width=True,
                )


def blast_matrix(server: Server) -> None:
    """Tool x asset matrix: a row per tool, a column per virtual asset.

    Only pairs the tool actually acts on are rateable; the rest are read-only N/A.
    Live cells start unset, so an unanswered cell stays distinguishable from a
    deliberate 1.
    """
    with st.expander("What each virtual asset holds", expanded=False):
        for asset in server.blast_assets:
            st.markdown(
                f'<div class="level-def"><b>{asset.name}</b> — {asset.desc}</div>',
                unsafe_allow_html=True,
            )

    description_of = {tool.name: tool.desc for tool in server.tools}
    widths = [3] + [2] * len(server.blast_assets)

    with st.container(border=True):
        header = st.columns(widths)
        header[0].markdown('<div class="grid-head">Tool \\ Virtual asset</div>', unsafe_allow_html=True)
        for column, asset in zip(header[1:], server.blast_assets):
            column.markdown(f'<div class="grid-head">{asset.name}</div>', unsafe_allow_html=True)

        for tool in server.blast_tools:
            row = st.columns(widths)
            with row[0]:
                st.markdown(f'<div class="question-title"><b>{tool}</b></div>', unsafe_allow_html=True)
                if description_of.get(tool):
                    st.markdown(
                        f'<div class="question-help">{description_of[tool]}</div>',
                        unsafe_allow_html=True,
                    )
            for column, asset in zip(row[1:], server.blast_assets):
                with column:
                    if not server.is_live(asset.name, tool):
                        st.markdown('<div class="na-cell">N/A</div>', unsafe_allow_html=True)
                        continue
                    key = blast_key(server, asset.name, tool)
                    kwargs = {} if key in st.session_state else {"index": None}
                    st.selectbox(
                        f"{tool} acting on {asset.name}",
                        options=BLAST_OPTIONS,
                        key=key,
                        label_visibility="collapsed",
                        placeholder="—",
                        format_func=lambda value: (
                            "not sure" if value == UNSURE else value
                        ),
                        **kwargs,
                    )


# -------------------------------------------------------------------------- pages


def render_intro(config: SurveyConfig) -> None:
    with st.container(border=True):
        st.markdown('<div class="question-title"><b>About this study</b></div>', unsafe_allow_html=True)
        st.write(config.intro)

    with question_card("Participant ID", "Enter the participant ID provided by the researcher.", required=True):
        st.text_input("Participant ID", key="participant_id", label_visibility="collapsed")

    with question_card("Email address", "Optional. Used only if follow-up is required."):
        st.text_input("Email address", key="email", label_visibility="collapsed")

    with question_card("Familiarity with LLM agents", required=True):
        simple_scale("familiarity_llm_agents", "Not familiar", "Very familiar")

    with question_card("Familiarity with MCP", required=True):
        simple_scale("familiarity_mcp", "Never heard of it", "Very familiar / used it")

    with question_card("Consent", required=True):
        st.checkbox(config.consent, key="consent")


# Which context each step needs. Tool Impact is a judgement about the tool itself,
# so the organisation is a distraction there; Asset Sensitivity is entirely about
# what the data means to this organisation; Blast Radius needs both, since it is
# the reach of a tool over an asset.
STEP_CONTEXT = {
    "impact": ("mcp",),
    "sensitivity": ("org",),
    "blast": ("mcp", "org"),
}
CONTEXT_LABELS = {"mcp": "About this MCP server", "org": "About this organization"}


def render_context(server: Server, step: str) -> None:
    for kind in STEP_CONTEXT[step]:
        text = server.mcp_context if kind == "mcp" else server.scenario
        if not text:
            continue
        with st.container(border=True):
            st.markdown(
                f'<div class="question-title"><b>{server.title} MCP — '
                f'{CONTEXT_LABELS[kind]}</b></div>',
                unsafe_allow_html=True,
            )
            st.write(text)


def render_step(config: SurveyConfig, server: Server, step: str) -> None:
    render_context(server, step)

    st.markdown(f"#### {step_title(config, step)}")
    st.write(config.step_prompts[step])
    scale_reference(config, step)

    how_to_answer(step)

    if step == "impact":
        radio_grid(config, "impact", server, server.tools, impact_key, "Tool")
    elif step == "sensitivity":
        st.caption("How sensitive is each of these virtual assets to this organization?")
        radio_grid(config, "sensitivity", server, server.assets, sensitivity_key, "Virtual asset")
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

    with question_card("Overall confidence in your ratings"):
        simple_scale("confidence", "Very low", "Very high")


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
    # An assignment can shrink the plan (or be missing on a restored session);
    # never index past the end.
    index = min(st.session_state.page, len(plan) - 1)
    st.session_state.page = index
    kind, server = plan[index]
    # Before assignment the plan is just intro + feedback, which would tell the
    # participant there are 2 sections when there will be 8. Project the real total.
    if st.session_state.get("assigned"):
        total = len(plan)
    else:
        per = min(config.servers_per_participant, len(config.enabled_servers))
        total = 2 + len(STEPS) * per
    st.progress((index + 1) / total, text=f"Section {index + 1} of {total}")

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
