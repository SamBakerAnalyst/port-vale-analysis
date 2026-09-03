"""Summer 26/27 window-review Present deck lives on the Presentations gallery."""

from app.apps_manifest import APPS, required_sidebar_titles
from app.window_review import (
    AFTER_AGE,
    AFTER_OWNED_AGE,
    AFTER_SIZE,
    BEFORE_AGE,
    BEFORE_OWNED_AGE,
    INS_COUNT,
    LOAN_AGE,
    LOANS_AFTER,
    LOANS_BEFORE,
    OUTS_COUNT,
)


def test_window_review_is_personal_presentation():
    titles = required_sidebar_titles()
    assert "Summer Window Review" not in titles
    row = next(app for app in APPS if app["id"] == "window-review")
    assert row["href"] == "/window-review"
    assert row["group"] == "presentations"
    assert row.get("sidebar") is False
    assert tuple(row["roles"]) == ("admin",)


def test_window_review_html_has_core_slides():
    from app.paths import STANDALONE_DIR

    html = STANDALONE_DIR / "window-review.html"
    assert html.is_file()
    text = html.read_text(encoding="utf-8")
    assert "Summer window review" in text
    assert "Permanent ins" in text
    assert "Loans" in text
    assert "Average age" in text
    assert "January leavers" in text
    assert "Byers · Craig" in text
    assert "Croasdale · Garrity · Dempsey" in text
    assert 'pcard__pos">MF</span>' in text
    assert 'pcard__pos">DM</span>' in text
    assert "All 19" in text
    assert "sum-units" in text


def test_window_review_snapshot_numbers():
    assert INS_COUNT == 12
    assert OUTS_COUNT == 19
    assert AFTER_SIZE == 26
    assert BEFORE_AGE == 27.0
    assert AFTER_AGE == 26.3
    assert AFTER_OWNED_AGE == 27.1
    assert BEFORE_OWNED_AGE == 27.9
    assert LOAN_AGE == 21.8
    assert LOANS_BEFORE == 5
    assert LOANS_AFTER == 4
