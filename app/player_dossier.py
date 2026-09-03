"""Player dossier — one page per Impect player (photo, profiles, reports, recent games)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
import json
import re
import threading
import uuid
from typing import Any
from urllib.parse import quote

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from app.label_utils import humanize_profile_name, strip_pv_prefix
from app.paths import DATA_ROOT, STANDALONE_DIR
from app.opponent_photos import _normalize_name_key

try:
    from app.set_piece_pre_match import _fetch_transfermarkt_heights, _height_label_from_cm
except Exception:  # noqa: BLE001
    def _fetch_transfermarkt_heights(club_name: str, season: str | None) -> dict[str, int]:
        return {}

    def _height_label_from_cm(cm: int | None) -> str:
        if not cm:
            return "—"
        feet = int(cm // 30.48)
        inches = int(round((cm / 2.54) % 12))
        if inches == 12:
            feet += 1
            inches = 0
        return f"{feet}'{inches}\""

RECENT_GAMES_LIMIT = 8
UPCOMING_GAMES_LIMIT = 5
RECENT_GAMES_SCAN_BATCH = 6
_MATCH_KPI_CACHE: dict[int, tuple[float, Any]] = {}
_MATCH_KPI_CACHE_TTL = 600.0

PLAYER_NOTES_PATH = DATA_ROOT / "player-notes.json"
_player_notes_lock = threading.Lock()
ABILITY_STAR_MAX = 5


class PlayerNoteCreate(BaseModel):
    kind: str = "note"  # "note" | "report"
    summary: str = Field(..., min_length=1)
    title: str = ""
    staff: str = ""
    position: str = ""
    current_ability: float | None = None
    potential_ability: float | None = None
    date: str = ""


class PlayerNoteUpdate(BaseModel):
    kind: str | None = None
    summary: str | None = None
    title: str | None = None
    staff: str | None = None
    position: str | None = None
    current_ability: float | None = None
    potential_ability: float | None = None
    date: str | None = None


DOSSIER_KPI_KEYS: tuple[tuple[str, str], ...] = (
    ("PXT_ATTACK", "PXT attack"),
    ("PXT_DEFEND", "PXT defend"),
    ("BYPASSED_OPPONENTS", "Bypassed opp."),
    ("BALL_WIN_NUMBER", "Ball wins"),
    ("SHOT_XG", "Shot xG"),
    ("GOALS", "Goals"),
    ("ASSISTS", "Assists"),
)


def _impect():
    from app import main as impect

    return impect


def _resolve_catalog_player(player_id: int) -> dict[str, Any] | None:
    impect = _impect()
    iterations = impect._fetch_iterations()
    iteration_ids = impect._latest_iteration_ids(iterations)
    if not iteration_ids:
        return None

    players_by_iteration = impect._fetch_players_parallel(iteration_ids)
    merged = impect._merge_player_options(iteration_ids, players_by_iteration)
    match = next((row for row in merged if int(row.get("impect_player_id") or 0) == player_id), None)
    if match is None:
        # Fall back to full history catalog (slower) so older-only players still resolve.
        all_ids = [int(row["id"]) for row in iterations if row.get("competition_name") in impect.ALLOWED_COMPETITIONS]
        players_by_iteration = impect._fetch_players_parallel(all_ids)
        merged = impect._merge_player_options(all_ids, players_by_iteration)
        match = next((row for row in merged if int(row.get("impect_player_id") or 0) == player_id), None)
        if match is None:
            return None

    label_map = impect._iteration_label_map(
        [int(i) for i in match.get("ids_by_iteration", {})] or iteration_ids
    )
    iteration_meta = impect._iteration_meta_map()
    # Avoid expand_history — it hammers Impect and can 429 on dossier loads.
    enriched = impect._enrich_player_catalog(
        [match], label_map, iteration_meta, expand_history=False
    )
    return enriched[0] if enriched else match


def _pick_season(
    player: dict[str, Any],
    iteration_id: int | None,
) -> dict[str, Any] | None:
    seasons = list(player.get("seasons") or [])
    if not seasons:
        return None
    if iteration_id is not None:
        for row in seasons:
            if int(row.get("iteration_id") or 0) == iteration_id:
                return row
    # Prefer seasons with a named club (drops ghost catalog rows like League Two
    # when the player only actually played League One for that club).
    with_club = [row for row in seasons if str(row.get("club") or "").strip()]
    chartable = [row for row in (with_club or seasons) if row.get("chartable")]
    pool = chartable or with_club or seasons
    pool.sort(
        key=lambda row: (
            _impect()._season_sort_key(str(row.get("season") or "")),
            1 if str(row.get("club") or "").strip() else 0,
            int(row.get("iteration_id") or 0),
        ),
        reverse=True,
    )
    return pool[0]


def _raw_player_record(iteration_id: int, player_id: int) -> dict[str, Any] | None:
    impect = _impect()
    for row in impect._fetch_players_for_iteration(iteration_id):
        if int(row.get("id") or 0) == player_id:
            return row
    return None


def _height_for_player(name: str, club: str | None, season: str | None) -> str | None:
    if not club:
        return None
    try:
        heights = _fetch_transfermarkt_heights(club, season)
    except Exception:
        return None
    key = _normalize_name_key(name)
    cm = heights.get(key)
    if cm is None:
        # Soft match on surname token
        surname = key.split()[-1] if key else ""
        for candidate, value in heights.items():
            if surname and surname in candidate:
                cm = value
                break
    return _height_label_from_cm(cm) if cm else None


def _foot_label(raw_player: dict[str, Any] | None) -> str:
    if not raw_player:
        return "—"
    from app.scouting import _format_foot

    return _format_foot(raw_player.get("leg") or raw_player.get("preferredFoot") or raw_player.get("foot"))


def _photo_url(name: str, club: str | None, season: str | None) -> str:
    params = [f"name={quote(name)}"]
    if club:
        params.append(f"club={quote(club)}")
    if season:
        params.append(f"season={quote(season)}")
    return "/api/pre-match/player-photo?" + "&".join(params)


def _positions_block(
    iteration_id: int,
    player_id: int,
    *,
    squad_id: int | None = None,
) -> tuple[str | None, list[dict[str, Any]]]:
    from app.scouting import _ensure_position_shares, _scouting_position_label

    primary, shares = _ensure_position_shares(iteration_id)
    primary_pos = (primary or {}).get(player_id)
    share_map = (shares or {}).get(player_id) or {}
    codes = [
        code
        for code, share in sorted(share_map.items(), key=lambda item: item[1], reverse=True)
        if float(share or 0) > 0
    ]
    minutes_by_code: dict[str, float] = {}
    if squad_id is not None and codes:
        impect = _impect()

        def load_minutes(position: str) -> tuple[str, float]:
            try:
                score_rows, _ = impect._fetch_profile_scores(
                    iteration_id, squad_id, [position], 0
                )
            except Exception:
                return position, 0.0
            row = next(
                (r for r in score_rows if int(r.get("playerId") or 0) == player_id),
                None,
            )
            if row is None:
                return position, 0.0
            return position, float(impect._play_duration_minutes(row) or 0.0)

        with ThreadPoolExecutor(max_workers=min(4, len(codes))) as pool:
            for position, minutes in pool.map(load_minutes, codes):
                minutes_by_code[position] = minutes

    rows: list[dict[str, Any]] = []
    for code in codes:
        minutes = minutes_by_code.get(code)
        rows.append(
            {
                "code": code,
                "label": _scouting_position_label(code),
                "abbrev": _impect().POSITION_ABBREV.get(code, code[:3]),
                "match_share": round(float(share_map.get(code) or 0), 1),
                "minutes": round(float(minutes), 0) if minutes is not None else None,
            }
        )
    # Prefer sorting by minutes when available.
    rows.sort(
        key=lambda item: (
            float(item.get("minutes") or 0),
            float(item.get("match_share") or 0),
        ),
        reverse=True,
    )
    return primary_pos, rows


def _profile_rows(
    iteration_id: int,
    squad_id: int,
    player_id: int,
    primary_position: str | None,
) -> tuple[list[dict[str, Any]], float | None, str | None]:
    """Return (profiles, minutes, position_code_used)."""
    impect = _impect()
    candidates: list[str] = []
    if primary_position:
        candidates.append(str(primary_position))
    for fallback in (
        "LEFT_WINGER",
        "RIGHT_WINGER",
        "LEFT_MIDFIELD",
        "RIGHT_MIDFIELD",
        "ATTACKING_MIDFIELD",
        "CENTER_FORWARD",
        "CENTRAL_MIDFIELD",
        "LEFT_WINGBACK_DEFENDER",
        "RIGHT_WINGBACK_DEFENDER",
        "DEFENSE_MIDFIELD",
        "CENTRAL_DEFENDER",
    ):
        if fallback not in candidates:
            candidates.append(fallback)

    best_profiles: list[dict[str, Any]] = []
    best_minutes: float | None = None
    best_position: str | None = None

    for position in candidates:
        try:
            score_rows, _ = impect._fetch_profile_scores(iteration_id, squad_id, [position], 0)
        except Exception:
            continue

        row = next((r for r in score_rows if int(r.get("playerId") or 0) == player_id), None)
        if row is None:
            continue

        minutes = impect._play_duration_minutes(row)
        profiles: list[dict[str, Any]] = []
        for score in row.get("profileScores") or []:
            if not isinstance(score, dict):
                continue
            name = str(score.get("profileName") or "").strip()
            if not name or not impect._is_pv_profile(name):
                continue
            value = score.get("value")
            if value is None:
                continue
            try:
                numeric = float(value)
            except (TypeError, ValueError):
                continue
            label = strip_pv_prefix(name)
            label = re.sub(r"\s*[\-\(].*$", "", label).replace("_", " ").strip()
            label = label or humanize_profile_name(name)
            profiles.append(
                {
                    "name": name,
                    "label": label,
                    "score": round(numeric, 3),
                    "pct": round(numeric * 100),
                }
            )
        profiles.sort(key=lambda item: item["pct"], reverse=True)
        if profiles:
            return profiles, minutes, position
        if best_minutes is None and minutes is not None:
            best_minutes = minutes
            best_profiles = profiles
            best_position = position

    return best_profiles, best_minutes, best_position


def _load_player_notes_store() -> dict[str, Any]:
    if not PLAYER_NOTES_PATH.exists():
        return {"version": 1, "updated_at": None, "notes": {}}
    try:
        payload = json.loads(PLAYER_NOTES_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"version": 1, "updated_at": None, "notes": {}}
    if not isinstance(payload.get("notes"), dict):
        payload["notes"] = {}
    return payload


def _save_player_notes_store(payload: dict[str, Any]) -> None:
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    payload["updated_at"] = datetime.now(UTC).isoformat()
    temp_path = PLAYER_NOTES_PATH.with_suffix(".json.tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temp_path.replace(PLAYER_NOTES_PATH)


def _notes_for_player(player_id: int) -> list[dict[str, Any]]:
    with _player_notes_lock:
        store = _load_player_notes_store()
        raw = store.get("notes", {}).get(str(player_id)) or []
    if not isinstance(raw, list):
        return []
    rows: list[dict[str, Any]] = []
    for note in raw:
        if not isinstance(note, dict):
            continue
        rows.append(_note_to_report_row(note))
    rows.sort(key=lambda item: str(item.get("marked_at") or item.get("date") or ""), reverse=True)
    return rows


def _normalize_entry_kind(value: Any) -> str:
    kind = str(value or "").strip().casefold()
    return "report" if kind == "report" else "note"


def _note_to_report_row(note: dict[str, Any]) -> dict[str, Any]:
    kind = _normalize_entry_kind(note.get("kind"))
    default_title = "Scout report" if kind == "report" else "Note"
    title = str(note.get("title") or "").strip() or default_title
    return {
        "id": note.get("id"),
        "kind": kind,
        "fixture_id": None,
        "fixture": title,
        "league": "",
        "player_name": note.get("player_name") or "",
        "team": note.get("team") or "",
        "staff": note.get("staff") or "",
        "position": note.get("position") or "",
        "date": str(note.get("date") or "")[:10],
        "marked_at": note.get("updated_at") or note.get("created_at"),
        "current_ability": _coerce_star_rating(note.get("current_ability")) if kind == "report" else None,
        "potential_ability": _coerce_star_rating(note.get("potential_ability")) if kind == "report" else None,
        "summary": str(note.get("summary") or "").strip() or None,
        "example": False,
        "source": "dossier",
        "editable": True,
        "href": None,
    }


def create_player_note(player_id: int, body: PlayerNoteCreate, *, player_name: str = "") -> dict[str, Any]:
    summary = str(body.summary or "").strip()
    if not summary:
        raise HTTPException(status_code=400, detail="Notes text is required.")
    kind = _normalize_entry_kind(body.kind)
    now = datetime.now(UTC).isoformat()
    default_title = "Scout report" if kind == "report" else "Note"
    note = {
        "id": str(uuid.uuid4()),
        "kind": kind,
        "player_id": int(player_id),
        "player_name": player_name,
        "title": str(body.title or "").strip() or default_title,
        "summary": summary,
        "staff": str(body.staff or "").strip(),
        "position": str(body.position or "").strip() if kind == "report" else str(body.position or "").strip(),
        "date": str(body.date or "").strip()[:10] or now[:10],
        "current_ability": _coerce_star_rating(body.current_ability) if kind == "report" else None,
        "potential_ability": _coerce_star_rating(body.potential_ability) if kind == "report" else None,
        "created_at": now,
        "updated_at": now,
    }
    with _player_notes_lock:
        store = _load_player_notes_store()
        bucket = store.setdefault("notes", {}).setdefault(str(player_id), [])
        if not isinstance(bucket, list):
            bucket = []
            store["notes"][str(player_id)] = bucket
        bucket.insert(0, note)
        _save_player_notes_store(store)
    return _note_to_report_row(note)


def update_player_note(player_id: int, note_id: str, body: PlayerNoteUpdate) -> dict[str, Any]:
    with _player_notes_lock:
        store = _load_player_notes_store()
        bucket = store.get("notes", {}).get(str(player_id)) or []
        if not isinstance(bucket, list):
            raise HTTPException(status_code=404, detail="Note not found.")
        match = next((row for row in bucket if str(row.get("id")) == str(note_id)), None)
        if match is None:
            raise HTTPException(status_code=404, detail="Note not found.")
        payload = body.model_dump(exclude_unset=True)
        if "summary" in payload:
            summary = str(payload.get("summary") or "").strip()
            if not summary:
                raise HTTPException(status_code=400, detail="Notes text is required.")
            match["summary"] = summary
        if "title" in payload:
            kind = _normalize_entry_kind(match.get("kind"))
            default_title = "Scout report" if kind == "report" else "Note"
            match["title"] = str(payload.get("title") or "").strip() or default_title
        if "kind" in payload and payload.get("kind") is not None:
            match["kind"] = _normalize_entry_kind(payload.get("kind"))
        if "staff" in payload:
            match["staff"] = str(payload.get("staff") or "").strip()
        if "position" in payload:
            match["position"] = str(payload.get("position") or "").strip()
        if "date" in payload:
            match["date"] = str(payload.get("date") or "").strip()[:10]
        if "current_ability" in payload:
            match["current_ability"] = _coerce_star_rating(payload.get("current_ability"))
        if "potential_ability" in payload:
            match["potential_ability"] = _coerce_star_rating(payload.get("potential_ability"))
        match["updated_at"] = datetime.now(UTC).isoformat()
        _save_player_notes_store(store)
        return _note_to_report_row(match)


def delete_player_note(player_id: int, note_id: str) -> dict[str, Any]:
    with _player_notes_lock:
        store = _load_player_notes_store()
        notes_map = store.setdefault("notes", {})
        bucket = notes_map.get(str(player_id)) or []
        if not isinstance(bucket, list):
            raise HTTPException(status_code=404, detail="Note not found.")
        kept = [row for row in bucket if str(row.get("id")) != str(note_id)]
        if len(kept) == len(bucket):
            raise HTTPException(status_code=404, detail="Note not found.")
        if kept:
            notes_map[str(player_id)] = kept
        else:
            notes_map.pop(str(player_id), None)
        _save_player_notes_store(store)
    return {"ok": True, "player_id": player_id, "note_id": note_id}


def _reports_for_player(player_id: int, name: str) -> list[dict[str, Any]]:
    from app.fixture_planner import get_scouting_reports

    dossier_notes = _notes_for_player(player_id)

    store = get_scouting_reports().get("reports") or {}
    name_key = name.casefold().strip()
    rows: list[dict[str, Any]] = []
    for fixture_id, fixture_reports in store.items():
        if not isinstance(fixture_reports, dict):
            continue
        for player_key, report in fixture_reports.items():
            if not isinstance(report, dict):
                continue
            report_id = report.get("player_id")
            report_name = str(report.get("player_name") or "").casefold().strip()
            id_match = report_id is not None and int(report_id) == player_id
            key_match = str(player_key).isdigit() and int(player_key) == player_id
            name_match = bool(name_key) and report_name == name_key
            if not (id_match or key_match or name_match):
                continue
            parts = str(fixture_id).split("|")
            fixture_label = (
                f"{parts[1].title()} vs {parts[2].title()}"
                if len(parts) >= 3
                else str(fixture_id)
            )
            rows.append(
                {
                    "id": None,
                    "fixture_id": fixture_id,
                    "fixture": fixture_label,
                    "league": parts[0] if parts else "",
                    "player_name": report.get("player_name") or name,
                    "team": report.get("team") or "",
                    "staff": report.get("staff") or "",
                    "position": report.get("position") or "",
                    "date": str(report.get("fixture_date") or report.get("date") or "")[:10],
                    "marked_at": report.get("marked_at"),
                    "current_ability": _coerce_star_rating(
                        report.get("current_ability")
                        if report.get("current_ability") is not None
                        else report.get("ca")
                    ),
                    "potential_ability": _coerce_star_rating(
                        report.get("potential_ability")
                        if report.get("potential_ability") is not None
                        else report.get("pa")
                    ),
                    "summary": str(report.get("summary") or report.get("notes") or "").strip() or None,
                    "example": False,
                    "kind": "report",
                    "source": "fixture",
                    "editable": False,
                    "href": "/played-fixtures",
                }
            )
    rows.sort(key=lambda item: str(item.get("marked_at") or item.get("date") or ""), reverse=True)
    combined = dossier_notes + rows
    if combined:
        return combined
    # Placeholder reports until full scout write-ups are stored in the hub.
    return _example_reports_for_player(player_id, name)


# Example scout write-ups (CA/PA stars) for players until reports land in the store.
_EXAMPLE_SCOUT_REPORTS: dict[int, list[dict[str, Any]]] = {
    105272: [  # Mo Faal
        {
            "fixture": "Port Vale vs Blackpool",
            "league": "League One",
            "team": "FC Port Vale",
            "staff": "Recruitment (example)",
            "position": "CF",
            "date": "2026-01-01",
            "current_ability": 3,
            "potential_ability": 4,
            "summary": (
                "Physical target forward who wins first contacts and holds the ball up well. "
                "Links play into wide runners; finishing still needs to sharpen inside the box."
            ),
        },
        {
            "fixture": "Bradford City vs Port Vale",
            "league": "League One",
            "team": "FC Port Vale",
            "staff": "Recruitment (example)",
            "position": "CF",
            "date": "2025-12-29",
            "current_ability": 3,
            "potential_ability": 4.5,
            "summary": (
                "Came on and occupied both centre-backs. Aerial threat on set plays; "
                "mobility limited over longer transitions but upside as a League One 9."
            ),
        },
    ],
}


def _coerce_star_rating(value: Any, *, maximum: int = ABILITY_STAR_MAX) -> float | None:
    if value is None or value == "":
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if numeric < 0:
        return 0.0
    if numeric > maximum:
        return float(maximum)
    # Snap to half-stars for a clean scout scale.
    return round(numeric * 2) / 2


def _example_reports_for_player(player_id: int, name: str) -> list[dict[str, Any]]:
    rows = _EXAMPLE_SCOUT_REPORTS.get(int(player_id)) or []
    out: list[dict[str, Any]] = []
    for row in rows:
        out.append(
            {
                "fixture_id": None,
                "fixture": row.get("fixture") or "Example fixture",
                "league": row.get("league") or "",
                "player_name": name,
                "team": row.get("team") or "",
                "staff": row.get("staff") or "Scout (example)",
                "position": row.get("position") or "",
                "date": str(row.get("date") or "")[:10],
                "marked_at": None,
                "current_ability": _coerce_star_rating(row.get("current_ability")),
                "potential_ability": _coerce_star_rating(row.get("potential_ability")),
                "summary": row.get("summary"),
                "example": True,
                "kind": "report",
                "source": "example",
                "editable": False,
                "href": "/played-fixtures",
            }
        )
    return out


def _split_player_activity(player_id: int, name: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows = _reports_for_player(player_id, name)
    notes = [row for row in rows if _normalize_entry_kind(row.get("kind")) == "note"]
    scout_reports = [row for row in rows if _normalize_entry_kind(row.get("kind")) != "note"]
    return notes, scout_reports


def _activity_payload(player_id: int, name: str, *, note: dict[str, Any] | None = None) -> dict[str, Any]:
    notes, scout_reports = _split_player_activity(player_id, name)
    payload = {
        "notes": notes,
        "reports": scout_reports,
        "ability": _ability_from_reports(scout_reports),
    }
    if note is not None:
        payload["note"] = note
    return payload


def _ability_from_reports(reports: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Aggregate CA/PA from full scout reports only (not work notes)."""
    current: float | None = None
    potential: float | None = None
    source = "report"
    for row in reports:
        kind = _normalize_entry_kind(row.get("kind"))
        if kind != "report" and not row.get("example"):
            # Legacy rows without kind still count if they carry ratings.
            if row.get("current_ability") is None and row.get("potential_ability") is None:
                continue
        if current is None:
            current = _coerce_star_rating(row.get("current_ability"))
        if potential is None:
            potential = _coerce_star_rating(row.get("potential_ability"))
        if row.get("example"):
            source = "example"
        if current is not None and potential is not None:
            break
    if current is None and potential is None:
        return None
    return {
        "current": current,
        "potential": potential,
        "max": ABILITY_STAR_MAX,
        "source": source,
        "label": "Scout rating" if source == "report" else "Scout rating (example)",
    }


