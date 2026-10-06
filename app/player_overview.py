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


_CONTEXT_DATE_RE = re.compile(r"\bon (\d{1,2})/(\d{1,2})/(\d{4})\b")


def _date_from_text(text: str) -> str:
    match = _CONTEXT_DATE_RE.search(text or "")
    if not match:
        return ""
    day, month, year = (int(part) for part in match.groups())
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return ""
    return f"{year:04d}-{month:02d}-{day:02d}"


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
        fixture_date = re.search(r"\d{4}-\d{2}-\d{2}", slot.get("fixture_id") or "")
        date = (
            _text(info.get("match_date"))
            or (fixture_date.group(0) if fixture_date else "")
            or _date_from_text(body)
            or _text(primary.get("created_at"))[:10]
            or _text(primary.get("updated_at"))[:10]
        )
        physical = {}
        for source in (general.get("physical"), detailed.get("physical")):
            if isinstance(source, dict):
                physical.update({k: v for k, v in source.items() if _text(v)})
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
                "position_label": _position_words(_text(primary.get("position_in_game"))),
                "viewing": _text(info.get("viewing")),
                "match_rating": float(rating) if rating is not None else None,
                "pvfc_level": level if level in PVFC_LEVEL_TITLES else "",
                "next_action": action if action in NEXT_ACTION_TITLES else "",
                "current_ability": None,
                "potential_ability": None,
                "text": body,
                "next_steps": next_steps,
                "physical": physical,
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


