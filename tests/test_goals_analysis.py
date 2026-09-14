"""Goals Analysis — League Two coding hub."""

from __future__ import annotations

from app.apps_manifest import APPS, required_sidebar_titles
from app.goals_analysis import (
    CodeBody,
    apply_code,
    assign_clips,
    clip_matches_goal,
    club_profile,
    club_slug,
    export_league_csv,
    export_team_csv,
    extract_goals_from_match,
    goal_id_for,
    impect_to_pitch_pct,
    import_csv_text,
    is_coded,
    league_rows,
    merge_goal,
    parse_clip_filename,
    pitch_pct_to_impect,
    save_catalog,
    scan_clips,
    stamp_impect_xy,
    store_clip_bytes,
    suggested_filename,
    taxonomy_payload,
)
from app.paths import STANDALONE_DIR


def _goal(**overrides):
    row = {
        "id": "m1-e10",
        "match_id": 1,
        "event_id": 10,
        "match_week": 5,
        "date": "2026-09-05",
        "home": "Salford City",
        "away": "Port Vale",
        "home_id": 100,
        "away_id": 882,
        "home_goals": 1,
        "away_goals": 1,
        "minute": 52,
        "minute_label": "52",
        "scorer": "Ben Powell",
        "scorer_id": 9,
        "scorer_team": "Port Vale",
        "scorer_team_id": 882,
        "conceding_team": "Salford City",
        "conceding_team_id": 100,
        "assist": "Ryan Croasdale",
        "assist_id": 8,
        "goal_xy": {"x": 41.2, "y": -8.1},
        "assist_xy": {"x": 20.0, "y": 12.0},
        "xy_source": "impect",
        "focus": True,
    }
    row.update(overrides)
    return row


def test_goals_analysis_is_a_strategy_rail_tool():
    titles = required_sidebar_titles()
    assert "Goals Analysis" in titles
    row = next(app for app in APPS if app["id"] == "goals-analysis")
    assert row["href"] == "/goals-analysis"
    assert row["group"] == "strategy"
    assert row.get("sidebar") is not False
    assert tuple(row["roles"]) == ("admin",)
    assert row["router"] == "goals_analysis"
    assert "/api/goals-analysis" in tuple(row["api_prefixes"])


def test_page_has_log_league_team_and_player():
    html = (STANDALONE_DIR / "goals-analysis.html").read_text(encoding="utf-8")
    css = (STANDALONE_DIR.parent / "static" / "goals-analysis.css").read_text(encoding="utf-8")
    js = (STANDALONE_DIR.parent / "static" / "goals-analysis.js").read_text(encoding="utf-8")
    assert "Goals Analysis" in html
    assert 'data-tab="log"' in html
    assert 'data-tab="league"' in html
    assert 'data-tab="team"' in html
    assert 'data-tab="player"' in html
    assert "Save & next" in js
    assert "data-origin" in js
    assert "Impect" in html
    assert "/api/goals-analysis" in js
    assert "/videos/scan" in js
    assert "/export/league.csv" in js
    assert "/export/team/" in js
    assert "html2canvas" not in js
    assert ".ga-pitch" in css
    assert "Players — goals scored" in js
    assert "Port Vale" in html


def test_taxonomy_covers_the_coaching_tree_including_penalty():
    tax = taxonomy_payload()
    assert [row["id"] for row in tax["origins"]] == ["possession", "transition", "set_play"]
    poss = [row["id"] for row in tax["subtypes"]["possession"]]
    trans = [row["id"] for row in tax["subtypes"]["transition"]]
    setp = [row["id"] for row in tax["subtypes"]["set_play"]]
    assert poss == ["passing", "crossing", "solo"]
    assert trans == ["full_transition", "fifty_fifty", "high_regain"]
    assert setp == [
        "corner",
        "wide_free_kick",
        "direct_free_kick",
        "deep_free_kick",
        "long_throw",
        "penalty",
    ]
    assert [row["id"] for row in tax["phases"]] == ["first", "second"]
    assert tax["pitch"]["length"] == 105.0
    assert tax["pitch"]["width"] == 68.0
    assert tax["pitch"]["attack"] == "right"