def _kpi_lookup() -> dict[str, int]:
    from app.pre_match import _kpi_names

    names = _kpi_names()
    return {str(name).upper(): int(kpi_id) for kpi_id, name in names.items()}


def _extract_match_kpis(row: dict[str, Any], kpi_ids: dict[str, int]) -> dict[str, float | None]:
    values_by_id: dict[int, float] = {}
    for item in row.get("kpis") or []:
        if not isinstance(item, dict):
            continue
        kpi_id = item.get("kpiId")
        if kpi_id is None:
            continue
        try:
            values_by_id[int(kpi_id)] = float(item.get("value"))
        except (TypeError, ValueError):
            continue

    out: dict[str, float | None] = {}
    for key, _label in DOSSIER_KPI_KEYS:
        kpi_id = kpi_ids.get(key)
        if kpi_id is None:
            out[key.lower()] = None
            continue
        value = values_by_id.get(kpi_id)
        if value is None:
            out[key.lower()] = None
        elif key in {"SHOT_XG", "PXT_ATTACK", "PXT_DEFEND"}:
            out[key.lower()] = round(value, 2)
        else:
            out[key.lower()] = round(value, 1)
    return out


def _cached_match_player_kpis(match_id: int) -> Any | None:
    import time

    from app.pre_match import _unwrap_match_player_payload

    cached = _MATCH_KPI_CACHE.get(match_id)
    now = time.time()
    if cached and now - cached[0] < _MATCH_KPI_CACHE_TTL:
        return cached[1]
    impect = _impect()
    try:
        payload = impect._impect_get(
            f"/v5/{impect._api_prefix()}/matches/{match_id}/player-kpis"
        )["data"]
    except Exception:
        return None
    data = _unwrap_match_player_payload(payload)
    _MATCH_KPI_CACHE[match_id] = (now, data)
    return data


