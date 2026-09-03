import json
import pathlib
import tempfile

import app.goal_involvement as gi
from app.goal_involvement import (
    POINTS,
    allocation_total,
    average_player_scores,
    disagreement_summary,
    Allocation,
)


def _temp_db():
    gi.DB_PATH = pathlib.Path(tempfile.mkdtemp()) / "gi.sqlite"
    gi.ensure_dirs = lambda: None
    gi._ready = False
    return gi.db()


def test_missing_coach_counts_as_zero():
    scores = [
        {"coach_id": "a", "player_id": 1, "points": 6},
        {"coach_id": "a", "player_id": 2, "points": 4},
        {"coach_id": "b", "player_id": 1, "points": 10},
    ]
    rows = average_player_scores(
        player_ids=[1, 2, 3],
        coach_ids=["a", "b"],
        scores=scores,
    )
    by_id = {row["player_id"]: row for row in rows}
    assert by_id[1]["mean"] == 8.0
    assert by_id[2]["mean"] == 2.0  # 4 and implicit 0
    assert by_id[3]["mean"] == 0.0


def test_allocation_must_use_full_pool():
    rows = [Allocation(player_id=1, points=6), Allocation(player_id=2, points=4)]
    assert allocation_total(rows) == POINTS
    assert allocation_total([Allocation(player_id=1, points=9)]) != POINTS


def test_disagreement_flags_split_opinions():
    even = [
        {"player_id": 1, "mean": 5, "stdev": 0.2},
        {"player_id": 2, "mean": 5, "stdev": 0.2},
    ]
    split = [
        {"player_id": 1, "mean": 5, "stdev": 4.0},
        {"player_id": 2, "mean": 5, "stdev": 4.0},
    ]
    assert disagreement_summary(even, 1.5)["flagged"] is False
    assert disagreement_summary(split, 1.5)["flagged"] is True
    assert disagreement_summary(split, 1.5)["label"] == "Low agreement"


def test_coaching_staff_is_seeded_with_initials():
    with _temp_db() as conn:
        staff = {row["id"]: row["display_name"] for row in gi.coaches(conn)}
        assert staff == {
            "JB": "Jon Brady",
            "GM": "Gary Mills",
            "ROD": "Richard O'Donnell",
            "JS": "Jamie Smith",
            "DW": "Dan Watson",
        }
        assert gi.settings(conn)["expected_coach_count"] == 5


def _open_goal(conn, pitch_ids=(1, 2, 3)):
    pitch = [gi.player_card(i, {i: f"Player {i}"}) for i in pitch_ids]
    conn.execute(
        """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
           is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
           players_on_pitch, status, created_at)
           VALUES ('g1', 1, 1, '2026-08-22', '26/27', 'League Two', 'Tranmere', 1, '1-0', '0-0',
                   'scored', 17, "17'", ?, 'open', ?)""",
        (json.dumps(pitch), gi.now()),
    )


def test_scores_stay_hidden_even_from_the_admin_login():
    # Every coach signs in on the same admin account, so an admin bypass would
    # leak the whole panel's numbers before they have all submitted.
    person = {"id": "PortVale", "display_name": "PortVale", "role": "admin", "is_admin": True}
    with _temp_db() as conn:
        _open_goal(conn)
        for coach, player_id in (("JB", 1), ("GM", 2)):
            conn.execute(
                "INSERT INTO goal_scores VALUES ('g1',?,?,?,?)", (coach, player_id, 10, gi.now())
            )
        jb = gi.acting(conn, person, "JB")

        goal = gi.public_goal(conn, gi.get_goal(conn, "g1"), jb, detail=True)
        assert goal["revealed"] is False
        assert goal["averages"] == []
        assert goal["coach_scores"] == []
        assert goal["submitted_coaches"] == ["GM", "JB"]  # who filed is fine to show

        conn.execute("UPDATE goals SET status='closed' WHERE id='g1'")
        goal = gi.public_goal(conn, gi.get_goal(conn, "g1"), jb, detail=True)
        assert goal["revealed"] is True
        assert {row["player_id"]: row["mean"] for row in goal["averages"] if row["mean"]} == {1: 5.0, 2: 5.0}


def test_scoring_link_identifies_one_coach_and_one_match():
    token = gi.make_scoring_token(coach_id="JB", match_id=1)
    claim = gi.parse_scoring_token(token)
    assert claim["coach_id"] == "JB"
    assert claim["match_id"] == 1


