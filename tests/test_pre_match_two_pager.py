from __future__ import annotations

from pathlib import Path

from app import pre_match_notes as notes


def test_two_pager_notes_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(notes, "DATA_ROOT", tmp_path)
    monkeypatch.setattr(notes, "two_pager_store_path", lambda: tmp_path / "pre-match-two-pager.json")
    empty = notes.load_two_pager_board(2120, 2157)
    assert empty["notes"]["hurt_them"] == ""
    saved = notes.save_two_pager_board(
        2120,
        2157,
        notes={
            "hurt_them": "Attack the space behind Turton",
            "hurt_us": "",
            "player_comments": "",
        },
        xi_shape={"id:9": {"x": 51.2, "y": 18.4}},
    )
    assert saved["notes"]["hurt_them"].startswith("Attack the space")
    assert saved["xi_shape"]["id:9"]["x"] == 51.2
    loaded = notes.load_two_pager_board(2120, 2157)
    assert loaded["notes"] == saved["notes"]
    assert loaded["xi_shape"] == saved["xi_shape"]


def test_two_pager_store_uses_shared_folder_when_writable(tmp_path, monkeypatch):
    shared = tmp_path / "shared"
    shared.mkdir()
    monkeypatch.setenv("SHARED_DATA_ROOT", str(shared))
    monkeypatch.setattr(notes, "DATA_ROOT", tmp_path / "data")
    path = notes.two_pager_store_path()
    assert path == shared / "pre-match-two-pager.json"
    notes.save_two_pager_board(1, 2, notes={"hurt_us": "Wide overloads"})
    assert path.exists()
    assert "Wide overloads" in path.read_text(encoding="utf-8")


def test_last_starting_xi_uses_headshots():
    js = Path("static/pre-match.js").read_text(encoding="utf-8")
    idx = js.index('title: "Last starting XI"')
    chunk = js[idx : idx + 700]
    assert 'markerMode: "photo"' in chunk
    assert 'markerMode: "number"' not in chunk