def _recent_games(
    iteration_id: int,
    squad_id: int,
    player_id: int,
    *,
    limit: int = RECENT_GAMES_LIMIT,
) -> list[dict[str, Any]]:
    import time

    from app.pre_match import _match_play_minutes, _recent_completed_matches

    impect = _impect()
    # Scan the full completed season — a player may have minutes earlier but not in the
    # last N squad fixtures (e.g. loan return, injury, rotation).
    matches = _recent_completed_matches(iteration_id, squad_id, limit=None)
    squad_names = impect._fetch_squad_names(iteration_id)
    kpi_ids = _kpi_lookup()

    def load_one(match: dict[str, Any]) -> dict[str, Any] | None:
        match_id = int(match["id"])
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        is_home = home_id == squad_id
        opponent_id = away_id if is_home else home_id
        goals = match.get("goals") or {}
        home_goals = ((goals.get("home") or {}).get("fullTime"))
        away_goals = ((goals.get("away") or {}).get("fullTime"))
        data = _cached_match_player_kpis(match_id)
        if data is None:
            return None
        player_row = None
        for side in ("squadHome", "squadAway"):
            squad = data.get(side) or {}
            if int(squad.get("id") or -1) != squad_id:
                continue
            for row in squad.get("players") or []:
                if int(row.get("id") or 0) == player_id:
                    minutes = _match_play_minutes(row)
                    if player_row is None or minutes > _match_play_minutes(player_row):
                        player_row = row
        if player_row is None:
            return None
        minutes = _match_play_minutes(player_row)
        if minutes <= 0:
            return None
        position = str(player_row.get("position") or "")
        return {
            "match_id": match_id,
            "date": str(match.get("scheduledDate") or "")[:10],
            "opponent": squad_names.get(opponent_id) or f"Squad {opponent_id}",
            "is_home": is_home,
            "venue": "H" if is_home else "A",
            "score": (
                f"{home_goals}-{away_goals}"
                if home_goals is not None and away_goals is not None
                else "—"
            ),
            "minutes": minutes,
            "position": position,
            "position_label": impect.POSITION_LABELS.get(position, position.replace("_", " ").title()),
            "position_abbrev": impect.POSITION_ABBREV.get(position, position[:3] if position else "—"),
            "impect": _extract_match_kpis(player_row, kpi_ids),
        }

    games: list[dict[str, Any]] = []
    # Gentle concurrency — heavy parallel scans trip Impect 429s and return empty lists.
    for start in range(0, len(matches), RECENT_GAMES_SCAN_BATCH):
        if len(games) >= limit:
            break
        chunk = matches[start : start + RECENT_GAMES_SCAN_BATCH]
        with ThreadPoolExecutor(max_workers=min(2, max(len(chunk), 1))) as pool:
            futures = [pool.submit(load_one, match) for match in chunk]
            for future in as_completed(futures):
                row = future.result()
                if row is not None:
                    games.append(row)
        if start + RECENT_GAMES_SCAN_BATCH < len(matches) and len(games) < limit:
            time.sleep(0.15)

    games.sort(key=lambda item: str(item.get("date") or ""), reverse=True)
    return games[:limit]