def test_tampered_or_expired_links_are_refused():
    token = gi.make_scoring_token(coach_id="JB", match_id=1)
    # Swapping the payload without the matching signature must not work, or a
    # coach could edit the URL and score as somebody else.
    forged = gi.base64.urlsafe_b64encode(b"GM\n1\n99999999999\ndeadbeef").decode().rstrip("=")
    assert gi.parse_scoring_token(forged) is None
    assert gi.parse_scoring_token(token[:-4] + "AAAA") is None
    assert gi.parse_scoring_token("") is None

    # Properly signed but last season's link should be dead.
    stale = f"JB\n1\n{int(gi.time.time()) - 60}"
    sig = gi.hmac.new(gi.link_secret(), stale.encode(), gi.hashlib.sha256).hexdigest()
    expired = gi.base64.urlsafe_b64encode(f"{stale}\n{sig}".encode()).decode().rstrip("=")
    assert gi.parse_scoring_token(expired) is None


def test_link_only_exposes_that_coachs_own_numbers():
    with _temp_db() as conn:
        _open_goal(conn)
        for coach, player_id in (("JB", 1), ("GM", 2)):
            conn.execute(
                "INSERT INTO goal_scores VALUES ('g1',?,?,?,?)", (coach, player_id, 10, gi.now())
            )
        payload = gi.token_payload(conn, {"coach_id": "JB", "match_id": 1, "exp": 0})
        assert payload["coach"]["display_name"] == "Jon Brady"
        goal = payload["goals"][0]
        assert goal["my_allocations"] == [{"player_id": 1, "points": 10}]
        for leak in ("averages", "coach_scores", "coach_names", "submitted_coaches", "agreement"):
            assert leak not in goal


def test_short_codes_are_stable_and_readable():
    with _temp_db() as conn:
        code = gi.link_code(conn, coach_id="JB", match_id=270696)
        assert len(code) == 8
        # Nothing a coach could misread down the phone.
        assert not set(code) & set("O0I1L")
        # Re-sending the same match must not orphan the link already sent.
        assert gi.link_code(conn, coach_id="JB", match_id=270696) == code
        assert gi.link_code(conn, coach_id="GM", match_id=270696) != code

        claim = gi.resolve_link(conn, code)
        assert claim["coach_id"] == "JB"
        assert claim["match_id"] == 270696
        assert gi.resolve_link(conn, code.lower()) == claim  # typed by hand
        assert gi.resolve_link(conn, "ZZZZZZZZ") is None


def test_long_signed_links_still_work_after_the_switch():
    # Links already sitting in a coach's WhatsApp must not die.
    with _temp_db() as conn:
        old = gi.make_scoring_token(coach_id="GM", match_id=42)
        assert gi.claim_or_403(conn, old)["coach_id"] == "GM"
        new = gi.link_code(conn, coach_id="GM", match_id=42)
        assert gi.claim_or_403(conn, new)["coach_id"] == "GM"


def _goal(conn, gid, match, minute, side="scored", season="26/27", status="open", date="2026-08-22"):
    pitch = [gi.player_card(i, {i: f"Player {i}"}) for i in (1, 2, 3)]
    conn.execute(
        """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
           is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
           players_on_pitch, status, created_at)
           VALUES (?,?,?,?,?,'League Two','Tranmere',1,'1-0','0-0',?,?,?,?,?,?)""",
        (gid, match, minute, date, season, side, minute, f"{minute}'", json.dumps(pitch), status, gi.now()),
    )


def test_unranked_means_open_unscored_and_this_season():
    with _temp_db() as conn:
        _goal(conn, "a", 7, 10)
        _goal(conn, "b", 7, 20)
        _goal(conn, "c", 9, 30, date="2026-08-29")
        _goal(conn, "old", 5, 40, season="25/26", date="2025-11-01")
        _goal(conn, "shut", 7, 50, status="closed")
        conn.execute("INSERT INTO goal_scores VALUES ('a','JB',1,10,?)", (gi.now(),))

        # 'a' already scored by JB, 'old' is last season, 'shut' is closed.
        assert [row["id"] for row in gi.unranked_goals(conn, "JB")] == ["b", "c"]
        # Gary has scored none, so he still owes 'a' as well — it is per coach.
        assert [row["id"] for row in gi.unranked_goals(conn, "GM")] == ["a", "b", "c"]


