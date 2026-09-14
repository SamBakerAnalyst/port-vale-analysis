"""LMS Sports AI Consultancy is a branded blank demo of the same hub."""

from __future__ import annotations

from pathlib import Path

from app.apps_manifest import manifest_payload
from app.auth import session_secret
from app.brand import apply_brand_html, current_brand, is_demo, reveal_all_tools
from app.home_dashboard import build_port_vale_fixtures, build_strategy_snapshot


def test_default_brand_is_port_vale(monkeypatch):
    monkeypatch.delenv("HUB_PROFILE", raising=False)
    monkeypatch.delenv("HUB_ENV", raising=False)
    brand = current_brand()
    assert brand.id == "portvale"
    assert brand.club == "Port Vale"
    assert brand.demo is False
    assert brand.session_cookie == "pv_hub_session"
    assert is_demo() is False
    assert "Port Vale Live" in brand.product


def test_staging_stays_port_vale(monkeypatch):
    monkeypatch.delenv("HUB_PROFILE", raising=False)
    monkeypatch.setenv("HUB_ENV", "staging")
    brand = current_brand()
    assert brand.id == "portvale"
    assert brand.product == "Port Vale Staging"
    assert brand.demo is False
    assert reveal_all_tools() is True
    payload = manifest_payload(role="admin")
    assert payload["product"] == "Port Vale Staging"
    assert payload["product_id"] == "staging"
    assert payload["staging"] is True
    assert payload["brand"]["id"] == "portvale"


def test_lms_profile_is_blank_demo(monkeypatch):
    monkeypatch.setenv("HUB_PROFILE", "lms")
    monkeypatch.setenv("HUB_ENV", "demo")
    brand = current_brand()
    assert brand.id == "lms"
    assert brand.org == "LMS Sports AI Consultancy"
    assert brand.demo is True
    assert brand.club == ""
    assert brand.session_cookie == "lms_hub_session"
    assert reveal_all_tools() is True
    payload = manifest_payload(role="admin")
    assert payload["product"] == "LMS Sports AI Consultancy"
    assert payload["product_id"] == "demo"
    assert payload["staging"] is True
    assert payload["brand"]["demo"] is True
    assert payload["brand"]["badge"] == "/standalone/lms-badge.svg"


def test_lms_rewrites_login_chrome_only(monkeypatch):
    monkeypatch.setenv("HUB_PROFILE", "lms")
    monkeypatch.setenv("HUB_ENV", "demo")
    html = apply_brand_html(
        """<title>Sign in · Port Vale Analysis Hub</title>
        <body>
        <img src="/standalone/port-vale-badge.png?v=2" alt="Port Vale FC crest" />
        <div>Port Vale FC</div>
        <p>For Port Vale staff use only</p></body>"""
    )
    assert "Port Vale" not in html
    assert "LMS Sports AI Consultancy" in html
    assert "/standalone/lms-badge.svg" in html
    assert 'class="is-demo-hub"' in html


def test_port_vale_html_is_untouched(monkeypatch):
    monkeypatch.delenv("HUB_PROFILE", raising=False)
    monkeypatch.delenv("HUB_ENV", raising=False)
    raw = '<div class="rail__club">Port Vale FC</div>'
    assert apply_brand_html(raw) == raw


def test_demo_home_data_is_empty(monkeypatch):
    monkeypatch.setenv("HUB_PROFILE", "lms")
    monkeypatch.setenv("HUB_ENV", "demo")
    fixtures = build_port_vale_fixtures()
    assert fixtures["demo"] is True
    assert fixtures["played"] == []
    assert fixtures["upcoming"] == []
    assert fixtures["matches"] == []
    strategy = build_strategy_snapshot()
    assert strategy["demo"] is True
    assert strategy.get("pace") == {}


def test_lms_uses_a_separate_session_cookie(monkeypatch):
    monkeypatch.setenv("HUB_PROFILE", "lms")
    # session_secret still works; cookie name is what isolates Vale vs LMS on the same IP.
    assert current_brand().session_cookie == "lms_hub_session"
    assert session_secret()


def test_lms_compose_must_not_use_service_name_hub():
    """LMS joins Live's Docker network. Service name 'hub' on that network
    made Caddy send pvfc / the staff IP to the LMS demo."""
    from pathlib import Path

    text = Path("deploy/docker-compose.lms.yml").read_text()
    assert "\n  hub:" not in text
    assert "\n  lms:" in text
    assert "aliases:" in text
    assert "- lms" in text


def test_live_caddy_must_not_proxy_generic_hub_dns():
    text = Path("deploy/Caddyfile.ip").read_text()
    assert "reverse_proxy hub:8000" not in text
    assert "reverse_proxy port-vale-analysis-hub-1:8000" in text
    assert "reverse_proxy lms:8000" in text
    assert "pvfc.sportsanalysis.ai" in text
    assert "lmsc.sportsanalysis.ai" in text
    assert Path("deploy/check-live-caddy.sh").is_file()