def _upcoming_from_iteration(
    iteration_id: int,
    squad_id: int,
    *,
    competition_name: str | None = None,
    season_label: str | None = None,
) -> list[dict[str, Any]]:
    from app.pre_match import (
        _format_kickoff,
        _match_is_complete,
        _match_sort_key,
        _parse_match_datetime,
        _unwrap_items,
    )

    impect = _impect()
    try:
        matches = _unwrap_items(
            impect._impect_get(
                f"/v5/{impect._api_prefix()}/iterations/{iteration_id}/matches"
            )["data"]
        )
    except Exception:
        return []
    now = datetime.now(UTC)
    squad_names = impect._fetch_squad_names(iteration_id)
    rows: list[dict[str, Any]] = []
    for match in matches:
        if (
            int(match.get("homeSquadId") or -1) != squad_id
            and int(match.get("awaySquadId") or -1) != squad_id
        ):
            continue
        if _match_is_complete(match):
            continue
        match_dt = _parse_match_datetime(match.get("scheduledDate"))
        if match_dt is not None and match_dt < now:
            continue
        home_id = int(match.get("homeSquadId") or 0)
        away_id = int(match.get("awaySquadId") or 0)
        is_home = home_id == squad_id
        opponent_id = away_id if is_home else home_id
        date_label, time_label = _format_kickoff(match.get("scheduledDate"))
        rows.append(
            {
                "match_id": int(match["id"]),
                "date": str(match.get("scheduledDate") or "")[:10],
                "date_label": date_label,
                "time_label": time_label,
                "opponent": squad_names.get(opponent_id) or f"Squad {opponent_id}",
                "is_home": is_home,
                "venue": "H" if is_home else "A",
                "competition": competition_name,
                "season": season_label,
                "source": "impect",
                "_sort": _match_sort_key(match),
            }
        )
    rows.sort(key=lambda row: row.get("_sort") or (datetime.min.replace(tzinfo=UTC), 0, 0))
    for row in rows:
        row.pop("_sort", None)
    return rows