def test_send_out_only_chases_coaches_who_owe():
    with _temp_db() as conn:
        _goal(conn, "a", 7, 10)
        conn.execute("UPDATE coaches SET phone='07700900123' WHERE id='JB'")
        for coach in ("GM", "ROD", "JS", "DW"):
            conn.execute("INSERT INTO goal_scores VALUES ('a',?,1,10,?)", (coach, gi.now()))

        out = gi.send_out(conn, base_url="https://analysis.port-vale.co.uk")
        assert [row["id"] for row in out["waiting"]] == ["JB"]
        assert out["nothing_to_send"] is False
        jb = out["waiting"][0]
        assert jb["whatsapp_ready"] is True
        assert "1 goal to score" in jb["message"]
        assert jb["url"].startswith("https://analysis.port-vale.co.uk/gi/")

        conn.execute("INSERT INTO goal_scores VALUES ('a','JB',1,10,?)", (gi.now(),))
        assert gi.send_out(conn, base_url="https://x")["nothing_to_send"] is True


def test_an_everything_link_spans_games_but_not_closed_goals():
    with _temp_db() as conn:
        _goal(conn, "a", 7, 10)
        _goal(conn, "b", 9, 20, date="2026-08-29")
        _goal(conn, "shut", 9, 30, date="2026-08-29", status="closed")
        code = gi.link_code(conn, coach_id="JB", match_id=gi.ALL_OUTSTANDING)
        payload = gi.token_payload(conn, gi.resolve_link(conn, code))

        assert [g["id"] for g in payload["goals"]] == ["a", "b"]
        assert payload["multi_match"] is True
        # Still nobody else's numbers, same as a single-match link.
        for goal in payload["goals"]:
            for leak in ("averages", "coach_scores", "coach_names", "submitted_coaches"):
                assert leak not in goal


def test_one_standing_link_catches_up_on_games_missed_since():
    with _temp_db() as conn:
        _goal(conn, "week1", 7, 10)
        code = gi.link_code(conn, coach_id="JB", match_id=gi.ALL_OUTSTANDING)
        assert [g["id"] for g in gi.token_payload(conn, gi.resolve_link(conn, code))["goals"]] == ["week1"]

        # Two more games go by while the coach ignores their phone.
        _goal(conn, "week2", 9, 20, date="2026-08-29")
        _goal(conn, "week3", 11, 30, date="2026-09-05")

        # Same link, no new message needed, all three now waiting.
        assert gi.link_code(conn, coach_id="JB", match_id=gi.ALL_OUTSTANDING) == code
        goals = gi.token_payload(conn, gi.resolve_link(conn, code))["goals"]
        assert [g["id"] for g in goals] == ["week1", "week2", "week3"]

        # And once they have done them, the same link goes quiet rather than broken.
        for gid in ("week1", "week2", "week3"):
            conn.execute("INSERT INTO goal_scores VALUES (?,'JB',1,10,?)", (gid, gi.now()))
        assert gi.token_payload(conn, gi.resolve_link(conn, code))["goals"] == []


def test_standing_links_outlive_a_busy_spell():
    with _temp_db() as conn:
        code = gi.link_code(conn, coach_id="JB", match_id=gi.ALL_OUTSTANDING)
        row = conn.execute("SELECT expires_at FROM scoring_links WHERE code=?", (code,)).fetchone()
        days = (int(row["expires_at"]) - int(gi.time.time())) / 86400
        assert days > 180, "a coach catching up after a month must not find a dead link"

        # Pretend it is nearly out of time, then re-send: the expiry moves out
        # and the code stays put, so an old message still works.
        conn.execute("UPDATE scoring_links SET expires_at=? WHERE code=?", (int(gi.time.time()) + 60, code))
        assert gi.link_code(conn, coach_id="JB", match_id=gi.ALL_OUTSTANDING) == code
        renewed = conn.execute("SELECT expires_at FROM scoring_links WHERE code=?", (code,)).fetchone()
        assert (int(renewed["expires_at"]) - int(gi.time.time())) / 86400 > 180


def test_uk_mobiles_become_wa_me_numbers():
    assert gi.wa_number("07700 900123") == "447700900123"
    assert gi.wa_number("+44 7700 900123") == "447700900123"
    assert gi.wa_number("00447700900123") == "447700900123"
    assert gi.wa_number("") == ""


def _clip_store(tmp):
    gi.CLIPS_DIR = pathlib.Path(tmp) / "clips"
    return gi.CLIPS_DIR