def _is_duplicate_of_library(row: dict[str, Any], library: list[dict[str, Any]]) -> bool:
    """Same write-up copied into the notes store during the Gemini migration."""
    sentences = {s.casefold() for s in _clean_report_text(row.get("text") or "") if len(s) > 25}
    if not sentences:
        return False
    for other in library:
        other_text = (other.get("text") or "").casefold()
        if sum(1 for s in sentences if s in other_text) >= max(1, len(sentences) // 2):
            return True
    return False


def collect_player_reports(player_id: int, name: str) -> list[dict[str, Any]]:
    library = _library_reports_for_player(player_id)
    hub = [row for row in _hub_reports_for_player(player_id, name) if not _is_duplicate_of_library(row, library)]
    rows = library + hub
    for row in hub:
        if not row.get("scout"):
            match = re.search(r"Original scout \(Gemini\):\s*([^—\n]+?)\s*—", row.get("text") or "")
            if match:
                row["scout"] = match.group(1).strip()
        row.setdefault("position_label", _position_words(row.get("position") or ""))
        if row.get("fixture", "").casefold().startswith("gemini scout report"):
            row["fixture"] = "Scout report (migrated)"
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


_BOILERPLATE_RES = [
    re.compile(p, re.I)
    for p in (
        r"^\[?migrated from gemini[^\]\n]*\]?",
        r"^original scout\b.*$",
        r"^match \(gemini\):.*$",
        r"^gemini (technical|physical|mental) ratings:.*$",
        r"^gemini match performance:.*$",
        r"^gemini verdict:.*$",
        r"^note: gemini.*$",
        r"^separate from\b.*$",
        r"^\[anything else continued\]\s*$",
        r"^(tommy johnson|tom fry|lee darnbrough|[a-z]+ [a-z]+) (\w+ )?report\s+[—-].*$",
    )
]
_LABEL_RE = re.compile(r"^(scout comments|player notes|comments|notes|summary|write[- ]?up)\s*:\s*", re.I)
_MINUTE_RE = re.compile(r"\(\d{1,3}(?:,\s*\d{1,3})*\)|\b\d{1,3}(?:st|nd|rd|th)? min\b", re.I)

_POSITIVE = (
    "good", "great", "excellent", "strong", "composed", "confident", "assured", "reliable",
    "accurate", "clean", "quick", "quickly", "sharp", "brave", "vocal", "organis", "command",
    "technically", "vision", "comfortable", "decent", "important save", "key save", "well",
    "nice", "impressive", "threat", "dangerous", "scored", "intelligent", "clever", "calm",
    "aggressive", "dominant", "commanding", "creative", "fine", "solid", "positive", "lively",
    "energetic", "hard working", "worked hard", "tidy", "neat", "skilful", "skillful", "pace",
    "powerful", "reflex", "athletic", "agile", "excellent", "stands out", "liked",
)
_NEGATIVE = (
    "poor", "struggl", "lack", "needs to", "need to", "could he", "can he", "inconsistent",
    "inconsistency", "nervous", "mistake", "error", "fumbl", "awkward", "lucky", "weak",
    "slow", "didn't", "did not", "odd", "overhit", "careless", "sloppy", "hesitant",
    "hesitat", "misjudg", "wasteful", "missed", "gave away", "lost the ball", "caught out",
    "not great", "not the best", "could have done better", "should have", "too often",
    "frustrat", "limited", "lightweight", "bouncy", "concern", "worry", "worried",
    "fill out", "unconvincing", "erratic", "rushed", "panick", "dropped", "spilled",
)

_THEMES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Shot-stopping", ("save", "saves", "saved", "reflex", "parr", "fingertip", "tipped", "penalty save", "shot-stop", "shot stop", "dives", "1v1")),
    ("Distribution", ("kick", "kicking", "kicks", "distribution", "goal kick", "throw out", "threw the ball", "long ball", "short passing", "release the ball", "released the ball")),
    ("Crosses & aerial play", ("cross", "crosses", "claim", "claims", "claimed", "punch", "punches", "punched", "aerial ball", "high ball", "corner delivery", "from a corner", "comes for", "came to collect", "came and dealt")),
    ("Physique & size", ("good size", "size", "tall", "lean", "slim", "skinny", "frame", "fill out", "physically", "physique", "strong build", "lean build", "slim build", "6'", "6’")),
    ("Communication & leadership", ("vocal", "organis", "communicat", "leader", "talking", "instruct")),
    ("Composure & decisions", ("composed", "composure", "decision", "decisions", "under pressure", "pressured", "nervous", "calm", "panic", "assured")),
    ("Technique & ball carrying", ("touch", "technically", "technical", "technique", "carried", "carry", "carries", "dribbl", "ball control", "skilful", "skillful", "1v1s")),
    ("Finishing & goal threat", ("finish", "finishing", "scored", "goal threat", "shooting", "shots on", "on target", "header on goal", "chances")),
    ("Passing & vision", ("passing", "pass", "passes", "vision", "through ball", "assist", "switch of play", "range of pass", "weighted")),
    ("Pace & athleticism", ("pace", "pacey", "quick feet", "speed", "sprint", "sprints", "acceleration", "mobility", "agile", "athletic", "explosive", "rapid")),
    ("Defending & duels", ("tackle", "tackles", "duel", "duels", "intercept", "defending", "defensively", "aerial duel", "blocks", "recovery run")),
    ("Work rate & pressing", ("work rate", "worked hard", "pressing", "presses", "track back", "tracked back", "tracks back", "energy")),
    ("Movement & positioning", ("movement", "runs in behind", "in behind", "between the lines", "tucked", "inside the pitch", "drifts", "found him in space", "positioning", "positional")),
)
_THEME_RES = tuple(
    (label, re.compile("|".join(r"(?<![\w])" + re.escape(word) for word in words), re.I))
    for label, words in _THEMES
)


def _clean_report_text(text: str) -> list[str]:
    """Scout comments split into sentences, without migration headers or labels."""
    lines: list[str] = []
    for raw in _text(text).splitlines():
        line = raw.strip().lstrip("•-*·\t ").strip()
        if not line:
            continue
        if any(rx.search(line) for rx in _BOILERPLATE_RES):
            continue
        line = _LABEL_RE.sub("", line).strip().lstrip("•-*·\t ").strip()
        if line:
            lines.append(line)
    sentences: list[str] = []
    for line in lines:
        for part in re.split(r"(?<=[.!?])\s+|\s+•\s+", line):
            part = _MINUTE_RE.sub("", part).strip(" .;,-–—")
            part = re.sub(r"\s{2,}", " ", part)
            if len(part) >= 12 and len(part.split()) >= 3:
                sentences.append(part)
    return sentences


def _tone(sentence: str) -> int:
    low = sentence.casefold()
    pos = sum(1 for word in _POSITIVE if word in low)
    neg = sum(1 for word in _NEGATIVE if word in low)
    if "?" in sentence:
        neg += 1
    return (pos > neg) - (neg > pos)