def _club_name_tokens(name: str | None) -> set[str]:
    text = re.sub(r"[^a-z0-9]+", " ", str(name or "").casefold()).strip()
    stop = {"fc", "afc", "the", "club", "town", "city", "united", "utd"}
    return {token for token in text.split() if token and token not in stop}


def _club_names_match(left: str | None, right: str | None) -> bool:
    a = _club_name_tokens(left)
    b = _club_name_tokens(right)
    if not a or not b:
        return False
    return a == b or a.issubset(b) or b.issubset(a)


def _upcoming_from_fotmob(
    club_name: str | None,
    *,
    limit: int,
    preferred_competition: str | None = None,
) -> list[dict[str, Any]]:
    """FotMob league fixtures filtered to this club (primary upcoming source)."""
    if not club_name:
        return []
    from app.fixture_planner import FIXTURE_LEAGUES, _fetch_fotmob_fixtures
    from app.pre_match import _format_kickoff, _parse_match_datetime

    now = datetime.now(UTC)
    # Prefer the forthcoming English season first.
    season_order = ("26/27", "25/26", "27/28")
    preferred = str(preferred_competition or "").strip()
    league_rows = [
        league
        for league in FIXTURE_LEAGUES
        if str(league.get("competition") or league.get("ui") or "")
        in {"League One", "League Two", "National League"}
    ]
    if preferred:
        league_rows.sort(
            key=lambda row: 0
            if preferred.casefold()
            in str(row.get("competition") or row.get("ui") or "").casefold()
            else 1
        )

    rows: list[dict[str, Any]] = []
    for season in season_order:
        for league in league_rows:
            competition = str(league.get("competition") or league.get("ui") or "")
            try:
                fixtures = _fetch_fotmob_fixtures(
                    int(league["fotmob_id"]),
                    league_ui=str(league["ui"]),
                    season=season,
                    calendar_year=bool(league.get("calendar_year")),
                )
            except Exception:
                continue
            for fixture in fixtures:
                if str(fixture.get("status") or "") == "completed":
                    continue
                home = (fixture.get("home") or {}).get("name")
                away = (fixture.get("away") or {}).get("name")
                is_home = _club_names_match(club_name, home)
                is_away = _club_names_match(club_name, away)
                if not is_home and not is_away:
                    continue
                kickoff = fixture.get("kickoff_utc") or fixture.get("scheduled_date")
                match_dt = _parse_match_datetime(kickoff)
                if match_dt is not None and match_dt < now:
                    continue
                date_label, time_label = _format_kickoff(kickoff)
                opponent = away if is_home else home
                rows.append(
                    {
                        "match_id": None,
                        "date": str(fixture.get("date") or (str(kickoff or "")[:10])),
                        "date_label": date_label,
                        "time_label": time_label,
                        "opponent": opponent or "TBC",
                        "is_home": is_home,
                        "venue": "H" if is_home else "A",
                        "competition": competition,
                        "season": season,
                        "source": "fotmob",
                        "_kickoff": str(kickoff or ""),
                    }
                )
        if rows:
            break
    rows.sort(key=lambda row: str(row.get("_kickoff") or row.get("date") or ""))
    for row in rows:
        row.pop("_kickoff", None)
    return rows[:limit]