def test_only_real_video_files_are_accepted():
    _clip_store(tempfile.mkdtemp())
    for bad_name in ("hack.php", "notes.txt", "clip.mp4.exe", "clip"):
        try:
            gi.store_clip("g1", filename=bad_name, blob=b"x")
        except Exception as exc:
            assert "must be one of" in str(exc)
        else:
            raise AssertionError(f"{bad_name} should have been refused")

    # Oversized files are refused rather than filling the droplet.
    try:
        gi.store_clip("g1", filename="huge.mp4", blob=b"x" * (gi.MAX_CLIP_BYTES + 1))
    except Exception as exc:
        assert "too big" in str(exc)
    else:
        raise AssertionError("an oversized clip should have been refused")

    assert gi.store_clip("g1", filename="goal.MP4", blob=b"video") == "g1.mp4"


def test_a_goal_id_cannot_escape_the_clips_folder():
    store = _clip_store(tempfile.mkdtemp())
    name = gi.store_clip("../../etc/passwd", filename="x.mp4", blob=b"video")
    assert "/" not in name and ".." not in name
    assert (store / name).is_file(), "the file must land inside the clips folder"


def test_replacing_a_clip_does_not_leave_the_old_format_behind():
    store = _clip_store(tempfile.mkdtemp())
    gi.store_clip("g1", filename="first.mp4", blob=b"one")
    gi.store_clip("g1", filename="second.webm", blob=b"two")
    assert sorted(path.name for path in store.glob("g1.*")) == ["g1.webm"]


def test_youtube_and_vimeo_links_become_embeddable():
    assert gi.embed_url("https://youtu.be/abc123XYZ") == "https://www.youtube.com/embed/abc123XYZ"
    assert gi.embed_url("https://www.youtube.com/watch?v=abc123XYZ") == "https://www.youtube.com/embed/abc123XYZ"
    assert gi.embed_url("https://vimeo.com/123456789") == "https://player.vimeo.com/video/123456789"
    # A club provider that refuses framing is left alone for the fallback button.
    assert gi.embed_url("https://app.veo.co/matches/xyz") == "https://app.veo.co/matches/xyz"


def test_clip_kind_reflects_what_is_actually_there():
    store = _clip_store(tempfile.mkdtemp())
    assert gi.clip_info({"clip_file": "", "clip_url": ""})["has_clip"] is False
    assert gi.clip_info({"clip_file": "", "clip_url": "https://youtu.be/a1b2c3"})["kind"] == "embed"
    assert gi.clip_info({"clip_file": "", "clip_url": "https://app.veo.co/x"})["kind"] == "link"
    # A row pointing at a file that has since been deleted must not claim a clip.
    assert gi.clip_info({"clip_file": "ghost.mp4", "clip_url": ""})["has_clip"] is False
    store.mkdir(parents=True, exist_ok=True)
    (store / "real.mp4").write_bytes(b"video")
    assert gi.clip_info({"clip_file": "real.mp4", "clip_url": ""})["kind"] == "file"


def test_a_clip_row_cannot_point_outside_the_clips_folder():
    store = _clip_store(tempfile.mkdtemp())
    store.mkdir(parents=True, exist_ok=True)
    outside = store.parent / "secret.mp4"
    outside.write_bytes(b"not yours")
    # Even a doctored database row is resolved against the clips folder only.
    assert gi.clip_file_path({"clip_file": "../secret.mp4"}) is None


def test_coaches_see_the_clip_on_their_own_goals():
    store = _clip_store(tempfile.mkdtemp())
    store.mkdir(parents=True, exist_ok=True)
    (store / "g1.mp4").write_bytes(b"video")
    with _temp_db() as conn:
        _open_goal(conn)
        conn.execute("UPDATE goals SET clip_file='g1.mp4' WHERE id='g1'")
        claim = {"coach_id": "JB", "match_id": gi.ALL_OUTSTANDING, "exp": 0}
        payload = gi.token_payload(conn, claim)
        assert payload["goals"][0]["clip"]["kind"] == "file"
        # The link must not hand over anything about where it sits on disk.
        assert "clip_file" not in payload["goals"][0]


def test_points_are_recorded_against_the_picked_coach():
    person = {"id": "PortVale", "display_name": "PortVale", "role": "admin", "is_admin": True}
    with _temp_db() as conn:
        nobody = gi.acting(conn, person, None)
        assert nobody["coach_id"] == ""
        assert gi.can_score(conn, nobody) is False

        picked = gi.acting(conn, person, "jb")
        assert picked["coach_id"] == "JB"
        assert picked["coach_name"] == "Jon Brady"
        assert gi.can_score(conn, picked) is True

        assert gi.acting(conn, person, "nope")["coach_id"] == ""


