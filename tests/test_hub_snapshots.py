from app.hub_snapshots import apply_player_stats_to_row, player_stat_key, put_player_stats


def test_player_stat_key():
    assert player_stat_key(12, "ATTACKING_MIDFIELD") == "12|ATTACKING_MIDFIELD"


def test_put_and_apply_player_stats(tmp_path, monkeypatch):
    monkeypatch.setattr("app.hub_snapshots.HUB_SNAPSHOTS_DIR", tmp_path)
    monkeypatch.setattr("app.hub_snapshots.PLAYERS_PATH", tmp_path / "players.json")
    monkeypatch.setattr("app.hub_snapshots.META_PATH", tmp_path / "meta.json")
    monkeypatch.setattr("app.hub_snapshots.STANDINGS_PATH", tmp_path / "standings.json")

    put_player_stats(
        99,
        "ATTACKING_MIDFIELD",
        {
            "overall_score": 61.2,
            "minutes": 412,
            "top_profile": "Creator",
            "top_profile_score": 74.1,
            "minutes_by_position": [{"position": "ATTACKING_MIDFIELD", "label": "AM", "minutes": 412}],
            "stats_score_version": 5,
        },
        name="Test Player",
    )
    row = {
        "player_id": 99,
        "position": "ATTACKING_MIDFIELD",
        "name": "Test Player",
        "overall_score": None,
        "minutes": None,
    }
    assert apply_player_stats_to_row(row) is True
    assert row["overall_score"] == 61.2
    assert row["minutes"] == 412
    assert row["top_profile"] == "Creator"
