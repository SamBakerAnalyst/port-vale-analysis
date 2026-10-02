from app import pv_archetypes as pva
from app.apps_manifest import APPS, role_path_prefixes


def test_every_formation_has_eleven_known_slots():
    role_ids = {role["id"] for role in pva.DEFAULT_ROLES}
    for formation in pva.FORMATIONS:
        slots = formation["slots"]
        assert len(slots) == 11, formation["id"]
        assert len({s["slot"] for s in slots}) == 11
        assert all(s["role"] in role_ids for s in slots)


def test_every_role_is_used_by_a_formation():
    used = {s["role"] for f in pva.FORMATIONS for s in f["slots"]}
    assert used == {role["id"] for role in pva.DEFAULT_ROLES}


def test_archetype_weights_only_use_profiles_their_sources_share():
    ids = set()
    for role in pva.DEFAULT_ROLES:
        assert role["archetypes"], role["id"]
        for arch in role["archetypes"]:
            assert arch["id"] not in ids
            ids.add(arch["id"])
            allowed = set(pva.archetype_profiles(arch))
            assert allowed, arch["id"]
            assert set(arch["weights"]) <= allowed, arch["id"]
            assert sum(arch["weights"].values()) > 0
            assert all(name in pva.PROFILE_LABELS for name in arch["weights"])


def test_fit_is_weighted_average_and_needs_every_weighted_profile():
    weights = {"A": 3, "B": 1, "C": 0}
    assert pva.archetype_fit({"A": 80, "B": 40}, weights) == 70.0
    assert pva.archetype_fit({"A": 80}, weights) is None


def _player(pid, position, scores, **extra):
    return {
        "playerId": pid,
        "name": f"P{pid}",
        "age": extra.get("age", 24),
        "club": extra.get("club", "Club"),
        "league": extra.get("league", "League Two"),
        "minutes": extra.get("minutes", 900),
        "position": position,
        "scores": scores,
    }


def test_rank_filters_dedupes_and_sorts():
    arch = {
        "sources": ["DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD"],
        "weights": {pva.MID_WIN: 1},
    }
    players = [
        _player(1, "DEFENSE_MIDFIELD", {pva.MID_WIN: 70}),
        _player(1, "CENTRAL_MIDFIELD", {pva.MID_WIN: 90}),
        _player(2, "CENTRAL_MIDFIELD", {pva.MID_WIN: 80}),
        _player(3, "CENTRAL_MIDFIELD", {pva.MID_WIN: 99}, minutes=50),
        _player(4, "CENTRAL_MIDFIELD", {pva.MID_WIN: 95}, age=33),
        _player(5, "CENTER_FORWARD", {pva.MID_WIN: 100}),
    ]
    ranked = pva.rank_archetype(arch, players, min_minutes=270, max_age=30)
    assert [(r["playerId"], r["fit"]) for r in ranked] == [(1, 90.0), (2, 80.0)]


def test_overrides_merge_text_and_reject_foreign_weights():
    overrides = {
        "roles": {"six": {"nickname": "The Pivot", "importance": 9, "requirements": ["One", "", "Two"]}},
        "archetypes": {
            "six-winner": {"name": "Destroyer", "weights": {pva.MID_WIN: 5, "PV - GOAL THREAT": 9}},
        },
    }
    merged = pva.apply_overrides(pva.DEFAULT_ROLES, overrides)
    six = next(r for r in merged if r["id"] == "six")
    assert six["nickname"] == "The Pivot"
    assert six["importance"] == 5
    assert six["requirements"] == ["One", "Two"]
    winner = next(a for a in six["archetypes"] if a["id"] == "six-winner")
    assert winner["name"] == "Destroyer"
    assert winner["weights"] == {pva.MID_WIN: 5.0}
    # Defaults untouched.
    assert next(r for r in pva.DEFAULT_ROLES if r["id"] == "six")["nickname"] == "The Screen"


def test_manifest_entry_and_scout_access():
    app = next(a for a in APPS if a["id"] == "pv-archetypes")
    assert app["group"] == "recruitment"
    assert app["router"] == "pv_archetypes"
    prefixes = role_path_prefixes("scouts")
    assert "/pv-archetypes" in prefixes
    assert "/api/pv-archetypes" in prefixes