def _themes_for(sentence: str) -> list[str]:
    return [label for label, rx in _THEME_RES if rx.search(sentence)]


def _short_quote(sentence: str, limit: int = 110) -> str:
    text = sentence.strip()
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0]
    return cut.rstrip(",;:- ") + "…"


def _mode(values: list[str]) -> str:
    clean = [v for v in values if v]
    return Counter(clean).most_common(1)[0][0] if clean else ""


_HEIGHT_RE = re.compile(r"\b([56])\s*['’]\s*(\d{1,2})")
_LOAN_RE = re.compile(r"on loan from ([A-Z][\w&.'’ ]+?)(?:[.,;)\n]|$)")
_FOOT_RE = re.compile(r"\b(left|right)[- ]footed\b", re.I)
_POSITION_RE = re.compile(r"position (?:in match|inferred|):?\s*:?\s*([A-Z]{2,3})\b")


def _profile_facts(rows: list[dict[str, Any]]) -> dict[str, str]:
    heights, feet, loans, positions = [], [], [], []
    for row in rows:
        text = row.get("text") or ""
        phys = row.get("physical") or {}
        size = _text(phys.get("size"))
        match = _HEIGHT_RE.search(size) or _HEIGHT_RE.search(text)
        if match:
            heights.append(f"{match.group(1)}'{match.group(2)}")
        foot = _text(phys.get("foot")).casefold()
        if not foot:
            m = _FOOT_RE.search(text)
            foot = m.group(1).casefold() if m else ""
        if foot in ("left", "right"):
            feet.append(foot)
        m = _LOAN_RE.search(text)
        if m:
            loans.append(m.group(1).strip())
        pos = _text(row.get("position")).upper()
        if not pos:
            m = _POSITION_RE.search(text)
            pos = m.group(1) if m else ""
        if pos:
            positions.append(pos)
    return {
        "height": _mode(heights),
        "foot": _mode(feet),
        "loan_from": _mode(loans),
        "position": _mode(positions),
    }


_POSITION_WORDS = {
    "GK": "goalkeeper", "GOALKEEPER": "goalkeeper",
    "CB": "centre-back", "CENTRAL_DEFENDER": "centre-back",
    "LB": "left back", "LWB": "left wing-back", "LEFT_WINGBACK_DEFENDER": "left back",
    "RB": "right back", "RWB": "right wing-back", "RIGHT_WINGBACK_DEFENDER": "right back",
    "DM": "defensive midfielder", "CDM": "defensive midfielder", "DEFENSE_MIDFIELD": "defensive midfielder",
    "CM": "central midfielder", "CENTRAL_MIDFIELD": "central midfielder",
    "AM": "attacking midfielder", "CAM": "attacking midfielder", "ATTACKING_MIDFIELD": "attacking midfielder",
    "LW": "left winger", "LM": "left midfielder", "LEFT_WINGER": "left winger",
    "RW": "right winger", "RM": "right midfielder", "RIGHT_WINGER": "right winger",
    "CF": "centre-forward", "ST": "striker", "CENTER_FORWARD": "centre-forward",
}


def _position_words(code: str) -> str:
    key = _text(code).upper()
    return _POSITION_WORDS.get(key, key.replace("_", " ").lower())


