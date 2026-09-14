"""Hub product brand / tenant profile.

Port Vale Live and Staging stay the default. Set HUB_PROFILE=lms (and usually
HUB_ENV=demo) for the LMS Sports AI Consultancy blank demo hub.

This module is a leaf — do not import other app packages here.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class HubBrand:
    id: str
    org: str
    org_short: str
    product: str
    stamp: str
    club: str
    badge: str
    login_title: str
    login_subtitle: str
    login_footer: str
    greeting: str
    session_cookie: str
    demo: bool
    reveal_all: bool
    stamp_title: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "org": self.org,
            "org_short": self.org_short,
            "product": self.product,
            "stamp": self.stamp,
            "club": self.club,
            "badge": self.badge,
            "login_title": self.login_title,
            "login_subtitle": self.login_subtitle,
            "login_footer": self.login_footer,
            "greeting": self.greeting,
            "demo": self.demo,
            "reveal_all": self.reveal_all,
            "stamp_title": self.stamp_title,
        }


_PORTVALE = HubBrand(
    id="portvale",
    org="Port Vale FC",
    org_short="Port Vale FC",
    product="Port Vale Hub",
    stamp="",  # filled from HUB_ENV (Live vs Staging) in current_brand()
    club="Port Vale",
    badge="/standalone/port-vale-badge.png?v=2",
    login_title="Analysis Hub",
    login_subtitle="Sign in to access the tools",
    login_footer="For Port Vale staff use only",
    greeting="Port Vale",
    session_cookie="pv_hub_session",
    demo=False,
    reveal_all=False,
    stamp_title="Port Vale Live — staff / boss product",
)

_LMS = HubBrand(
    id="lms",
    org="LMS Sports AI Consultancy",
    org_short="LMS Sports",
    product="LMS Sports AI Consultancy",
    stamp="LMS Demo",
    club="",
    badge="/standalone/lms-badge.svg",
    login_title="Analysis Hub",
    login_subtitle="Blank demo hub — sign in to look around",
    login_footer="Demo environment · no club data loaded",
    greeting="LMS Sports",
    session_cookie="lms_hub_session",
    demo=True,
    reveal_all=True,
    stamp_title="LMS Sports AI Consultancy — blank demo hub (not Port Vale)",
)

_PROFILES = {
    "portvale": _PORTVALE,
    "port-vale": _PORTVALE,
    "vale": _PORTVALE,
    "lms": _LMS,
    "lms-sports": _LMS,
    "lms-demo": _LMS,
}


def hub_env() -> str:
    return os.getenv("HUB_ENV", "").strip().lower()


def profile_id() -> str:
    raw = os.getenv("HUB_PROFILE", "").strip().lower()
    if raw in _PROFILES:
        return _PROFILES[raw].id
    env = hub_env()
    if env in {"demo", "lms"}:
        return "lms"
    return "portvale"


def is_staging_env() -> bool:
    return hub_env() == "staging"


def is_demo() -> bool:
    return current_brand().demo


def reveal_all_tools() -> bool:
    if hub_env() in {"staging", "demo"}:
        return True
    return current_brand().reveal_all


def current_brand() -> HubBrand:
    profile = _PROFILES.get(profile_id(), _PORTVALE)
    if profile.id == "lms":
        return profile
    staging = is_staging_env()
    return HubBrand(
        id=profile.id,
        org=profile.org,
        org_short=profile.org_short,
        product="Port Vale Staging" if staging else "Port Vale Live",
        stamp="Port Vale Staging" if staging else "Port Vale Live",
        club=profile.club,
        badge=profile.badge,
        login_title=profile.login_title,
        login_subtitle=profile.login_subtitle,
        login_footer=profile.login_footer,
        greeting=profile.greeting,
        session_cookie=profile.session_cookie,
        demo=False,
        reveal_all=staging,
        stamp_title=(
            "Port Vale Staging — safe break/fix sandbox (not staff)"
            if staging
            else "Port Vale Live — staff / boss product"
        ),
    )


def apply_brand_html(html: str) -> str:
    """Rewrite Port Vale chrome strings when this process is the LMS demo.

    Port Vale HTML is left byte-for-byte alone so Live/Staging cannot drift.
    """
    brand = current_brand()
    if brand.id != "lms":
        return html
    pairs = (
        ("Sign in · Port Vale Analysis Hub", f"Sign in · {brand.product}"),
        ("<title>Port Vale Hub</title>", f"<title>{brand.product}</title>"),
        ("<title>Port Vale FC — Analysis</title>", f"<title>{brand.product}</title>"),
        ('src="/standalone/port-vale-badge.png?v=2"', f'src="{brand.badge}"'),
        ('alt="Port Vale FC crest"', f'alt="{brand.org}"'),
        ('<div class="rail__club">Port Vale FC</div>', f'<div class="rail__club">{brand.org_short}</div>'),
        (">Port Vale FC<", f">{brand.org}<"),
        ("For Port Vale staff use only", brand.login_footer),
        ("Sign in to access the tools", brand.login_subtitle),
        (
            ">Port Vale Live · __HUB_BUILD__<",
            f">{brand.stamp} · __HUB_BUILD__<",
        ),
        (">Port Vale · League Two<", f">{brand.org} · Demo<"),
        (">Port Vale fixtures<", ">Club fixtures<"),
        (">Port Vale vs League Two<", ">Squad vs league<"),
        (">Port Vale vs league<", ">Squad vs league<"),
        ("    Internal use only · Port Vale FC", f"Demo · {brand.org}"),
    )
    out = html
    for old, new in pairs:
        out = out.replace(old, new)
    # CSS already mentions is-demo-hub, so do not use a whole-file substring check.
    out = out.replace("<body>", '<body class="is-demo-hub">', 1)
    return out
