"""End-to-end smoke tests driving the real Streamlit app with AppTest.

Note on widget selection: AppTest's element tree can retain nodes for widgets that
were rendered on an earlier wizard page and are no longer on screen. Reading such a
stale node raises. Every helper here therefore selects widgets by the key prefix of
the page under test rather than taking `app.radio` wholesale.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from survey.config import load_config

APP_PATH = Path(__file__).resolve().parents[1] / "streamlit_app.py"
CONFIG = load_config(APP_PATH.parent / "survey_config.json")


def impact_keys(server_key: str) -> list[str]:
    server = next(s for s in CONFIG.enabled_servers if s.key == server_key)
    return [f"impact__{server_key}__{tool.name}" for tool in server.tools]


def sensitivity_keys(server_key: str) -> list[str]:
    server = next(s for s in CONFIG.enabled_servers if s.key == server_key)
    return [f"sensitivity__{server_key}__{asset.name}" for asset in server.assets]


def blast_keys(server_key: str) -> list[str]:
    server = next(s for s in CONFIG.enabled_servers if s.key == server_key)
    return [f"blast__{server_key}__{asset}__{tool}" for asset, tool in server.live_blast_cells]


def run_app(**secrets) -> AppTest:
    app = AppTest.from_file(str(APP_PATH), default_timeout=60)
    for key, value in secrets.items():
        app.secrets[key] = value
    return app.run()


def click(app: AppTest, label_startswith: str) -> AppTest:
    for button in app.button:
        if button.label.startswith(label_startswith):
            return button.click().run()
    raise AssertionError(
        f"no button starting with {label_startswith!r}; have {[b.label for b in app.button]}"
    )


def errors(app: AppTest) -> str:
    return " ".join(element.value for element in app.error)


def page_text(app: AppTest) -> str:
    """All markdown on the page. The form chrome is rendered as styled HTML, not
    st.title/st.subheader, so assertions read the markdown stream."""
    return " ".join(element.value for element in app.markdown)


def set_ratings(app: AppTest, keys, value: int) -> AppTest:
    """Answer a whole rating page at once.

    Ratings are stored under plain session-state keys (the buttons write to them),
    so a test can seed them directly. `test_clicking_a_rating_button_records_it`
    covers the click path itself.
    """
    for key in keys:
        app.session_state[key] = value
    return app.run()


def complete_intro(app: AppTest, participant: str = "P01") -> AppTest:
    app.text_input[0].set_value(participant)
    app.session_state["familiarity_llm_agents"] = 4
    app.session_state["familiarity_mcp"] = 3
    app.checkbox(key="consent").check()
    return click(app.run(), "Next")


def complete_server_steps(app: AppTest, server_key: str, *, blast_value: str = "2") -> AppTest:
    """Walk one server's three steps, rating everything, leaving the app on the next page."""
    app = set_ratings(app, impact_keys(server_key), 3)
    app = click(app, "Next")
    app = set_ratings(app, sensitivity_keys(server_key), 3)
    app = click(app, "Next")
    for key in blast_keys(server_key):
        app.session_state[key] = blast_value
    return click(app.run(), "Next")


class TestIntroPage:
    def test_app_starts_without_exception(self):
        app = run_app()
        assert not app.exception
        assert "MCP Static Scanner Validation Survey" in page_text(app)

    def test_app_starts_when_no_secrets_file_exists(self):
        # A fresh deployment has no secrets.toml; reading secrets must not crash the app.
        assert not run_app().exception

    def test_next_is_blocked_until_required_fields_are_filled(self):
        app = click(run_app(), "Next")
        assert not app.exception
        assert "Participant ID is required." in errors(app)
        assert "Consent is required" in errors(app)

    def test_completing_the_intro_advances_to_the_first_server(self):
        app = complete_intro(run_app())
        assert not app.exception
        assert app.session_state["page"] == 1
        assert "Google Calendar MCP" in page_text(app)