def test_running_table_uses_whoever_has_filed_so_far():
    with _temp_db() as conn:
        _open_goal(conn)
        conn.execute(
            "INSERT INTO goal_scores VALUES ('g1','JB',1,7,?)", (gi.now(),)
        )
        conn.execute(
            "INSERT INTO goal_scores VALUES ('g1','JB',2,3,?)", (gi.now(),)
        )
        hidden = gi.player_dashboard(
            conn, season="26/27", date_from=None, date_to=None, competition=None
        )
        assert hidden["players"] == []
        running = gi.player_dashboard(
            conn,
            season="26/27",
            date_from=None,
            date_to=None,
            competition=None,
            include_incomplete=True,
        )
        assert running["provisional"] is True
        by_name = {row["name"]: row for row in running["players"]}
        assert by_name["Player 1"]["scored_points"] == 7
        assert by_name["Player 2"]["scored_points"] == 3
        assert [row["name"] for row in running["players"]] == ["Player 1", "Player 2"]


def test_the_board_ranks_by_net():
    with _temp_db() as conn:
        _open_goal(conn)
        conn.execute("UPDATE goals SET status='closed' WHERE id='g1'")
        conn.execute("INSERT INTO goal_scores VALUES ('g1','JB',1,10,?)", (gi.now(),))
        conn.execute(
            """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
               is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
               players_on_pitch, status, created_at)
               VALUES ('g2', 1, 2, '2026-08-22', '26/27', 'League Two', 'Tranmere', 1, '1-1', '1-0',
                       'conceded', 71, "71'", ?, 'closed', ?)""",
            (
                json.dumps([gi.player_card(i, {i: f"Player {i}"}) for i in (1, 2, 3)]),
                gi.now(),
            ),
        )
        conn.execute("INSERT INTO goal_scores VALUES ('g2','JB',2,10,?)", (gi.now(),))
        board = gi.player_dashboard(
            conn, season="26/27", date_from=None, date_to=None, competition=None
        )
        names = [row["name"] for row in board["players"]]
        nets = [row["net_points"] for row in board["players"]]
        assert names[0] == "Player 1"
        assert nets[0] == 10
        assert names[1] == "Player 2"
        assert nets[1] == -10


def test_shot_and_goal_events_are_the_same_finish():
    shot = gi.goal_fingerprint(match_id=9, side="scored", minute=17.1, scorer_id=44)
    goal = gi.goal_fingerprint(match_id=9, side="scored", minute=17.4, scorer_id=44)
    other = gi.goal_fingerprint(match_id=9, side="conceded", minute=17.1, scorer_id=44)
    assert shot == goal
    assert shot != other


def test_duplicate_goal_rows_collapse_onto_the_one_with_the_clip():
    with _temp_db() as conn:
        pitch = json.dumps([gi.player_card(1, {1: "Byers"})])
        when = gi.now()
        conn.execute(
            """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
               is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
               scorer_id, scorer_name, players_on_pitch, status, created_at, clip_file)
               VALUES ('g_a', 1, 11, '2026-08-22', '26/27', 'League Two', 'Tranmere', 1, '1-0', '0-0',
                       'scored', 17.1, "17'", 1, 'Byers', ?, 'open', ?, '')""",
            (pitch, when),
        )
        conn.execute(
            """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
               is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
               scorer_id, scorer_name, players_on_pitch, status, created_at, clip_file)
               VALUES ('g_b', 1, 22, '2026-08-22', '26/27', 'League Two', 'Tranmere', 1, '1-0', '0-0',
                       'scored', 17.4, "17'", 1, 'Byers', ?, 'open', ?, 'g_b.mp4')""",
            (pitch, when),
        )
        conn.execute("INSERT INTO goal_scores VALUES ('g_a','JB',1,10,?)", (when,))
        removed = gi.merge_duplicate_goals(conn)
        assert removed == 1
        rows = conn.execute("SELECT id, clip_file FROM goals").fetchall()
        assert len(rows) == 1
        assert rows[0]["clip_file"] == "g_b.mp4"
        scores = conn.execute("SELECT goal_id, coach_id FROM goal_scores").fetchall()
        assert len(scores) == 1
        assert scores[0]["goal_id"] == rows[0]["id"]


