from app.set_piece_pre_match import (
    _backfill_tm_heights_from_previous_season,
    _height_band_label,
    _parse_tm_height_cm,
    _tm_profiles_have_heights,
)


def test_parse_uk_imperial_height():
    assert _parse_tm_height_cm("6 ft 3 in") == 190
    assert _parse_tm_height_cm('<td class="zentriert">6 ft 1 in</td>') == 185
    assert _parse_tm_height_cm("5 ft 10 in") == 178


def test_parse_metric_height():
    assert _parse_tm_height_cm("1,88 m") == 188
    assert _parse_tm_height_cm("1.91m") == 191


def test_imperial_height_lands_in_expected_band():
    assert _height_band_label(_parse_tm_height_cm("6 ft 3 in")) == "6'3\""
    assert _height_band_label(_parse_tm_height_cm("6 ft 4 in")) == "6'4\"+"
    assert _height_band_label(_parse_tm_height_cm("5 ft 8 in")) == "<5'9\""


def test_profiles_without_heights_are_unusable():
    assert not _tm_profiles_have_heights(
        {"tombooth": {"name": "Tom Booth", "height_cm": None}}
    )
    assert _tm_profiles_have_heights(
        {"tombooth": {"name": "Tom Booth", "height_cm": 191}}
    )


def test_backfill_uses_previous_season_height(monkeypatch):
    current = {"owentaylor": {"name": "Owen Taylor", "height_cm": None}}
    previous = {"owentaylor": {"name": "Owen Taylor", "height_cm": 175}}
    monkeypatch.setattr(
        "app.set_piece_pre_match._read_json_cache",
        lambda *args, **kwargs: previous,
    )
    monkeypatch.setattr(
        "app.set_piece_pre_match._tm_profiles_disk_path",
        lambda *args, **kwargs: "dummy",
    )
    filled = _backfill_tm_heights_from_previous_season(current, 1042, 2026)
    assert filled["owentaylor"]["height_cm"] == 175