class TestRatingSteps:
    def test_tool_impact_step_blocks_until_every_tool_is_rated(self):
        app = click(complete_intro(run_app()), "Next")
        assert "Tool Impact" in errors(app)
        assert "get-event" in errors(app)

    def test_rating_every_tool_advances_to_asset_sensitivity(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = click(app, "Next")
        assert not app.exception
        assert app.session_state["page"] == 2

    def test_blast_matrix_renders_one_cell_per_asset_tool_pair(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        app = click(app, "Next")
        cells = [b for b in app.selectbox if b.key and b.key.startswith("blast__calendar__")]
        assert len(cells) == 16  # only the live pairs are rateable
        assert all(cell.value is None for cell in cells)  # nothing preselected
        assert all("N/A" not in cell.options for cell in cells)
        # The rest of the 6x5 grid is rendered read-only.
        assert page_text(app).count('class="na-cell"') == 30 - 16

    def test_blast_matrix_is_laid_out_with_tools_as_rows_and_assets_as_columns(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        app = click(app, "Next")
        text = page_text(app)
        assert "Tool \ Virtual asset" in text
        # Column headers are the matrix assets; row headings are the tools.
        for asset in ("executive", "recruiting", "free-busy-availability"):
            assert f'class="grid-head">{asset}<' in text
        for tool in ("list-calendars", "delete-event"):
            assert f"<b>{tool}</b>" in text
        # get-current-time acts on no asset, so it has no row at all.
        assert "<b>get-current-time</b>" not in text

    def test_impact_and_sensitivity_render_as_a_single_table(self):
        app = complete_intro(run_app())
        impact_text = page_text(app)
        assert 'class="grid-head">Tool<' in impact_text
        app = set_ratings(app, impact_keys("calendar"), 3)
        sensitivity_text = page_text(click(app, "Next"))
        assert 'class="grid-head">Virtual asset<' in sensitivity_text

    def test_blast_step_blocks_until_every_cell_is_rated(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        app = click(click(app, "Next"), "Next")
        assert "16 of 16 tool/asset cells are not yet rated" in errors(app)

    def test_scoring_only_some_blast_cells_still_blocks(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        app = click(app, "Next")
        next(b for b in app.selectbox if b.key.startswith("blast__calendar__")).set_value("4")
        app = click(app.run(), "Next")
        assert "15 of 16 tool/asset cells are not yet rated" in errors(app)
        assert app.session_state["page"] == 3

    def test_scoring_every_blast_cell_unblocks_the_step(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        app = click(app, "Next")
        for box in app.selectbox:
            if box.key and box.key.startswith("blast__calendar__"):
                box.set_value("4")
        app = click(app.run(), "Next")
        assert not app.exception
        assert not errors(app)
        assert app.session_state["page"] == 4


class TestRatingButtons:
    def test_clicking_a_rating_button_records_it(self):
        app = complete_intro(run_app())
        key = impact_keys("calendar")[0]
        app = app.button(key=f"{key}__opt4").click().run()
        assert app.session_state[key] == 4

    def test_the_selected_button_is_the_primary_one(self):
        app = complete_intro(run_app())
        key = impact_keys("calendar")[0]
        app = app.button(key=f"{key}__opt4").click().run()
        selected = app.button(key=f"{key}__opt4")
        assert selected.proto.type == "primary"
        assert app.button(key=f"{key}__opt2").proto.type == "secondary"

    def test_every_rating_row_offers_five_buttons(self):
        app = complete_intro(run_app())
        keys = {b.key.rsplit("__opt", 1)[0] for b in app.button if b.key and "__opt" in b.key}
        assert keys == set(impact_keys("calendar"))
        for key in keys:
            present = [b for b in app.button if b.key and b.key.startswith(f"{key}__opt")]
            assert len(present) == 5, key


class TestAnswersSurviveNavigation:
    def test_going_back_and_forward_preserves_ratings(self):
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 4)
        app = click(app, "Next")
        app = click(app, "← Back")
        assert app.session_state["page"] == 1
        assert app.session_state["impact__calendar__get-event"] == 4
        assert app.session_state["impact__calendar__delete-event"] == 4

    def test_ratings_two_sections_back_are_not_garbage_collected(self):
        # Streamlit drops widget state for off-screen pages unless it is pinned.
        app = set_ratings(complete_intro(run_app()), impact_keys("calendar"), 5)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 2)
        app = click(app, "Next")  # now on the Blast Radius step
        assert app.session_state["impact__calendar__get-event"] == 5
        assert app.session_state["sensitivity__calendar__executive"] == 2


class TestSubmission:
    def test_full_run_persists_a_row_and_shows_the_thank_you_page(self, tmp_path):
        from survey.config import load_config

        csv_path = tmp_path / "responses.csv"
        config = load_config(APP_PATH.parent / "survey_config.json")
        app = complete_intro(run_app(responses_csv_path=str(csv_path)), participant="P42")
        for server in config.enabled_servers:
            app = complete_server_steps(app, server.key)
            assert not app.exception

        app.session_state["confidence"] = 5
        app = click(app.run(), "Submit")

        assert not app.exception
        assert app.session_state["submitted"] is True
        assert any("Thank you" in s.value for s in app.success)

        import csv

        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert len(rows) == 1
        assert rows[0]["participant_id"] == "P42"
        assert rows[0]["consent"] == "yes"
        assert rows[0]["confidence"] == "5"
        assert rows[0]["impact__calendar__get-event"] == "3"
        assert rows[0]["blast__calendar__executive__get-event"] == "2"

    def test_a_second_submission_appends_rather_than_overwriting(self, tmp_path):
        import csv

        from survey.config import load_config

        csv_path = tmp_path / "responses.csv"
        config = load_config(APP_PATH.parent / "survey_config.json")

        for participant in ("P01", "P02"):
            app = complete_intro(
                run_app(responses_csv_path=str(csv_path)), participant=participant
            )
            for server in config.enabled_servers:
                app = complete_server_steps(app, server.key)
            app = click(app, "Submit")
            assert not app.exception

        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        assert [row["participant_id"] for row in rows] == ["P01", "P02"]


class TestResearcherPanel:
    @pytest.mark.parametrize("token,expected", [("secret-token", True), ("wrong", False)])
    def test_panel_requires_the_admin_token(self, token, expected):
        app = AppTest.from_file(str(APP_PATH), default_timeout=60)
        app.secrets["admin_token"] = "secret-token"
        app.query_params["admin"] = token
        app.run()
        assert not app.exception
        assert ("Researcher panel" in [t.value for t in app.title]) is expected

    def test_panel_is_unreachable_when_no_admin_token_is_configured(self):
        app = AppTest.from_file(str(APP_PATH), default_timeout=60)
        app.query_params["admin"] = "anything"
        app.run()
        assert not app.exception
        assert "Researcher panel" not in [t.value for t in app.title]
