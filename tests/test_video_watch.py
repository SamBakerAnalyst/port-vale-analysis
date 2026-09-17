"""Player Reports — team sheets plus notes shared with Scoutable Teams and the player page."""

from __future__ import annotations

import app.main  # noqa: F401 - initialise the app so the router imports resolve

from app.apps_manifest import APPS, LIVE_ESSENTIAL_IDS, required_sidebar_titles
from app.paths import STANDALONE_DIR
from app import player_dossier as dossier
from app import scoutable_teams as st
from app import video_watch as vw
from app import player_reports as reports
from app import who_to_scout as wts
from app.player_dossier import PlayerNoteCreate


def test_sheet_player_gets_a_position_short_code():
    row = vw._decorate_sheet_player(
        {
            "player_id": 1,
            "name": "Test Player",
            "position": "CENTER_FORWARD",
            "position_label": "Centre-forward",
            "overall": 66,
        },
        club="Bohemian FC",
    )
    assert row["position_short"] == "CF"


def test_video_watch_is_a_recruitment_rail_tool():
    titles = required_sidebar_titles()
    assert "Player Reports" in titles
    row = next(app for app in APPS if app["id"] == "video-watch")
    assert row["title"] == "Player Reports"
    assert row["href"] == "/player-reports"
    assert row["group"] == "recruitment"
    assert row.get("sidebar") is not False
    assert "scouts" in tuple(row["roles"])
    assert row["router"] == "video_watch"
    assert "/player-reports" in tuple(row["api_prefixes"])
    assert "/video-watch" in tuple(row["api_prefixes"])
    assert "/api/video-watch" in tuple(row["api_prefixes"])
    assert row["id"] in LIVE_ESSENTIAL_IDS


def test_page_has_both_sheets_and_a_central_profile():
    html = (STANDALONE_DIR / "video-watch.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "video-watch.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "video-watch.js").read_text(encoding="utf-8")
    assert "Player Reports" in html
    assert "Which league are you watching?" in html
    assert 'id="vwLeagues"' in html
    assert 'id="vwFixtures"' in html
    assert 'id="vwHome"' in html
    assert 'id="vwAway"' in html
    assert 'id="vwCenter"' in html
    assert 'id="vwProfile"' in html
    assert "/api/video-watch/games" in js
    assert "/api/video-watch/fixture" in js
    assert "/api/video-watch/player" in js
    assert "/api/video-watch/notes" in js
    assert "/api/video-watch/general-report" in js
    assert "/api/video-watch/detailed-report" in js
    assert "/api/video-watch/cms" in js
    assert "Must watch" in js
    assert "Worth a look" in js
    assert "watchPct" in js
    assert "/api/pre-match/player-photo" in js
    assert 'data-tab="${id}"' in js
    assert '["general", "General report"]' in js
    assert '["detailed", "Detailed report"]' in js
    assert '["cms", "Player CMS"]' in js
    assert "Player notes" in js
    assert "General report" in js
    assert "Detailed report" in js
    assert "Player CMS" in js
    assert "Match conditions" in js or "Weather conditions" in js
    assert "Home / Away" in js
    assert "auto from match title" in js
    assert "Position in game" in js
    assert "Physical" in js
    assert "Weak foot" in js
    assert "Data profiles" in js
    assert "Psychology" in js
    assert "PVFC player level" in js
    assert "Next action" in js
    assert "Add to pipeline" in js
    assert "How do they progress the ball" in js
    assert "What sort of headers do they win" in js
    assert "Scoutable Teams" in js
    assert "Who to Scout" in js
    assert "player page" in js
    assert "vw-leagues" in css
    assert "vw-row__teams" in css
    assert "vw-photo-wrap" in css
    assert "vw-pitch" in css
    assert "vw-tip" in css
    assert "flagcdn.com" in js
    assert "leaguelogo" in js
    assert "--bg: #0a0c10" in css
    assert "scoreTone" in js
    assert "positionShort" in js
    assert "shirtNo" in js
    assert "function loadGames" in js
    assert "Building the fixture list" in js
    assert "Could not load fixtures" in js
    assert "gamesReady" in js
    assert "setSort" in js
    assert "data-sort=" in js
    assert '["date", "Date"]' in js
    assert '["match", "Match"]' in js
    assert '["watch", "Watch score"]' in js
    assert "Watch score" in js
    assert "vw-cols" in css
    assert "border-radius: 12px" in css
    assert "assignFormation" in js
    assert "Team sheet" in js
    assert "Starting XI" in js
    assert "Substitutes" in js
    assert "hasMatchLineup" in js
    assert "who started and who came on" in js
    assert "4-3-3" in js
    assert "vw-field" in css
    assert "vw-dot" in css
    assert "grid-template-columns: minmax(270px, 1fr) minmax(340px, 1.45fr) minmax(270px, 1fr)" in css