def test_set_play_needs_a_phase_except_penalties():
    assert is_coded({"origin": "possession", "subtype": "passing"}) is True
    assert is_coded({"origin": "transition", "subtype": "fifty_fifty"}) is True
    assert is_coded({"origin": "set_play", "subtype": "corner"}) is False
    assert is_coded({"origin": "set_play", "subtype": "corner", "set_play_phase": "first"}) is True
    assert is_coded({"origin": "set_play", "subtype": "penalty"}) is True
    assert is_coded({"origin": "possession", "subtype": "corner"}) is False


def test_filename_convention_matches_home_away_minute_scorer():
    parsed = parse_clip_filename("2026-09-05_salford_vs_port-vale_52_powell.mp4")
    assert parsed == {
        "kind": "fixture",
        "date": "2026-09-05",
        "home": "salford",
        "away": "port-vale",
        "minute": 52,
        "scorer": "powell",
    }
    goal = _goal()
    assert clip_matches_goal(parsed, goal) is True
    assert suggested_filename(goal) == "B. Powell - Goal - Right Foot-1.mov"
    assert club_slug("AFC Wimbledon") == "wimbledon"


def test_wyscout_filenames_match_initial_and_last_name():
    caton = parse_clip_filename("C. Caton - Goal - Head-1.mov")
    assert caton == {
        "kind": "wyscout",
        "initial": "C",
        "last": "Caton",
        "finish": "head",
        "finish_label": "Head",
        "seq": 1,
    }
    kavanagh = parse_clip_filename("C. Kavanagh - Goal - Right Foot-2.mov")
    assert kavanagh["seq"] == 2
    assert kavanagh["finish"] == "right_foot"
    olowu = parse_clip_filename("A. Olowu - Goal - Head-1.mov")
    oluwo_goal = _goal(scorer="Adebola Oluwo", scorer_team="Barnet")
    assert clip_matches_goal(olowu, oluwo_goal) is True
    assert clip_matches_goal(caton, _goal(scorer="Charlie Caton")) is True
    assert clip_matches_goal(caton, _goal(scorer="Calum Kavanagh")) is False
    assert clip_matches_goal(
        parse_clip_filename("J. Jones - Goal - Right Foot-1.mov"),
        _goal(scorer="Jack James"),
    ) is False


def test_wyscout_clips_zip_onto_that_players_goals():
    first = _goal(
        id="m1-e1",
        scorer="Calum Kavanagh",
        scorer_id=11,
        scorer_team="Bradford City",
        conceding_team="Port Vale",
        date="2026-08-08",
        minute=12,
        event_id=1,
    )
    second = _goal(
        id="m1-e2",
        scorer="Calum Kavanagh",
        scorer_id=11,
        scorer_team="Bradford City",
        conceding_team="Port Vale",
        date="2026-08-08",
        minute=44,
        event_id=2,
    )
    head = _goal(
        id="m3-e1",
        scorer="Charlie Caton",
        scorer_id=22,
        scorer_team="Colchester United",
        date="2026-08-15",
        minute=28,
        event_id=1,
    )
    left = _goal(
        id="m3-e2",
        scorer="Charlie Caton",
        scorer_id=22,
        scorer_team="Colchester United",
        date="2026-08-15",
        minute=45,
        event_id=2,
    )
    mapping = assign_clips(
        [
            "C. Kavanagh - Goal - Right Foot-2.mov",
            "C. Kavanagh - Goal - Right Foot-1.mov",
            "C. Caton - Goal - Left Foot-1.mov",
            "C. Caton - Goal - Head-1.mov",
        ],
        [first, second, head, left],
    )
    assert mapping["C. Kavanagh - Goal - Right Foot-1.mov"]["id"] == "m1-e1"
    assert mapping["C. Kavanagh - Goal - Right Foot-2.mov"]["id"] == "m1-e2"
    assert mapping["C. Caton - Goal - Head-1.mov"]["id"] == "m3-e1"
    assert mapping["C. Caton - Goal - Left Foot-1.mov"]["id"] == "m3-e2"


