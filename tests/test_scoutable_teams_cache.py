"""Scoutable Teams board caching.

The board is league → club structure, which barely changes across a season, but
it used to live in process memory on a 30 minute TTL with no disk copy. That
meant a rebuild — six leagues of Impect iteration and squad lookups — after
every deploy and after any half hour nobody had the page open. These tests pin
the disk cache that stops that.
"""

from __future__ import annotations

import app.main  # noqa: F401 - initialise the app so the router imports resolve
from app import scoutable_teams as st


def _fake_board() -> dict:
    return {
        "stages": [],
        "positions": [],
        "leagues": [
            {"id": "League Two", "title": "League Two", "clubs": [{"id": 1, "name": "FC Port Vale"}]}
        ],
    }


def test_board_survives_a_restart_via_the_disk_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "BOARD_DISK_CACHE", tmp_path / "board.json")
    monkeypatch.setattr(st, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(st, "_attach_board_counts", lambda payload: payload)

    key = f"board:v{st._CACHE_VERSION}"
    st._save_board_disk(key, _fake_board())

    # A fresh container starts with empty memory — the disk copy must serve it.
    st._BOARD_CACHE.clear()

    def _explode(_competition):
        raise AssertionError("hit Impect despite a warm disk cache")

    monkeypatch.setattr(st, "_pick_iteration_for_competition", _explode)

    board = st.build_leagues_board()
    assert board["leagues"][0]["clubs"][0]["name"] == "FC Port Vale"
    # and it should now be back in memory for the next request
    assert key in st._BOARD_CACHE


def test_stale_disk_cache_is_rebuilt(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "BOARD_DISK_CACHE", tmp_path / "board.json")
    monkeypatch.setattr(st, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(st, "_attach_board_counts", lambda payload: payload)

    key = f"board:v{st._CACHE_VERSION}"
    st._save_board_disk(key, _fake_board())

    # Age the saved entry past the TTL.
    import json

    path = tmp_path / "board.json"
    store = json.loads(path.read_text())
    store[key]["saved_at"] = 0
    path.write_text(json.dumps(store))

    st._BOARD_CACHE.clear()
    rebuilt: list[str] = []
    monkeypatch.setattr(
        st,
        "_pick_iteration_for_competition",
        lambda competition: rebuilt.append(competition) or None,
    )

    st.build_leagues_board()
    assert rebuilt, "a stale board should rebuild rather than serve old structure"


def test_force_refresh_ignores_both_caches(tmp_path, monkeypatch):
    monkeypatch.setattr(st, "BOARD_DISK_CACHE", tmp_path / "board.json")
    monkeypatch.setattr(st, "ensure_data_dirs", lambda: None)
    monkeypatch.setattr(st, "_attach_board_counts", lambda payload: payload)

    key = f"board:v{st._CACHE_VERSION}"
    st._save_board_disk(key, _fake_board())
    st._BOARD_CACHE[key] = (9e9, _fake_board())  # far-future, would never expire

    rebuilt: list[str] = []
    monkeypatch.setattr(
        st,
        "_pick_iteration_for_competition",
        lambda competition: rebuilt.append(competition) or None,
    )

    st.build_leagues_board(force_refresh=True)
    assert rebuilt, "the daily warm must rebuild, not read its own cache"


def test_board_ttl_is_long_enough_to_outlive_a_quiet_afternoon():
    assert st._BOARD_TTL >= 6 * 3600


def test_a_corrupt_disk_cache_does_not_break_the_page(tmp_path, monkeypatch):
    path = tmp_path / "board.json"
    path.write_text("{ not json")
    monkeypatch.setattr(st, "BOARD_DISK_CACHE", path)
    assert st._load_board_disk(f"board:v{st._CACHE_VERSION}") is None