def test_who_to_scout_shows_the_shared_scout_comment():
    js = (STANDALONE_DIR.parent / "static" / "who-to-scout.js").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "who-to-scout.css").read_text(encoding="utf-8")
    py = (STANDALONE_DIR.parent / "app" / "who_to_scout.py").read_text(encoding="utf-8")
    assert "scout_comment" in js
    assert "scout-player-note" in js
    assert "scout-note-mark" in css
    assert "_attach_recruitment_notes" in py


def _patch_note_stores(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(st, "SCOUT_NOTES_PATH", tmp_path / "scoutable-teams-notes.json")
    monkeypatch.setattr(st, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(dossier, "PLAYER_NOTES_PATH", tmp_path / "player-notes.json")
    monkeypatch.setattr(dossier, "DATA_ROOT", tmp_path)


def test_shared_comment_stamps_onto_who_to_scout_rows(tmp_path, monkeypatch):
    _patch_note_stores(tmp_path, monkeypatch)
    st.save_scout_notes(
        player_id=42,
        scout_scores={},
        scout_comment="Left footer, late runner.",
        staff="Dan",
    )
    players = [{"playerId": 42, "name": "Test Player"}, {"playerId": 7, "name": "Other"}]
    wts._attach_recruitment_notes(players)
    assert players[0]["scout_comment"] == "Left footer, late runner."
    assert players[0]["has_scout_note"] is True
    assert players[1]["has_scout_note"] is False


def test_video_watch_note_writes_to_both_stores(tmp_path, monkeypatch):
    _patch_note_stores(tmp_path, monkeypatch)
    monkeypatch.setattr(vw, "_pipeline_for_player", lambda _pid: None)
    monkeypatch.setattr(vw, "_real_activity", lambda pid, name: {
        "notes": dossier._notes_for_player(pid),
        "reports": [],
        "ability": None,
    })

    saved = vw.save_video_watch_entry(
        player_id=99,
        kind="comment",
        text="Quick feet in the box.",
        fixture_label="Bradford vs Vale",
        match_minute=23,
        staff="Dan",
        name="Test Player",
        club="Bradford",
        league="League Two",
        position="CENTER_FORWARD",
        position_label="ST",
        age=22,
    )
    assert saved["ok"] is True
    assert saved["scout_comment"] == "Quick feet in the box."
    assert st.scout_notes_for_player(99)["scout_comment"] == "Quick feet in the box."
    notes = dossier._notes_for_player(99)
    assert notes
    assert notes[0]["summary"] == "Quick feet in the box."
    assert "Bradford vs Vale" in str(notes[0]["fixture"])
    assert "23'" in str(notes[0]["fixture"])


def test_video_watch_report_is_a_player_page_report(tmp_path, monkeypatch):
    _patch_note_stores(tmp_path, monkeypatch)
    monkeypatch.setattr(vw, "_pipeline_for_player", lambda _pid: None)

    def _activity(pid, name):
        payload = dossier._activity_payload(pid, name)
        return {
            "notes": [row for row in payload["notes"] if not row.get("example")],
            "reports": [row for row in payload["reports"] if not row.get("example")],
            "ability": payload.get("ability"),
        }

    monkeypatch.setattr(vw, "_real_activity", _activity)
    saved = vw.save_video_watch_entry(
        player_id=12,
        kind="report",
        text="Can hold the ball up against League Two centre halves.",
        title="Video report · Grimsby",
        staff="Dan",
        name="Another Player",
        current_ability=3,
        potential_ability=4,
    )
    assert saved["note"]["kind"] == "report"
    reports = [
        row
        for row in dossier._notes_for_player(12)
        if row.get("kind") == "report"
    ]
    assert reports
    assert reports[0]["current_ability"] == 3
    assert st.scout_notes_for_player(12)["scout_comment"].startswith("Can hold the ball")


def test_infer_formation_follows_the_squad_shape():
    defenders = [
        {
            "player_id": index,
            "name": f"Player {index}",
            "position": position,
            "position_label": label,
            "minutes": 900,
            "overall": 60,
        }
        for index, (position, label) in enumerate(
            [
                ("GOALKEEPER", "Goalkeeper"),
                ("CENTRAL_DEFENDER", "Centre-back"),
                ("CENTRAL_DEFENDER", "Centre-back"),
                ("CENTRAL_DEFENDER", "Centre-back"),
                ("LEFT_WINGBACK_DEFENDER", "Left back"),
                ("RIGHT_WINGBACK_DEFENDER", "Right back"),
                ("DEFENSE_MIDFIELD", "Defensive midfield"),
                ("CENTRAL_MIDFIELD", "Central midfield"),
                ("CENTRAL_MIDFIELD", "Central midfield"),
                ("CENTER_FORWARD", "Centre-forward"),
                ("CENTER_FORWARD", "Centre-forward"),
            ],
            start=1,
        )
    ]
    assert vw.infer_watch_formation(defenders) == "5-3-2"
    assert vw.infer_watch_formation(
        [
            {
                "player_id": 1,
                "position": "LEFT_WINGER",
                "position_label": "Left winger",
                "minutes": 800,
                "overall": 62,
            },
            {
                "player_id": 2,
                "position": "RIGHT_WINGER",
                "position_label": "Right winger",
                "minutes": 800,
                "overall": 61,
            },
            {
                "player_id": 3,
                "position": "CENTER_FORWARD",
                "position_label": "Centre-forward",
                "minutes": 900,
                "overall": 70,
            },
        ]
    ) == "4-3-3"


def test_watch_formation_fills_eleven_slots_in_order():
    players = [
        {
            "player_id": index,
            "name": f"Player {index}",
            "position": position,
            "minutes": 900 - index,
            "overall": 70 - index,
        }
        for index, position in enumerate(
            [
                "GOALKEEPER",
                "LEFT_WINGBACK_DEFENDER",
                "CENTRAL_DEFENDER",
                "CENTRAL_DEFENDER",
                "RIGHT_WINGBACK_DEFENDER",
                "DEFENSE_MIDFIELD",
                "CENTRAL_MIDFIELD",
                "CENTRAL_MIDFIELD",
                "LEFT_WINGER",
                "CENTER_FORWARD",
                "RIGHT_WINGER",
                "ATTACKING_MIDFIELD",
            ],
            start=1,
        )
    ]
    team = vw.attach_watch_formation({"players": players}, "4-3-3")
    assert team["formation"] == "4-3-3"
    assert len(team["xi"]) == 11
    assert {row["formation_slot"] for row in team["xi"]} >= {
        "GOALKEEPER",
        "CENTER_FORWARD",
        "LEFT_WINGER",
        "RIGHT_WINGER",
    }
    assert all(row.get("x_pct") is not None and row.get("y_pct") is not None for row in team["xi"])
    assert len(team["bench"]) == 1


def test_match_lineup_does_not_keep_unused_squad_names():
    team = vw.attach_watch_formation(
        {
            "formation": "4-3-3",
            "players": [
                {"player_id": 1, "name": "Jack Byecroft", "position": "GOALKEEPER", "started": True},
                {"player_id": 2, "name": "Ethan Brierley", "position": "LEFT_WINGER", "subbed_on": True},
                {"player_id": 99, "name": "Jayden Wareham", "position": "CENTER_FORWARD", "overall": 57},
            ],
        }
    )
    assert [row["name"] for row in team["xi"]] == ["Jack Byecroft"]
    assert [row["name"] for row in team["bench"]] == ["Ethan Brierley"]
    assert all(row["name"] != "Jayden Wareham" for row in team["xi"] + team["bench"])


def test_create_player_note_shape_still_feeds_the_watch_desk():
    note = PlayerNoteCreate(kind="note", summary="hello", title="Video look")
    assert note.kind == "note"
    assert note.summary == "hello"


def test_home_away_comes_from_the_match_title():
    parsed = reports.parse_fixture_sides("Barnet vs Accrington Stanley")
    assert parsed == ("Barnet", "Accrington Stanley")
    away = reports.infer_home_away(
        club="Accrington Stanley",
        fixture_label="Barnet vs Accrington Stanley",
    )
    assert away["side"] == "away"
    assert away["label"] == "Away"
    assert away["source"] == "match title"
    home = reports.infer_home_away(
        club="Barnet",
        fixture_label="Barnet vs Accrington Stanley",
    )
    assert home["side"] == "home"
    assert home["source"] == "match title"


def test_team_sheet_side_wins_over_the_title():
    row = reports.infer_home_away(
        club="Accrington Stanley",
        fixture_label="Barnet vs Accrington Stanley",
        sheet_side="home",
    )
    assert row["side"] == "home"
    assert row["source"] == "team sheet"


def test_match_conditions_are_shared_across_players_on_the_same_game(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    first = reports.save_match_conditions(
        fixture_id="barnet-accrington-1",
        fixture_label="Barnet vs Accrington Stanley",
        weather="light-rain",
        pitch="soft",
        weather_note="Wind at the away end",
        staff="Dan",
    )
    assert first["filled"] is True
    assert first["weather_label"] == "Light rain"
    loaded = reports.match_conditions_for_fixture(
        "barnet-accrington-1",
        fixture_label="Barnet vs Accrington Stanley",
    )
    assert loaded["weather"] == "light-rain"
    assert loaded["pitch"] == "soft"
    assert loaded["weather_note"] == "Wind at the away end"
    other = reports.report_file_for_player(
        player_id=922,
        club="Accrington Stanley",
        fixture_id="barnet-accrington-1",
        fixture_label="Barnet vs Accrington Stanley",
    )
    assert other["match_conditions"]["weather"] == "light-rain"
    assert other["home_away"]["side"] == "away"


def test_player_cms_persists_agent_and_contract(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    monkeypatch.setattr(reports, "_cached_contract_expires", lambda name, club: "Jun 30, 2027")
    saved = reports.save_cms(
        player_id=922,
        agent_name="Unique Sports",
        agent_notes="Spoke Tuesday.",
        contract_expires="Jun 2027",
        staff="Dan",
        name="Connor O'Brien",
        club="Accrington Stanley",
    )
    assert saved["filled"] is True
    loaded = reports.cms_for_player(922, name="Connor O'Brien", club="Accrington Stanley")
    assert loaded["agent_name"] == "Unique Sports"
    assert loaded["contract_expires"] == "Jun 2027"
    assert loaded["contract_expires_source"] == "Jun 30, 2027"


def test_general_report_saves_player_notes_on_the_fixture(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    reports.save_general_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        notes="Comfortable at RWB.",
        staff="Dan",
    )
    row = reports.general_report_for_player(922, "barnet-accrington-1")
    assert row["notes"] == "Comfortable at RWB."
    empty = reports.general_report_for_player(7, "barnet-accrington-1")
    assert empty["filled"] is False


def test_general_report_keeps_physical_and_profile_notes(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    saved = reports.save_general_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        position_in_game="RIGHT_WINGBACK_DEFENDER",
        physical={"size": "Lean, not a target.", "mobility": "Recovers well."},
        profiles={"deep-creator": "Switches when the full-back jumps."},
        staff="Dan",
    )
    assert saved["filled"] is True
    assert saved["physical"]["size"].startswith("Lean")
    loaded = reports.general_report_for_player(922, "barnet-accrington-1")
    assert loaded["position_in_game"] == "RIGHT_WINGBACK_DEFENDER"
    assert loaded["profiles"]["deep-creator"].startswith("Switches")


def test_report_profile_titles_follow_the_player_data(tmp_path, monkeypatch):
    from app.player_report_schema import profile_entries_for_position, profile_id

    assert profile_id("PV DEEP CREATOR") == "deep-creator"
    rows = profile_entries_for_position(
        "RIGHT_WINGBACK_DEFENDER",
        player_profiles=[
            {"key": "PV DEFENDER", "label": "Defender", "score": 44},
            {"key": "PV DEEP CREATOR", "label": "Deep Creator", "score": 40},
        ],
        player_position="RIGHT_WINGBACK_DEFENDER",
    )
    labels = [row["label"] for row in rows]
    assert "Defender" in labels
    assert "Deep Creator" in labels
    assert rows[1]["detailed_prompt"].startswith("How do they progress the ball")


def test_detailed_report_stores_level_rating_and_next_action(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    saved = reports.save_detailed_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        position_in_game="RIGHT_WINGBACK_DEFENDER",
        psychology={"work_hard": "yes", "booked": "no", "notes": "Spoke to the bench at HT."},
        write_up="Progresses with the switch, not the carry.",
        next_steps="Watch again vs a better wide 10.",
        match_rating=7,
        pvfc_level="B",
        next_action="high_priority",
        add_to_pipeline=True,
        pipeline_stage="video_scouted",
        staff="Dan",
    )
    assert saved["match_rating"] == 7
    assert saved["pvfc_level"] == "B"
    assert saved["next_action"] == "high_priority"
    assert saved["psychology"]["work_hard"] == "yes"
    loaded = reports.detailed_report_for_player(922, "barnet-accrington-1")
    assert loaded["write_up"].startswith("Progresses")


def test_sign_next_action_adds_the_player_to_pipeline(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    saved = reports.save_detailed_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        next_action="sign",
        staff="Dan",
    )
    assert saved["next_action"] == "sign"
    assert saved["add_to_pipeline"] is True
    assert saved["pipeline_stage"] == "scout_identified"


def test_not_to_standard_marks_level_d(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    saved = reports.save_detailed_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        next_action="not_to_standard",
        staff="Dan",
    )
    assert saved["pvfc_level"] == "D"
    assert saved["pipeline_stage"] == "not_the_right_fit"


def test_empty_detailed_report_copies_general_physical(tmp_path, monkeypatch):
    monkeypatch.setattr(reports, "PLAYER_REPORTS_PATH", tmp_path / "player-reports.json")
    reports.save_general_report(
        player_id=922,
        fixture_id="barnet-accrington-1",
        position_in_game="RIGHT_WINGBACK_DEFENDER",
        physical={"size": "Lean frame."},
        profiles={"deep-creator": "Switches when the full-back jumps."},
        staff="Dan",
    )
    detailed = reports.detailed_report_for_player(922, "barnet-accrington-1")
    assert detailed["filled"] is False
    assert detailed["position_in_game"] == "RIGHT_WINGBACK_DEFENDER"
    assert detailed["physical"]["size"] == "Lean frame."
    assert detailed["profiles"]["deep-creator"].startswith("Switches")
