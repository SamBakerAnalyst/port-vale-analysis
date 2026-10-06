"""Player overview — scout report roll-up and summary for the player landing page."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
from collections import Counter
from datetime import UTC, datetime
from typing import Any

import requests

from app.paths import DATA_ROOT

SUMMARY_CACHE_PATH = DATA_ROOT / "player-report-summaries.json"
_summary_lock = threading.Lock()

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
OPENAI_TIMEOUT = 40
MAX_REPORT_CHARS = 1800

PVFC_LEVEL_TITLES = {
    "A": "Starter",
    "B": "Challenger",
    "C": "Emerging talent",
    "D": "Not to standard",
}
NEXT_ACTION_TITLES = {
    "not_to_standard": "Not to standard",
    "low_priority": "Low priority",
    "high_priority": "High priority",
    "sign": "Sign",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _library_reports_for_player(player_id: int) -> list[dict[str, Any]]:
    """General + detailed Match Scouting reports (Reports Library) merged per fixture."""
    try:
        from app.player_reports import all_report_rows, report_scout
    except Exception:
        return []
    try:
        store = all_report_rows()
    except Exception:
        return []
    prefix = f"{int(player_id)}:"
    merged: dict[str, dict[str, Any]] = {}
    for section in ("general_reports", "detailed_reports"):
        for key, row in (store.get(section) or {}).items():
            if not str(key).startswith(prefix) or not isinstance(row, dict):
                continue
            slot = merged.setdefault(str(key), {"fixture_id": str(key)[len(prefix):]})
            slot[section] = row

    rows: list[dict[str, Any]] = []
    for slot in merged.values():
        general = slot.get("general_reports") or {}
        detailed = slot.get("detailed_reports") or {}
        primary = detailed or general
        body_parts = [
            _text(detailed.get("write_up")),
            _text(general.get("notes")),
        ]
        body = "\n".join(part for part in body_parts if part)
        next_steps = _text(detailed.get("next_steps")) or _text(general.get("next_steps"))
        rating = detailed.get("match_rating")
        if rating is None:
            rating = general.get("match_rating")
        level = _text(detailed.get("pvfc_level") or general.get("pvfc_level")).upper()
        action = _text(detailed.get("next_action") or general.get("next_action"))
        if not (body or next_steps or rating is not None or level or action):
            continue
        info = primary.get("match_info") if isinstance(primary.get("match_info"), dict) else {}
        date = _text(info.get("match_date")) or _text(primary.get("created_at"))[:10] or _text(primary.get("updated_at"))[:10]
        scout = report_scout(detailed) or report_scout(general)
        if scout.casefold() == "staff":
            scout = ""
        rows.append(
            {
                "source": "library",
                "fixture": _text(primary.get("fixture_label")) or "Scouting report",
                "date": date[:10],
                "scout": scout,
                "position": _text(primary.get("position_in_game")),
                "viewing": _text(info.get("viewing")),
                "match_rating": float(rating) if rating is not None else None,
                "pvfc_level": level if level in PVFC_LEVEL_TITLES else "",
                "next_action": action if action in NEXT_ACTION_TITLES else "",
                "current_ability": None,
                "potential_ability": None,
                "text": body,
                "next_steps": next_steps,
                "href": "/reports-library",
            }
        )
    return rows


def _hub_reports_for_player(player_id: int, name: str) -> list[dict[str, Any]]:
    """Reports filed on the player page + fixture planner (no example placeholders)."""
    from app.player_dossier import _split_player_activity

    _notes, reports = _split_player_activity(player_id, name)
    rows: list[dict[str, Any]] = []
    for row in reports:
        if row.get("example"):
            continue
        rows.append(
            {
                "source": row.get("source") or "dossier",
                "fixture": _text(row.get("fixture")) or "Scout report",
                "date": _text(row.get("date"))[:10],
                "scout": _text(row.get("staff")),
                "position": _text(row.get("position")),
                "viewing": "",
                "match_rating": None,
                "pvfc_level": "",
                "next_action": "",
                "current_ability": row.get("current_ability"),
                "potential_ability": row.get("potential_ability"),
                "text": _text(row.get("summary")),
                "next_steps": "",
                "href": row.get("href"),
                "id": row.get("id") if row.get("editable") else None,
            }
        )
    return rows


def collect_player_reports(player_id: int, name: str) -> list[dict[str, Any]]:
    rows = _library_reports_for_player(player_id) + _hub_reports_for_player(player_id, name)
    rows.sort(key=lambda item: item.get("date") or "", reverse=True)
    return rows


def _avg(values: list[float]) -> float | None:
    clean = [float(v) for v in values if v is not None]
    if not clean:
        return None
    return int(sum(clean) / len(clean) * 10 + 0.5) / 10


def _report_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    dates = sorted(d for d in (row.get("date") for row in rows) if d)
    scouts = sorted({row["scout"] for row in rows if row.get("scout")})
    levels = Counter(row["pvfc_level"] for row in rows if row.get("pvfc_level"))
    level = levels.most_common(1)[0][0] if levels else ""
    latest_action = next((row["next_action"] for row in rows if row.get("next_action")), "")
    return {
        "count": len(rows),
        "scouts": scouts,
        "first_date": dates[0] if dates else None,
        "last_date": dates[-1] if dates else None,
        "avg_match_rating": _avg([row.get("match_rating") for row in rows]),
        "avg_current_ability": _avg([row.get("current_ability") for row in rows]),
        "avg_potential_ability": _avg([row.get("potential_ability") for row in rows]),
        "pvfc_level": level,
        "pvfc_level_title": PVFC_LEVEL_TITLES.get(level, ""),
        "pvfc_level_votes": dict(levels),
        "next_action": latest_action,
        "next_action_title": NEXT_ACTION_TITLES.get(latest_action, ""),
    }


def _first_sentences(text: str, limit: int = 2) -> str:
    parts = re.split(r"(?<=[.!?])\s+", _text(text).replace("\n", " "))
    return " ".join(part for part in parts[:limit] if part).strip()


def _fallback_summary(name: str, rows: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    scouts = stats["scouts"]
    lead = f"{stats['count']} report{'s' if stats['count'] != 1 else ''}"
    if scouts:
        lead += f" from {len(scouts)} scout{'s' if len(scouts) != 1 else ''}"
    verdict_bits = []
    if stats["pvfc_level"]:
        verdict_bits.append(f"consensus level {stats['pvfc_level']} ({stats['pvfc_level_title']})")
    if stats["avg_match_rating"] is not None:
        verdict_bits.append(f"average match rating {stats['avg_match_rating']}/10")
    if stats["avg_current_ability"] is not None or stats["avg_potential_ability"] is not None:
        ability = " / ".join(
            f"{label} {value}/5"
            for label, value in (("CA", stats["avg_current_ability"]), ("PA", stats["avg_potential_ability"]))
            if value is not None
        )
        verdict_bits.append(f"average {ability}")
    if stats["next_action_title"]:
        verdict_bits.append(f"latest recommendation: {stats['next_action_title'].lower()}")
    headline = lead + (" — " + ", ".join(verdict_bits) if verdict_bits else "") + "."
    points = []
    for row in rows[:3]:
        snippet = _first_sentences(row.get("text") or row.get("next_steps") or "")
        if snippet:
            who = row.get("scout") or "Scout"
            points.append(f"{who}: {snippet}")
    return {
        "headline": headline,
        "strengths": [],
        "concerns": [],
        "points": points,
        "recommendation": stats["next_action_title"] or "",
        "engine": "built-in",
    }


def _openai_summary(name: str, rows: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any] | None:
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        return None
    model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini").strip() or "gpt-4o-mini"
    blocks = []
    for idx, row in enumerate(rows[:12], start=1):
        meta = ", ".join(
            bit
            for bit in (
                row.get("date"),
                row.get("fixture"),
                f"scout {row['scout']}" if row.get("scout") else "",
                f"position {row['position']}" if row.get("position") else "",
                f"rating {row['match_rating']}/10" if row.get("match_rating") is not None else "",
                f"level {row['pvfc_level']}" if row.get("pvfc_level") else "",
                f"next action {row['next_action']}" if row.get("next_action") else "",
                f"CA {row['current_ability']}/5" if row.get("current_ability") is not None else "",
                f"PA {row['potential_ability']}/5" if row.get("potential_ability") is not None else "",
            )
            if bit
        )
        body = (row.get("text") or "")[:MAX_REPORT_CHARS]
        if row.get("next_steps"):
            body += f"\nNext steps: {row['next_steps'][:400]}"
        blocks.append(f"Report {idx} ({meta}):\n{body or '(no write-up)'}")
    prompt = (
        f"You are the head of recruitment at Port Vale FC. Summarise these scout reports on {name} "
        "for the manager. Be concrete and football-specific, British English, no fluff. "
        "Return JSON with keys: headline (one or two sentences overall verdict), strengths (list of up to 4 short bullets), "
        "concerns (list of up to 3 short bullets), recommendation (one short sentence on next step).\n\n"
        + "\n\n".join(blocks)
    )
    try:
        response = requests.post(
            OPENAI_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "temperature": 0.3,
                "response_format": {"type": "json_object"},
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=OPENAI_TIMEOUT,
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        data = json.loads(content)
    except Exception:
        return None
    return {
        "headline": _text(data.get("headline")),
        "strengths": [_text(x) for x in (data.get("strengths") or []) if _text(x)][:4],
        "concerns": [_text(x) for x in (data.get("concerns") or []) if _text(x)][:3],
        "points": [],
        "recommendation": _text(data.get("recommendation")),
        "engine": "ai",
        "model": model,
    }


def _load_cache() -> dict[str, Any]:
    try:
        payload = json.loads(SUMMARY_CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _save_cache(payload: dict[str, Any]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    temp = SUMMARY_CACHE_PATH.with_suffix(".json.tmp")
    temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp.replace(SUMMARY_CACHE_PATH)


def _fingerprint(rows: list[dict[str, Any]]) -> str:
    raw = json.dumps(rows, sort_keys=True, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]


def build_reports_summary(player_id: int, name: str, *, refresh: bool = False) -> dict[str, Any]:
    rows = collect_player_reports(player_id, name)
    stats = _report_stats(rows)
    base = {
        "player_id": player_id,
        "count": len(rows),
        "stats": stats,
        "reports": rows[:8],
    }
    if not rows:
        return {**base, "summary": None}

    fingerprint = _fingerprint(rows)
    ai_enabled = bool(os.environ.get("OPENAI_API_KEY", "").strip())
    with _summary_lock:
        cached = _load_cache().get(str(player_id))
    if (
        not refresh
        and isinstance(cached, dict)
        and cached.get("fingerprint") == fingerprint
        and (cached.get("summary") or {}).get("engine") == ("ai" if ai_enabled else "built-in")
    ):
        return {**base, "summary": cached["summary"], "generated_at": cached.get("generated_at")}

    summary = _openai_summary(name, rows, stats) or _fallback_summary(name, rows, stats)
    generated_at = datetime.now(UTC).isoformat()
    if summary.get("engine") == "ai":
        with _summary_lock:
            cache = _load_cache()
            cache[str(player_id)] = {
                "fingerprint": fingerprint,
                "summary": summary,
                "generated_at": generated_at,
            }
            _save_cache(cache)
    return {**base, "summary": summary, "generated_at": generated_at}