def _upcoming_games(
    iteration_id: int,
    squad_id: int,
    *,
    club_name: str | None = None,
    preferred_competition: str | None = None,
    limit: int = UPCOMING_GAMES_LIMIT,
) -> list[dict[str, Any]]:
    """Club upcoming fixtures — FotMob is canonical; Impect only if FotMob is empty."""
    try:
        fotmob = _upcoming_from_fotmob(
            club_name,
            limit=limit,
            preferred_competition=preferred_competition,
        )
        if fotmob:
            return fotmob
    except Exception:
        pass

    # Soft fallback only — Impect often lags on next-season schedules.
    preferred = _upcoming_from_iteration(
        iteration_id,
        squad_id,
        competition_name=preferred_competition,
    )
    if preferred:
        for row in preferred:
            row.setdefault("source", "impect")
        return preferred[:limit]

    impect = _impect()
    probe_competitions = {"League One", "League Two"}
    iterations = [
        row
        for row in impect._fetch_iterations()
        if str(row.get("competition_name") or "").strip() in probe_competitions
    ]
    iterations.sort(
        key=lambda row: (
            impect._season_sort_key(str(row.get("season") or "")),
            int(row.get("id") or 0),
        ),
        reverse=True,
    )
    checked = 0
    for iteration in iterations:
        other_id = int(iteration.get("id") or 0)
        if not other_id or other_id == iteration_id:
            continue
        checked += 1
        if checked > 4:
            break
        try:
            rows = _upcoming_from_iteration(
                other_id,
                squad_id,
                competition_name=str(iteration.get("competition_name") or "") or None,
                season_label=str(iteration.get("season") or "") or None,
            )
        except Exception:
            break
        if rows:
            for row in rows:
                row.setdefault("source", "impect")
            return rows[:limit]
    return []


def _recent_games_with_fallback(
    player: dict[str, Any],
    *,
    iteration_id: int,
    squad_id: int,
    player_id: int,
    limit: int = RECENT_GAMES_LIMIT,
) -> list[dict[str, Any]]:
    """Appearances for the selected season, else other catalog seasons for this player."""
    games = _recent_games(iteration_id, squad_id, player_id, limit=limit)
    if games:
        return games

    impect = _impect()
    squad_map = player.get("squad_ids_by_iteration") or {}
    candidates: list[tuple[tuple[Any, ...], int, int]] = []
    for season in player.get("seasons") or []:
        other_id = int(season.get("iteration_id") or 0)
        if not other_id or other_id == iteration_id:
            continue
        other_squad = squad_map.get(str(other_id))
        if other_squad is None:
            continue
        candidates.append(
            (
                (
                    impect._season_sort_key(str(season.get("season") or "")),
                    other_id,
                ),
                other_id,
                int(other_squad),
            )
        )
    candidates.sort(key=lambda item: item[0], reverse=True)
    for _, other_id, other_squad in candidates:
        games = _recent_games(other_id, other_squad, player_id, limit=limit)
        if games:
            return games
    return []


def _sum_kpi(game: dict[str, Any], key: str) -> float:
    value = (game.get("impect") or {}).get(key)
    try:
        return float(value) if value is not None else 0.0
    except (TypeError, ValueError):
        return 0.0


def _avg_kpi(games: list[dict[str, Any]], key: str) -> float | None:
    values = [
        _sum_kpi(game, key)
        for game in games
        if (game.get("impect") or {}).get(key) is not None
    ]
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _estimate_matches(minutes: float | None, recent_count: int) -> int | None:
    if minutes is None and not recent_count:
        return None
    estimate = int(round(float(minutes) / 90.0)) if minutes else 0
    return max(int(recent_count or 0), estimate) or None