def test_impect_pitch_round_trips_attacking_right():
    x_pct, y_pct = impect_to_pitch_pct(52.5, 0.0)
    assert x_pct == 100.0
    assert 49.0 <= y_pct <= 51.0
    back = pitch_pct_to_impect(x_pct, y_pct)
    assert back["x"] == 52.5
    own, _mid = impect_to_pitch_pct(-52.5, 34.0)
    assert own == 0.0


def test_extract_goals_uses_shot_success_and_last_pass_assist():
    match = {
        "id": 99,
        "homeSquadId": 100,
        "awaySquadId": 882,
        "scheduledDate": "2026-08-15T14:00:00Z",
        "matchDay": {"index": 0, "name": "1"},
        "goals": {"home": {"fullTime": 0}, "away": {"fullTime": 1}},
        "iterationId": 2120,
    }
    events = [
        {
            "id": 8,
            "actionType": "PASS",
            "result": "SUCCESS",
            "sequenceIndex": 3,
            "squadId": 882,
            "player": {"id": 2, "commonname": "George Byers"},
            "start": {"adjCoordinates": {"x": 18.0, "y": 6.0}},
        },
        {
            "id": 9,
            "actionType": "SHOT",
            "result": "SUCCESS",
            "sequenceIndex": 3,
            "squadId": 882,
            "player": {"id": 1, "commonname": "George Byers"},
            "gameTime": {"gameTime": "17:00", "gameTimeInSec": 1020},
            "action": "PENALTY_KICK",
            "start": {"adjCoordinates": {"x": 41.5, "y": 0.0}},
        },
    ]
    squads = {100: "Tranmere Rovers", 882: "Port Vale"}
    rows = extract_goals_from_match(match, events, squads, {1: "George Byers", 2: "Funso Ojo"})
    assert len(rows) == 1
    goal = rows[0]
    assert goal["id"] == goal_id_for(99, 9)
    assert goal["scorer"] == "George Byers"
    assert goal["scorer_team"] == "Port Vale"
    assert goal["conceding_team"] == "Tranmere Rovers"
    assert goal["assist"] == "Funso Ojo"
    assert goal["match_week"] == 1
    assert goal["minute"] == 17
    assert goal["goal_xy"]["x"] == 41.5
    assert goal["focus"] is True


def test_coding_overlay_survives_catalog_identity(tmp_path, monkeypatch):
    import app.goals_analysis as ga

    monkeypatch.setattr(ga, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ga, "catalog_path", lambda: tmp_path / "catalog.json")
    monkeypatch.setattr(ga, "coding_path", lambda: tmp_path / "coding.json")
    save_catalog({"version": 1, "goals": [_goal()], "matches": 1})
    merged = apply_code(
        "m1-e10",
        CodeBody(origin="set_play", subtype="penalty"),
        staff="Sam",
    )
    assert merged["coded"] is True
    assert merged["origin"] == "set_play"
    assert merged["subtype"] == "penalty"
    assert merged["scorer"] == "Ben Powell"
    save_catalog({"version": 1, "goals": [_goal(scorer="Ben Powell", minute=52)], "matches": 1})
    again = merge_goal(_goal(), ga.load_coding()["m1-e10"])
    assert again["origin"] == "set_play"
    assert again["scorer"] == "Ben Powell"


