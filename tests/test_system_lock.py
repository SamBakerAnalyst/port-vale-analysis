"""Owner-controlled system lock — non-admin accounts are blocked until unpaid terms are resolved."""

from __future__ import annotations

from app.auth import (
    LOCK_MESSAGE,
    LOCK_TITLE,
    _lock_page_html,
    _path_allowed_for_role,
    set_system_locked,
    system_locked,
)


def test_lock_defaults_off_until_admin_locks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.auth._lock_path", lambda: tmp_path / "system_lock.json")
    assert system_locked() is False
    set_system_locked(True)
    assert system_locked() is True
    set_system_locked(False)
    assert system_locked() is False


def test_lock_page_shows_the_unpaid_invoice_copy():
    html = _lock_page_html()
    assert LOCK_TITLE in html
    assert LOCK_MESSAGE in html
    assert "Close" not in html


def test_any_signed_in_role_can_read_lock_status():
    assert _path_allowed_for_role("/api/system-lock", "analysis")
    assert _path_allowed_for_role("/api/system-lock", "scouts")
    assert _path_allowed_for_role("/api/system-lock", "ops")
    assert _path_allowed_for_role("/api/system-lock", "admin")


def test_admin_payload_can_close_lock_preview():
    from app.auth import current_user_payload

    class _Sess(dict):
        pass

    class _Req:
        session = _Sess(authenticated=True, role="admin", username="PortVale")

    payload = current_user_payload(_Req())
    assert payload["system_lock"]["can_close"] is True
    assert payload["system_lock"]["title"] == LOCK_TITLE
    assert payload["system_lock"]["message"] == LOCK_MESSAGE


def test_non_admin_payload_cannot_close_lock_preview():
    from app.auth import current_user_payload

    class _Sess(dict):
        pass

    class _Req:
        session = _Sess(authenticated=True, role="analysis", username="analyst")

    payload = current_user_payload(_Req())
    assert payload["system_lock"]["can_close"] is False
