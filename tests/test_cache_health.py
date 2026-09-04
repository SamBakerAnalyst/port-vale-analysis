"""Cache health checks.

The failure this exists to catch: Live's Who To Scout cache was a 3-byte file
dated 20 August. It existed, so nothing complained, and the tool quietly
rebuilt from Impect on every cold start for a fortnight. An "exists" check
would have passed it — hence the size floor.
"""

from __future__ import annotations

import os
import time

from app.cache_health import (
    MISSING,
    OK,
    STALE,
    THIN,
    CacheCheck,
    _humanise_duration,
    _measure,
    _verdict,
    build_cache_health,
)


def _check(tmp_path, **kw) -> CacheCheck:
    defaults = dict(
        id="probe",
        label="Probe",
        tool="Probe tool",
        path=tmp_path / "probe.json",
        max_age_hours=36,
        min_bytes=1_000,
    )
    defaults.update(kw)
    return CacheCheck(**defaults)


def test_a_three_byte_file_is_thin_not_ok(tmp_path):
    """The exact shape of the Live failure — present, fresh, and useless."""
    check = _check(tmp_path)
    check.path.write_text("{}\n")  # 3 bytes, written just now

    size, age = _measure(check)
    status, detail = _verdict(check, size, age)

    assert size == 3
    assert status == THIN, "a fresh but empty cache must not read as healthy"
    assert "3 bytes" in detail


def test_a_real_payload_is_ok(tmp_path):
    check = _check(tmp_path)
    check.path.write_text("x" * 5_000)

    size, age = _measure(check)
    status, _ = _verdict(check, size, age)
    assert status == OK


def test_an_old_file_is_stale(tmp_path):
    check = _check(tmp_path, max_age_hours=1)
    check.path.write_text("x" * 5_000)
    old = time.time() - 6 * 3600
    os.utime(check.path, (old, old))

    size, age = _measure(check)
    status, detail = _verdict(check, size, age)
    assert status == STALE
    assert "expected inside" in detail


def test_a_file_that_was_never_written_is_missing(tmp_path):
    check = _check(tmp_path)
    size, age = _measure(check)
    status, detail = _verdict(check, size, age)
    assert (size, age) == (0, None)
    assert status == MISSING
    assert "rebuilds it from Impect" in detail


def test_thin_beats_stale_so_the_real_fault_is_reported(tmp_path):
    """Live's file was both tiny and ancient; the useful message is 'not writing'."""
    check = _check(tmp_path, max_age_hours=1)
    check.path.write_text("{}\n")
    old = time.time() - 400 * 24 * 3600
    os.utime(check.path, (old, old))

    size, age = _measure(check)
    status, _ = _verdict(check, size, age)
    assert status == THIN


def test_directory_caches_sum_size_and_use_the_newest_file(tmp_path):
    d = tmp_path / "cachedir"
    (d / "nested").mkdir(parents=True)
    (d / "a.json").write_text("x" * 600)
    (d / "nested" / "b.json").write_text("x" * 600)
    old = time.time() - 10 * 3600
    os.utime(d / "a.json", (old, old))

    check = _check(tmp_path, path=d, is_dir=True, min_bytes=1_000)
    size, age = _measure(check)

    assert size == 1_200, "directory size should include nested files"
    assert age is not None and age < 1, "age should follow the newest file, not the oldest"
    assert _verdict(check, size, age)[0] == OK


def test_an_empty_directory_is_missing(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    check = _check(tmp_path, path=d, is_dir=True)
    assert _verdict(check, *_measure(check))[0] == MISSING


def test_payload_leads_with_problems_and_counts_them():
    payload = build_cache_health()

    assert set(payload) >= {"checked_at", "healthy", "problem_count", "caches"}
    statuses = [row["status"] for row in payload["caches"]]
    problems = [s for s in statuses if s != OK]
    assert payload["problem_count"] == len(problems)
    assert payload["healthy"] == (not problems)
    # Anything broken must sort above the healthy rows.
    if problems:
        assert statuses[0] != OK, "problems should be listed first"


def test_every_check_has_a_size_floor():
    """Without one, the 3-byte failure passes as healthy again."""
    from app.cache_health import CHECKS

    for check in CHECKS:
        assert check.min_bytes > 0, f"{check.id} has no size floor"
        assert check.max_age_hours > 0, f"{check.id} has no age limit"


def test_durations_read_as_english():
    assert _humanise_duration(0.25) == "15 minutes"
    assert _humanise_duration(2) == "2.0 hours"
    assert _humanise_duration(72) == "3.0 days"