def test_club_profile_splits_scored_and_conceded(tmp_path, monkeypatch):
    vale = _goal()
    vale["coded"] = True
    vale["origin"] = "possession"
    vale["subtype"] = "passing"
    conceded = _goal(
        id="m2-e1",
        scorer="Kieron Morris",
        scorer_team="Tranmere Rovers",
        scorer_team_id=200,
        conceding_team="Port Vale",
        conceding_team_id=882,
        origin="transition",
        subtype="high_regain",
        coded=True,
        focus=True,
    )
    profile = club_profile(
        [merge_goal(vale, {"origin": "possession", "subtype": "passing"}), merge_goal(conceded, {"origin": "transition", "subtype": "high_regain"})],
        "port-vale",
    )
    assert profile["scored"]["total"] == 1
    assert profile["conceded"]["total"] == 1
    assert profile["scored"]["origins"][0]["id"] == "possession"
    assert profile["scored"]["origins"][0]["count"] == 1
    assert profile["conceded"]["origins"][1]["id"] == "transition"
    assert profile["conceded"]["origins"][1]["count"] == 1
    assert [player["name"] for player in profile["players"]] == ["Ben Powell"]
    assert profile["players"][0]["goals"] == 1
    assert profile["players"][0]["rows"][0]["opponent"] == "Salford City"


def test_league_and_team_csv_export_player_goals():
    vale = merge_goal(_goal(), {"origin": "possession", "subtype": "passing"})
    other = merge_goal(
        _goal(
            id="m2-e1",
            scorer="Kieron Morris",
            scorer_id=7,
            scorer_team="Tranmere Rovers",
            conceding_team="Port Vale",
        ),
        {"origin": "transition", "subtype": "high_regain"},
    )
    rows = league_rows([vale, other])
    vale_row = next(item for item in rows if item["id"] == "port-vale")
    assert vale_row["scored"] == 1
    assert vale_row["conceded"] == 1
    league = export_league_csv([vale, other])
    assert "Port Vale" in league.body.decode("utf-8")
    team = export_team_csv("port-vale", [vale, other])
    text = team.body.decode("utf-8")
    assert "Ben Powell" in text
    assert "Salford City" in text


def test_csv_and_impect_json_stamp_the_same_records(tmp_path, monkeypatch):
    import app.goals_analysis as ga

    monkeypatch.setattr(ga, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ga, "catalog_path", lambda: tmp_path / "catalog.json")
    monkeypatch.setattr(ga, "coding_path", lambda: tmp_path / "coding.json")
    save_catalog({"version": 1, "goals": [_goal()], "matches": 1})
    csv_text = (
        "date,home,away,minute,scorer,origin,subtype,set_play_phase,goal_x,goal_y\n"
        "2026-09-05,Salford City,Port Vale,52,Powell,possession,crossing,,40.1,-7.2\n"
    )
    result = import_csv_text(csv_text, staff="Sam")
    assert result["applied"] == 1
    stamped = stamp_impect_xy(
        {
            "matchId": 1,
            "events": [
                {
                    "id": 10,
                    "start": {"adjCoordinates": {"x": 44.0, "y": 3.0}},
                    "assist": {"start": {"adjCoordinates": {"x": 12.0, "y": -10.0}}},
                }
            ],
        }
    )
    assert stamped["stamped"] == 1
    overlay = ga.load_coding()["m1-e10"]
    assert overlay["origin"] == "possession"
    assert overlay["subtype"] == "crossing"
    assert overlay["goal_xy"]["x"] == 44.0
    assert overlay["assist_xy"]["y"] == -10.0


