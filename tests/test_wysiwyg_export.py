"""WYSIWYG PNG export must not hang or POST huge Through a Lens photos."""

from app.paths import HUB_ROOT, STATIC_DIR


def test_png_zip_compresses_and_batches_large_packs():
    js = (STATIC_DIR / "wysiwyg-export.js").read_text(encoding="utf-8")
    assert "compressImageBlob" in js
    assert "pagesPerRequest" in js
    assert "image/jpeg" in js
    assert "JSZip.loadAsync" in js


def test_capture_waits_for_load_not_networkidle():
    text = (HUB_ROOT / "app" / "wysiwyg_capture.py").read_text(encoding="utf-8")
    assert 'wait_until="load"' in text
    assert 'wait_until="networkidle"' not in text
