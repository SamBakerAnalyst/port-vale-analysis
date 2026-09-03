from app.apps_manifest import APPS
from app.win_drivers import (
    CANDIDATES,
    WHY_BY_KEY,
    _mean_stat,
    metric_value,
    pearson,
    select_top_stats,
    spearman,
)


def test_spearman_perfect_and_inverse():
    xs = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert round(spearman(xs, xs), 3) == 1.0
    assert round(spearman(xs, [-v for v in xs]), 3) == -1.0
    assert round(pearson(xs, xs), 3) == 1.0


def test_metric_value_derived_xg_diff_and_duel_rate():
    spec_diff = next(item for item in CANDIDATES if item["key"] == "xg_diff")
    spec_duel = next(item for item in CANDIDATES if item["key"] == "duel_pct")
    stats = {82: 1.4, 1463: 1.1, 94: 40, 95: 30, 96: 10, 97: 20}
    assert round(metric_value(stats, spec_diff) or 0, 2) == 0.3
    assert round(metric_value(stats, spec_duel) or 0, 1) == 50.0


def test_select_top_stats_ranks_win_drivers_and_drops_collinear():
    observations = []
    for index in range(30):
        win = 8 + index * 1.1
        observations.append(
            {
                "win_pct": float(win),
                "metrics": {
                    "xg_diff": 0.2 * index + 0.1,
                    "xg_for": 0.2 * index,  # almost the same as xG difference
                    "duel_pct": 48 + (index % 7) * 0.8,
                    "presses": 90 - index * 0.4,
                    "aerial_pct": 42 + ((index * 3) % 11) * 0.5,
                    "shots": 9 + index * 0.05,
                    "packing_xg": 0.9 + (index % 9) * 0.04,
                    "ball_progression": 18 + index * 0.25,
                    "offensive_interventions": 7 + ((index * 5) % 8) * 0.3,
                    "final_third_entries": 28 + index * 0.12,
                    "set_piece_threat": 0.3 + ((index * 2) % 6) * 0.05,
                    "ground_pct": 51 - (index % 4) * 0.4,
                },
            }
        )
    specs = [
        {"key": key, "label": key.replace("_", " "), "short": key, "fmt": "dec", "digits": 2}
        for key in observations[0]["metrics"]
    ]
    top = select_top_stats(observations, specs, top_n=10, min_observations=10, collinearity_r=0.90)
    assert 6 <= len(top) <= 10
    keys = [item["key"] for item in top]
    assert keys[0] in {"xg_diff", "xg_for", "ball_progression", "final_third_entries", "shots"}
    assert not ({"xg_diff", "xg_for"} <= set(keys))
    assert all("r" in item and "higher_better" in item for item in top)
    assert any(item["higher_better"] is True for item in top)


def test_win_drivers_is_on_strategy_sidebar():
    row = next(app for app in APPS if app["id"] == "win-drivers")
    assert row["group"] == "strategy"
    assert row["href"] == "/win-drivers"
    assert row["router"] == "win_drivers"
    assert "What Wins Games" == row["title"]
    assert "15" in row["description"]


def test_every_candidate_has_owner_why_copy():
    missing = [item["key"] for item in CANDIDATES if item["key"] not in WHY_BY_KEY]
    assert missing == []


def test_mean_stat_league_and_top7_playoff_pack():
    rows = [{"position": index, "xg_for": float(index)} for index in range(1, 25)]
    assert _mean_stat(rows, "xg_for", digits=2) == round(sum(range(1, 25)) / 24, 2)
    assert _mean_stat(rows, "xg_for", digits=2, positions={1, 2, 3, 4, 5, 6, 7}) == round(
        sum(range(1, 8)) / 7, 2
    )
    assert _mean_stat(rows, "missing", digits=2) is None