def test_scan_copies_and_matches_by_filename(tmp_path, monkeypatch):
    import app.goals_analysis as ga

    monkeypatch.setattr(ga, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ga, "catalog_path", lambda: tmp_path / "catalog.json")
    monkeypatch.setattr(ga, "coding_path", lambda: tmp_path / "coding.json")
    inbox = tmp_path / "inbox" / "goals-analysis"
    videos = tmp_path / "videos" / "goals-analysis"
    inbox.mkdir(parents=True)
    videos.mkdir(parents=True)
    monkeypatch.setattr(ga, "inbox_dir", lambda: inbox)
    monkeypatch.setattr(ga, "videos_dir", lambda: videos)
    save_catalog({"version": 1, "goals": [_goal()], "matches": 1})
    clip = inbox / "2026-09-05_salford_vs_port-vale_52_powell.mp4"
    clip.write_bytes(b"fake-video")
    result = scan_clips(inbox)
    assert result["matched"][0]["goal_id"] == "m1-e10"
    assert (videos / clip.name).is_file()
    assert ga.load_coding()["m1-e10"]["clip_file"] == clip.name


def test_store_clip_rejects_non_video(tmp_path, monkeypatch):
    import app.goals_analysis as ga
    from fastapi import HTTPException

    monkeypatch.setattr(ga, "videos_dir", lambda: tmp_path)
    try:
        store_clip_bytes("notes.txt", b"nope")
        raise AssertionError("should refuse")
    except HTTPException as exc:
        assert exc.status_code == 400
    name = store_clip_bytes("goal.MP4", b"video")
    assert name.endswith(".mp4")
    assert (tmp_path / name).read_bytes() == b"video"
    wyscout = store_clip_bytes("A. Newby - Goal - Right Foot-1.mov", b"clip")
    assert wyscout == "A. Newby - Goal - Right Foot-1.mov"


def test_scan_matches_wyscout_folder_names(tmp_path, monkeypatch):
    import app.goals_analysis as ga

    monkeypatch.setattr(ga, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(ga, "catalog_path", lambda: tmp_path / "catalog.json")
    monkeypatch.setattr(ga, "coding_path", lambda: tmp_path / "coding.json")
    inbox = tmp_path / "inbox" / "goals-analysis"
    videos = tmp_path / "videos" / "goals-analysis"
    inbox.mkdir(parents=True)
    videos.mkdir(parents=True)
    monkeypatch.setattr(ga, "inbox_dir", lambda: inbox)
    monkeypatch.setattr(ga, "videos_dir", lambda: videos)
    save_catalog(
        {
            "version": 1,
            "goals": [
                _goal(
                    id="m1-e1",
                    scorer="Calum Kavanagh",
                    scorer_id=11,
                    scorer_team="Bradford City",
                    conceding_team="Port Vale",
                    date="2026-08-08",
                    minute=12,
                    event_id=1,
                ),
                _goal(
                    id="m1-e2",
                    scorer="Calum Kavanagh",
                    scorer_id=11,
                    scorer_team="Bradford City",
                    conceding_team="Port Vale",
                    date="2026-08-08",
                    minute=44,
                    event_id=2,
                ),
                _goal(
                    id="m4-e1",
                    scorer="Adebola Oluwo",
                    scorer_id=33,
                    scorer_team="Barnet",
                    date="2026-08-16",
                    minute=9,
                    event_id=1,
                ),
            ],
            "matches": 2,
        }
    )
    (inbox / "C. Kavanagh - Goal - Right Foot-1.mov").write_bytes(b"one")
    (inbox / "C. Kavanagh - Goal - Right Foot-2.mov").write_bytes(b"two")
    (inbox / "A. Olowu - Goal - Head-1.mov").write_bytes(b"head")
    result = scan_clips(inbox)
    by_file = {item["file"]: item["goal_id"] for item in result["matched"]}
    assert by_file["C. Kavanagh - Goal - Right Foot-1.mov"] == "m1-e1"
    assert by_file["C. Kavanagh - Goal - Right Foot-2.mov"] == "m1-e2"
    assert by_file["A. Olowu - Goal - Head-1.mov"] == "m4-e1"
    store = ga.load_coding()
    assert store["m1-e1"]["finish_type"] == "right_foot"
    assert store["m4-e1"]["finish_type"] == "head"
