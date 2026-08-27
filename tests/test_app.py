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


def complete_intro(app: AppTest, participant: str = "P01", assign=("calendar",)) -> AppTest:
    """Fill the intro and start.

    `assign` pins which servers the participant gets, so tests about a specific
    server stay deterministic; the app only assigns when nothing is set yet. Pass
    `assign=None` to exercise the real balanced assignment.
    """
    app.text_input[0].set_value(participant)
    app.session_state["familiarity_llm_agents"] = 4
    app.session_state["familiarity_mcp"] = 3
    app.checkbox(key="consent").check()
    if assign is not None:
        app.session_state["assigned"] = list(assign)
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


class TestStepContext:
    """Each step gets only the context that judgement needs."""

    def _calendar_step(self, step_index: int):
        app = complete_intro(run_app(), assign=["calendar"])
        for _ in range(step_index):
            app = set_ratings(app, impact_keys("calendar"), 3)
            app = set_ratings(app, sensitivity_keys("calendar"), 3)
            app = click(app, "Next")
        return app

    def test_tool_impact_explains_the_server_not_the_organisation(self):
        text = page_text(complete_intro(run_app(), assign=["calendar"]))
        assert "About this MCP server" in text
        assert "About this organization" not in text

    def test_asset_sensitivity_explains_the_organisation_not_the_server(self):
        app = set_ratings(complete_intro(run_app(), assign=["calendar"]), impact_keys("calendar"), 3)
        text = page_text(click(app, "Next"))
        assert "About this organization" in text
        assert "About this MCP server" not in text

    def test_blast_radius_shows_both(self):
        app = set_ratings(complete_intro(run_app(), assign=["calendar"]), impact_keys("calendar"), 3)
        app = set_ratings(click(app, "Next"), sensitivity_keys("calendar"), 3)
        text = page_text(click(app, "Next"))
        assert "About this MCP server" in text
        assert "About this organization" in text

    def test_the_org_text_is_the_source_form_wording_verbatim(self):
        server = next(s for s in CONFIG.enabled_servers if s.key == "calendar")
        assert server.scenario.startswith("CBG's workplace-services team")

    def test_the_mcp_text_does_not_name_the_organisation(self):
        for server in CONFIG.enabled_servers:
            assert server.mcp_context, server.key
            assert "CBG" not in server.mcp_context, server.key


class TestServerAssignment:
    def test_a_participant_is_given_two_servers(self):
        app = complete_intro(run_app(), assign=None)
        assert len(app.session_state["assigned"]) == 2

    def test_the_wizard_only_covers_the_assigned_servers(self):
        app = complete_intro(run_app(), assign=None)
        # intro + 3 steps for each of 2 servers + feedback
        assert app.session_state["page"] == 1
        assigned = app.session_state["assigned"]
        assert len(assigned) == 2
        for server_key in assigned:
            app = complete_server_steps(app, server_key)
            assert not app.exception
        # Straight to feedback, not to a third server.
        assert any(b.label == "Submit" for b in app.button)

    def test_the_intro_says_how_many_servers_they_will_rate(self):
        assert "2 of the 5" in page_text(run_app())

    def test_the_progress_bar_projects_the_full_length_before_assignment(self):
        # The plan is only 2 pages long until a participant starts. Showing that
        # would tell them the survey is a quarter of its real length: 1 of 8, not
        # 1 of 2, so the bar reads 12% rather than 50%.
        app = run_app()
        assert not app.session_state["assigned"]
        assert app.get("progress")[0].value == int(100 / 8)

    def test_the_progress_bar_matches_the_plan_once_assigned(self):
        app = complete_intro(run_app(), assign=None)
        assert app.get("progress")[0].value == int(100 * 2 / 8)

    def test_assignment_is_recorded_with_the_response(self, tmp_path):
        import csv

        csv_path = tmp_path / "responses.csv"
        app = complete_intro(run_app(responses_csv_path=str(csv_path)), assign=None)
        assigned = list(app.session_state["assigned"])
        for server_key in assigned:
            app = complete_server_steps(app, server_key)
        app = click(app, "Submit")
        assert not app.exception

        with csv_path.open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        assert set(row["assigned_servers"].split("|")) == set(assigned)

    def test_unassigned_servers_are_blank_not_zero(self, tmp_path):
        import csv

        csv_path = tmp_path / "responses.csv"
        app = complete_intro(run_app(responses_csv_path=str(csv_path)), assign=["calendar"])
        app = complete_server_steps(app, "calendar")
        app = click(app, "Submit")

        with csv_path.open(encoding="utf-8", newline="") as handle:
            row = next(csv.DictReader(handle))
        assert row["impact__calendar__get-event"] == "3"
        assert row["impact__slack__channels_list"] == ""
        assert row["sens__github__internal-docs"] == ""

    def test_assignment_balances_against_what_is_already_stored(self, tmp_path):
        """Servers already well covered should not be handed out again."""
        import csv

        from survey.schema import csv_columns
        from survey.config import load_config

        config = load_config(APP_PATH.parent / "survey_config.json")
        csv_path = tmp_path / "responses.csv"
        columns = csv_columns(config)
        with csv_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)
            writer.writeheader()
            for n in range(6):
                writer.writerow(
                    {**{c: "" for c in columns},
                     "submission_id": f"s{n}",
                     "assigned_servers": "calendar|github"}
                )

        app = complete_intro(run_app(responses_csv_path=str(csv_path)), assign=None)
        assigned = set(app.session_state["assigned"])
        assert not (assigned & {"calendar", "github"}), assigned


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
        csv_path = tmp_path / "responses.csv"
        app = complete_intro(run_app(responses_csv_path=str(csv_path)), participant="P42")
        for server_key in app.session_state["assigned"]:
            app = complete_server_steps(app, server_key)
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

        csv_path = tmp_path / "responses.csv"

        for participant in ("P01", "P02"):
            app = complete_intro(
                run_app(responses_csv_path=str(csv_path)), participant=participant
            )
            for server_key in app.session_state["assigned"]:
                app = complete_server_steps(app, server_key)
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