def _hero_stats(
    *,
    minutes: float | None,
    matches_est: int | None,
    profiles: list[dict[str, Any]],
    recent_games: list[dict[str, Any]],
    tm: dict[str, Any] | None,
    fbref: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    top_profile = profiles[0] if profiles else None
    sample = recent_games or []
    apps = len(sample)
    rows: list[dict[str, Any]] = [
        {
            "key": "minutes",
            "label": "Minutes",
            "value": round(float(minutes), 0) if minutes is not None else None,
            "format": "int",
            "source": "Impect",
        },
        {
            "key": "matches",
            "label": "Matches",
            "value": matches_est,
            "format": "int",
            "source": "Impect",
        },
    ]
    if top_profile:
        rows.append(
            {
                "key": "top_profile",
                "label": top_profile["label"],
                "value": top_profile["pct"],
                "format": "int",
                "source": "Impect PV",
            }
        )
    rows.append(
        {
            "key": "pxt_attack",
            "label": "PXT att / game",
            "value": _avg_kpi(sample, "pxt_attack"),
            "format": "2",
            "source": "Impect",
        }
    )
    if tm and tm.get("market_value"):
        rows.append(
            {
                "key": "market_value",
                "label": "Market value",
                "value": tm["market_value"],
                "format": "text",
                "source": "TM",
            }
        )
    if fbref:
        for key, label, fmt in (
            ("goals", "Goals", "int"),
            ("assists", "Assists", "int"),
            ("xg", "xG", "2"),
            ("xg_assist", "xA", "2"),
        ):
            if fbref.get(key) is None:
                continue
            rows.append(
                {
                    "key": f"fbref_{key}",
                    "label": label,
                    "value": fbref.get(key),
                    "format": fmt,
                    "source": "FBRef",
                }
            )
    elif apps:
        rows.append(
            {
                "key": "goals",
                "label": f"Goals (L{apps})",
                "value": round(sum(_sum_kpi(g, "goals") for g in sample), 0),
                "format": "int",
                "source": "Impect",
            }
        )
        rows.append(
            {
                "key": "shot_xg",
                "label": f"Shot xG (L{apps})",
                "value": round(sum(_sum_kpi(g, "shot_xg") for g in sample), 2),
                "format": "2",
                "source": "Impect",
            }
        )
    return rows[:8]


def _key_stats(
    *,
    minutes: float | None,
    matches_est: int | None,
    recent_games: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    sample = recent_games or []
    goals = sum(_sum_kpi(game, "goals") for game in sample)
    assists = sum(_sum_kpi(game, "assists") for game in sample)
    shot_xg = sum(_sum_kpi(game, "shot_xg") for game in sample)
    apps = len(sample)
    return [
        {"key": "minutes", "label": "Minutes", "value": round(float(minutes), 0) if minutes is not None else None, "format": "int"},
        {"key": "matches", "label": "Matches", "value": matches_est, "format": "int"},
        {
            "key": "goals",
            "label": f"Goals (L{apps})" if apps else "Goals",
            "value": round(goals, 0) if apps else None,
            "format": "int",
        },
        {
            "key": "assists",
            "label": f"Assists (L{apps})" if apps else "Assists",
            "value": round(assists, 0) if apps else None,
            "format": "int",
        },
        {
            "key": "shot_xg",
            "label": f"Shot xG (L{apps})" if apps else "Shot xG",
            "value": round(shot_xg, 2) if apps else None,
            "format": "2",
        },
        {
            "key": "pxt_attack",
            "label": "PXT att / game",
            "value": _avg_kpi(sample, "pxt_attack"),
            "format": "2",
        },
        {
            "key": "ball_wins",
            "label": "Ball wins / game",
            "value": _avg_kpi(sample, "ball_win_number"),
            "format": "1",
        },
        {
            "key": "bypassed",
            "label": "Bypassed / game",
            "value": _avg_kpi(sample, "bypassed_opponents"),
            "format": "1",
        },
    ]


def _charts_url(
    *,
    name: str,
    player_id: int,
    iteration_id: int,
    squad_id: int | None,
    position: str | None,
    club: str | None,
    league: str | None,
    season: str | None,
) -> str:
    from app.scouting import _profiles_for_position

    params = [
        f"iteration={iteration_id}",
        f"playerId={player_id}",
        f"name={quote(name)}",
    ]
    if squad_id is not None:
        params.append(f"squad={squad_id}")
    if position:
        params.append(f"position={quote(position)}")
        try:
            profiles = _profiles_for_position(position)
            if profiles:
                params.append(f"profiles={quote(','.join(profiles[:6]))}")
        except Exception:
            pass
    if club:
        params.append(f"club={quote(club)}")
    if league:
        params.append(f"league={quote(league)}")
    if season:
        params.append(f"season={quote(season)}")
    return "/scouting/player?" + "&".join(params)


def build_player_games(
    player_id: int,
    *,
    iteration_id: int | None = None,
) -> dict[str, Any]:
    """Heavy recent/upcoming payload — loaded async so the main dossier stays snappy."""
    player = _resolve_catalog_player(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found in Impect catalog.")
    season_row = _pick_season(player, iteration_id)
    if season_row is None:
        raise HTTPException(status_code=404, detail="No season data available for this player.")

    iter_id = int(season_row["iteration_id"])
    squad_map = player.get("squad_ids_by_iteration") or {}
    squad_id_raw = squad_map.get(str(iter_id))
    squad_id = int(squad_id_raw) if squad_id_raw is not None else None
    club = str(season_row.get("club") or player.get("club") or "").strip() or None
    league = str(season_row.get("competition_name") or player.get("league") or "").strip() or None
    if not club and squad_id is not None:
        club = _impect()._fetch_squad_names(iter_id).get(squad_id)

    recent_games: list[dict[str, Any]] = []
    upcoming_games: list[dict[str, Any]] = []
    if squad_id is not None:
        # Upcoming first (FotMob) so the UI can paint fixtures quickly if called in parallel.
        upcoming_games = _upcoming_games(
            iter_id,
            squad_id,
            club_name=club,
            preferred_competition=league,
        )
        recent_games = _recent_games_with_fallback(
            player,
            iteration_id=iter_id,
            squad_id=squad_id,
            player_id=player_id,
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "player_id": player_id,
        "iteration_id": iter_id,
        "squad_id": squad_id,
        "club": club,
        "recent_games": recent_games,
        "upcoming_games": upcoming_games,
        "impect_columns": [
            {"key": key.lower(), "label": label}
            for key, label in DOSSIER_KPI_KEYS
            if key not in {"ASSISTS"}
        ],
    }


def build_player_dossier(
    player_id: int,
    *,
    iteration_id: int | None = None,
    include_games: bool = False,
) -> dict[str, Any]:
    player = _resolve_catalog_player(player_id)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player {player_id} not found in Impect catalog.")

    season_row = _pick_season(player, iteration_id)
    if season_row is None:
        raise HTTPException(status_code=404, detail="No season data available for this player.")

    iter_id = int(season_row["iteration_id"])
    squad_map = player.get("squad_ids_by_iteration") or {}
    squad_id_raw = squad_map.get(str(iter_id))
    squad_id = int(squad_id_raw) if squad_id_raw is not None else None
    name = str(player.get("name") or "Player")
    club = str(season_row.get("club") or player.get("club") or "").strip() or None
    league = str(season_row.get("competition_name") or player.get("league") or "").strip() or None
    season = str(season_row.get("season") or "").strip() or None

    if not club and squad_id is not None:
        club = _impect()._fetch_squad_names(iter_id).get(squad_id)

    raw = _raw_player_record(iter_id, player_id)
    primary_position, positions = _positions_block(iter_id, player_id, squad_id=squad_id)
    profiles: list[dict[str, Any]] = []
    minutes: float | None = None
    if squad_id is not None:
        profiles, minutes, scored_position = _profile_rows(
            iter_id, squad_id, player_id, primary_position
        )
        # If Impect shares missed the role but profile scores found a position, use it.
        if scored_position and not primary_position:
            from app.scouting import _scouting_position_label

            primary_position = scored_position
            if not any(str(row.get("code") or "").upper() == scored_position for row in positions):
                positions = [
                    {
                        "code": scored_position,
                        "label": _scouting_position_label(scored_position),
                        "minutes": round(float(minutes), 0) if minutes is not None else None,
                        "match_share": 100.0,
                    }
                ] + list(positions)

    # Games are slow (many Impect match calls) and used to empty-out under 429s when
    # bundled into the main dossier. Load via /api/player/{id}/games instead.
    recent_games: list[dict[str, Any]] = []
    upcoming_games: list[dict[str, Any]] = []
    if include_games and squad_id is not None:
        upcoming_games = _upcoming_games(
            iter_id,
            squad_id,
            club_name=club,
            preferred_competition=league,
        )
        recent_games = _recent_games_with_fallback(
            player,
            iteration_id=iter_id,
            squad_id=squad_id,
            player_id=player_id,
        )

    matches_est = _estimate_matches(minutes, len(recent_games))

    from app.player_web_enrichment import enrich_player_web

    # Strip U21/Academy so Transfermarkt search hits the main player page.
    club_lookup = club or ""
    club_lookup = re.sub(
        r"\s*(U\d{2}|Under[-\s]?\d{2}|Youth|Academy|Reserves?|II|B)\s*$",
        "",
        club_lookup,
        flags=re.I,
    ).strip(" -–—") or club

    web = enrich_player_web(name, club_name=club_lookup)
    tm = web.get("transfermarkt") if isinstance(web, dict) else None
    fbref = web.get("fbref") if isinstance(web, dict) else None

    height = None
    if tm and tm.get("height"):
        height = tm["height"]
    if not height:
        height = _height_for_player(name, club, season)
    if not height and raw:
        from app.scouting import _format_height

        height = _format_height(raw)
    # Never ship placeholder heights into packs / UI.
    if height:
        text = str(height).strip()
        if text in {"—", "-", "0'0", "0'0\"", "0'0\" (0cm)"} or text.startswith("0'0"):
            height = None
        elif tm and tm.get("height_cm"):
            # Prefer re-label from validated cm when available.
            from app.set_piece_pre_match import _height_label_from_cm

            labeled = _height_label_from_cm(tm.get("height_cm"))
            if labeled != "—":
                height = labeled

    foot = (tm or {}).get("foot") or _foot_label(raw)

    key_stats = _key_stats(
        minutes=minutes,
        matches_est=matches_est,
        recent_games=recent_games,
    )
    hero_stats = _hero_stats(
        minutes=minutes,
        matches_est=matches_est,
        profiles=profiles,
        recent_games=recent_games,
        tm=tm,
        fbref=fbref,
    )

    notes, scout_reports = _split_player_activity(player_id, name)
    ability = _ability_from_reports(scout_reports)

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "games_deferred": not include_games,
        "player": {
            "id": player_id,
            "key": player.get("key"),
            "name": name,
            "age": player.get("age"),
            "birthdate": player.get("birthdate") or player.get("birthDate"),
            "height": height or "—",
            "foot": foot or "—",
            "citizenship": (tm or {}).get("citizenship"),
            "market_value": (tm or {}).get("market_value"),
            "on_loan_from": (tm or {}).get("on_loan_from"),
            "club": club or "—",
            "league": league or "—",
            "season": season or "—",
            "iteration_id": iter_id,
            "squad_id": squad_id,
            "photo_url": _photo_url(name, club, season),
            "primary_position": primary_position,
            "primary_position_label": (
                _impect().POSITION_LABELS.get(primary_position, primary_position)
                if primary_position
                else "—"
            ),
            "positions": positions,
            "minutes": round(float(minutes), 0) if minutes is not None else None,
            "matches": matches_est,
        },
        "hero_stats": hero_stats,
        "key_stats": key_stats,
        "web": {
            "transfermarkt": tm,
            "fbref": fbref,
        },
        "seasons": player.get("seasons") or [],
        "profiles": profiles,
        "reports": scout_reports,
        "notes": notes,
        "ability": ability,
        "recent_games": recent_games,
        "upcoming_games": upcoming_games,
        "impect_columns": [
            {"key": key.lower(), "label": label}
            for key, label in DOSSIER_KPI_KEYS
            if key not in {"ASSISTS"}
        ],
        "links": {
            "charts": _charts_url(
                name=name,
                player_id=player_id,
                iteration_id=iter_id,
                squad_id=squad_id,
                position=primary_position,
                club=club,
                league=league,
                season=season,
            ),
            "compare": "/studio",
            "transfermarkt": (tm or {}).get("profile_url"),
            "fbref": (fbref or {}).get("profile_url"),
            "home": "/",
            "games": f"/api/player/{player_id}/games"
            + (f"?iteration={iter_id}" if iter_id else ""),
        },
    }


def register_player_dossier_routes(app: FastAPI) -> None:
    @app.get("/api/player/{player_id}")
    def player_dossier_api(
        player_id: int,
        iteration: int | None = Query(None),
    ) -> dict[str, Any]:
        return build_player_dossier(player_id, iteration_id=iteration)

    @app.get("/api/player/{player_id}/games")
    def player_dossier_games_api(
        player_id: int,
        iteration: int | None = Query(None),
    ) -> dict[str, Any]:
        return build_player_games(player_id, iteration_id=iteration)

    @app.get("/api/player/{player_id}/profiles")
    def player_profiles_api(
        player_id: int,
        position: str = Query(..., min_length=1),
        iteration: int | None = Query(None),
    ) -> dict[str, Any]:
        player = _resolve_catalog_player(player_id)
        if player is None:
            raise HTTPException(status_code=404, detail=f"Player {player_id} not found.")
        season_row = _pick_season(player, iteration)
        if season_row is None:
            raise HTTPException(status_code=404, detail="No season data for this player.")
        iter_id = int(season_row["iteration_id"])
        squad_map = player.get("squad_ids_by_iteration") or {}
        squad_raw = squad_map.get(str(iter_id))
        if squad_raw is None:
            raise HTTPException(status_code=404, detail="No squad for this player season.")
        squad_id = int(squad_raw)
        position_code = str(position or "").strip().upper()
        profiles, minutes, scored_position = _profile_rows(iter_id, squad_id, player_id, position_code)
        return {
            "player_id": player_id,
            "iteration_id": iter_id,
            "squad_id": squad_id,
            "position": scored_position or position_code,
            "position_label": _impect().POSITION_LABELS.get(
                scored_position or position_code,
                (scored_position or position_code).replace("_", " ").title(),
            ),
            "minutes": round(float(minutes), 0) if minutes is not None else None,
            "profiles": profiles,
        }

    @app.get("/api/player/{player_id}/notes")
    def player_notes_list_api(player_id: int) -> dict[str, Any]:
        player = _resolve_catalog_player(player_id)
        name = str((player or {}).get("name") or "")
        return {"player_id": player_id, **_activity_payload(player_id, name or str(player_id))}

    @app.post("/api/player/{player_id}/notes")
    def player_notes_create_api(player_id: int, body: PlayerNoteCreate) -> dict[str, Any]:
        player = _resolve_catalog_player(player_id)
        name = str((player or {}).get("name") or "")
        note = create_player_note(player_id, body, player_name=name)
        return _activity_payload(player_id, name or str(player_id), note=note)

    @app.patch("/api/player/{player_id}/notes/{note_id}")
    def player_notes_update_api(
        player_id: int,
        note_id: str,
        body: PlayerNoteUpdate,
    ) -> dict[str, Any]:
        note = update_player_note(player_id, note_id, body)
        player = _resolve_catalog_player(player_id)
        name = str((player or {}).get("name") or "")
        return _activity_payload(player_id, name or str(player_id), note=note)

    @app.delete("/api/player/{player_id}/notes/{note_id}")
    def player_notes_delete_api(player_id: int, note_id: str) -> dict[str, Any]:
        delete_player_note(player_id, note_id)
        player = _resolve_catalog_player(player_id)
        name = str((player or {}).get("name") or "")
        return {"ok": True, **_activity_payload(player_id, name or str(player_id))}

    @app.get("/player/{player_id}", response_class=HTMLResponse)
    def player_dossier_page(player_id: int) -> HTMLResponse:
        html_path = STANDALONE_DIR / "player-dossier.html"
        if not html_path.exists():
            raise HTTPException(status_code=404, detail="Player dossier page not found.")
        return HTMLResponse(
            html_path.read_text(encoding="utf-8"),
            headers={"Cache-Control": "no-cache, no-store, must-revalidate", "Pragma": "no-cache"},
        )