def test_recent_auto_sync_is_not_repeated():
    with _temp_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('last_sync_at', ?)",
            (gi.now(),),
        )
        conn.execute(
            "INSERT OR REPLACE INTO settings(key, value) VALUES ('last_sync_season', '26/27')"
        )
        conn.commit()
    result = gi.maybe_sync_season("26/27")
    assert result["skipped"] is True
    assert result["goals_created"] == 0


def test_matrix_shows_each_coachs_points_and_flags_the_outlier():
    with _temp_db() as conn:
        _open_goal(conn)
        # Four coaches agree Player 1 did most of it; DW gives them nothing.
        for coach in ("JB", "GM", "ROD", "JS"):
            conn.execute(
                "INSERT INTO goal_scores VALUES ('g1',?,?,?,?)", (coach, 1, 8, gi.now())
            )
            conn.execute(
                "INSERT INTO goal_scores VALUES ('g1',?,?,?,?)", (coach, 2, 2, gi.now())
            )
        conn.execute("INSERT INTO goal_scores VALUES ('g1','DW',1,0,?)", (gi.now(),))
        conn.execute("INSERT INTO goal_scores VALUES ('g1','DW',2,10,?)", (gi.now(),))
        payload = gi.score_matrix(conn, season="26/27")
        coaches = [row["id"] for row in payload["coaches"]]
        assert coaches == ["JB", "GM", "ROD", "JS", "DW"]
        goal = payload["goals"][0]
        by_name = {row["name"]: row for row in goal["players"]}
        p1 = by_name["Player 1"]
        assert p1["by_coach"]["JB"] == 8
        assert p1["by_coach"]["DW"] == 0
        assert p1["flagged"] is True
        assert p1["outliers"]["DW"] is True
        assert "JB" not in p1["outliers"]
        assert payload["anomaly_count"] >= 1


def test_matrix_leaves_unfiled_coaches_blank_not_zero():
    with _temp_db() as conn:
        _open_goal(conn)
        conn.execute("INSERT INTO goal_scores VALUES ('g1','JB',1,10,?)", (gi.now(),))
        payload = gi.score_matrix(conn, season="26/27")
        row = payload["goals"][0]["players"][0]
        assert row["by_coach"]["JB"] == 10
        assert row["by_coach"]["GM"] is None
        assert row["flagged"] is False
        assert row["outliers"] == {}


def test_open_play_is_possession_plus_transition():
    assert gi.classify_play_type({"phase": "IN_POSSESSION"}) == "open_play"
    assert gi.classify_play_type({"phase": "ATTACKING_TRANSITION"}) == "open_play"
    assert gi.classify_play_type({"phase": "SET_PIECE"}) == "set_play"
    assert gi.classify_play_type({"action": "PENALTY_KICK"}) == "set_play"
    assert gi.classify_play_type({"setPiece": {"id": 9}}) == "set_play"


def test_table_filter_keeps_set_play_off_the_open_play_board():
    with _temp_db() as conn:
        _open_goal(conn)
        conn.execute("UPDATE goals SET play_type='open_play', status='closed' WHERE id='g1'")
        conn.execute("INSERT INTO goal_scores VALUES ('g1','JB',1,10,?)", (gi.now(),))
        conn.execute(
            """INSERT INTO goals (id, match_id, event_id, date, season, competition, opponent,
               is_home, scoreline, scoreline_before, team_for_or_against, minute, minute_label,
               players_on_pitch, status, created_at, play_type)
               VALUES ('g2', 1, 2, '2026-08-22', '26/27', 'League Two', 'Tranmere', 1, '2-0', '1-0',
                       'scored', 44, "44'", ?, 'closed', ?, 'set_play')""",
            (json.dumps([gi.player_card(2, {2: "Player 2"})]), gi.now()),
        )
        conn.execute("INSERT INTO goal_scores VALUES ('g2','JB',2,10,?)", (gi.now(),))
        open_board = gi.player_dashboard(
            conn, season="26/27", date_from=None, date_to=None, competition=None, play_type="open_play"
        )
        set_board = gi.player_dashboard(
            conn, season="26/27", date_from=None, date_to=None, competition=None, play_type="set_play"
        )
        assert [row["name"] for row in open_board["players"]] == ["Player 1"]
        assert [row["name"] for row in set_board["players"]] == ["Player 2"]
