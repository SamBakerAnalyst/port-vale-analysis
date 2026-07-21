from __future__ import annotations

from app.scouting import build_scouting_player_chart_bundle


def test_build_scouting_player_chart_bundle_includes_catalog_and_squad_hint() -> None:
    bundle = build_scouting_player_chart_bundle(
        name="Connor Jennings",
        player_id=12345,
        iteration_id=1464,
        squad_id=88,
        position="CENTER_FORWARD",
        profiles=["PV GOAL THREAT", "PV HOLD UP"],
    )

    assert bundle["playerKey"] == "connor jennings|12345"
    assert bundle["playerId"] == 12345
    assert bundle["iterationId"] == 1464
    assert bundle["squadId"] == 88

    request = bundle["chartRequest"]
    assert request["iteration_ids"] == [1464]
    assert request["player_keys"] == ["connor jennings|12345"]
    assert request["positions"] == ["CENTER_FORWARD"]
    assert request["chart_source"] == "profiles"

    catalog = request["player_catalog"]["connor jennings|12345"]
    assert catalog["name"] == "Connor Jennings"
    assert catalog["ids_by_iteration"] == {"1464": 12345}
    assert catalog["squad_ids_by_iteration"] == {"1464": 88}
    assert request["player_seasons"]["connor jennings|12345"] == [1464]
    assert request["player_positions"]["connor jennings|12345"] == ["CENTER_FORWARD"]


def test_build_scouting_player_chart_bundle_without_squad_id() -> None:
    bundle = build_scouting_player_chart_bundle(
        name="Test Player",
        player_id=99,
        iteration_id=100,
        squad_id=None,
        position="CENTRAL_DEFENDER",
        profiles=["PV DEFENSIVE"],
    )

    catalog = bundle["chartRequest"]["player_catalog"]["test player|99"]
    assert "squad_ids_by_iteration" not in catalog