def _month_label(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        return datetime.strptime(iso[:10], "%Y-%m-%d").strftime("%b %Y")
    except ValueError:
        return ""


def _theme_findings(rows: list[dict[str, Any]]) -> tuple[list[str], list[str]]:
    """Strengths / concerns: themes scouts keep coming back to, with a supporting quote."""
    total = len(rows)
    tally: dict[str, dict[str, Any]] = {}
    for idx, row in enumerate(rows):
        for sentence in _clean_report_text(row.get("text") or ""):
            tone = _tone(sentence)
            if tone == 0:
                continue
            for theme in _themes_for(sentence):
                slot = tally.setdefault(theme, {"pos": set(), "neg": set(), "pos_q": [], "neg_q": []})
                key = "pos" if tone > 0 else "neg"
                slot[key].add(idx)
                slot[f"{key}_q"].append(sentence)

    used: set[str] = set()

    def describe(theme: str, reports: set[int], quotes: list[str]) -> str:
        fresh = [q for q in quotes if q not in used] or quotes
        quote = min(fresh, key=lambda q: abs(len(q) - 70))
        used.add(quote)
        count = len(reports)
        backing = f"{count} of {total} reports" if total > 1 else "noted"
        return f"{theme} ({backing}) — “{_short_quote(quote)}”"

    strengths: list[tuple[int, str]] = []
    concerns: list[tuple[int, str]] = []
    for theme, slot in tally.items():
        pos, neg = len(slot["pos"]), len(slot["neg"])
        if pos and pos >= neg:
            strengths.append((pos, describe(theme, slot["pos"], slot["pos_q"])))
        if neg and (neg > pos or neg >= max(2, total // 2)):
            concerns.append((neg, describe(theme, slot["neg"], slot["neg_q"])))
    if total >= 3:
        strengths = [item for item in strengths if item[0] >= 2] or strengths
        concerns = [item for item in concerns if item[0] >= 2] or concerns
    strengths.sort(key=lambda item: item[0], reverse=True)
    concerns.sort(key=lambda item: item[0], reverse=True)
    return [text for _, text in strengths[:4]], [text for _, text in concerns[:3]]


def _fallback_summary(name: str, rows: list[dict[str, Any]], stats: dict[str, Any]) -> dict[str, Any]:
    count = stats["count"]
    scouts = stats["scouts"]
    facts = _profile_facts(rows)
    first = (name or "He").split()[0] if name and not name.isdigit() else "He"

    seen = f"Watched {count} time{'s' if count != 1 else ''}"
    if scouts:
        seen += f" by {len(scouts)} scout{'s' if len(scouts) != 1 else ''}"
    first_m, last_m = _month_label(stats.get("first_date")), _month_label(stats.get("last_date"))
    if first_m and last_m:
        seen += f" ({first_m})" if first_m == last_m else f" ({first_m} – {last_m})"
    if facts["position"]:
        seen += f", mostly as a {_position_words(facts['position'])}"
    sentences = [seen + "."]

    profile_bits = [
        facts["height"],
        f"{facts['foot']}-footed" if facts["foot"] else "",
    ]
    profile = " ".join(bit for bit in profile_bits if bit)
    if profile or facts["loan_from"]:
        line = f"Scouts describe a {profile} player" if profile else f"{first}"
        if facts["loan_from"]:
            line += f", on loan from {facts['loan_from']}" if profile else f" is on loan from {facts['loan_from']}"
        sentences.append(line + ".")

    verdict = []
    if stats["pvfc_level"]:
        votes = stats.get("pvfc_level_votes") or {}
        agree = votes.get(stats["pvfc_level"], 0)
        level = f"level {stats['pvfc_level']} ({stats['pvfc_level_title']})"
        verdict.append(f"{agree} of {count} reports grade him {level}" if count > 1 else f"graded {level}")
    if stats["avg_match_rating"] is not None:
        verdict.append(f"average match rating {stats['avg_match_rating']}/10")
    if stats["avg_current_ability"] is not None or stats["avg_potential_ability"] is not None:
        ability = " / ".join(
            f"{label} {value}/5"
            for label, value in (("CA", stats["avg_current_ability"]), ("PA", stats["avg_potential_ability"]))
            if value is not None
        )
        verdict.append(f"average {ability}")
    if verdict:
        text = ", ".join(verdict)
        sentences.append(text[0].upper() + text[1:] + ".")

    strengths, concerns = _theme_findings(rows)

    actions = Counter(row["next_action"] for row in rows if row.get("next_action"))
    recommendation = ""
    if actions:
        top, votes = actions.most_common(1)[0]
        label = NEXT_ACTION_TITLES.get(top, top)
        recommendation = (
            f"{label} — {votes} of {count} reports."
            if count > 1
            else f"{label}."
        )
        latest = stats.get("next_action")
        if latest and latest != top:
            recommendation += f" Latest report says {NEXT_ACTION_TITLES.get(latest, latest).lower()}."

    return {
        "headline": " ".join(sentences),
        "strengths": strengths,
        "concerns": concerns,
        "points": [],
        "recommendation": recommendation,
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
        body = "\n".join(_clean_report_text(row.get("text") or ""))[:MAX_REPORT_CHARS]
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
