"""Reports Library — every Port Vale player report filed from Match Scouting.

Lists general and detailed reports side by side with search / filters and a
read-only view of the full report. Editing stays in Match Scouting — both
fixture reports (team sheet) and manual reports (player search, ``manual-…``
fixture token) land in the same store and the same list.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import HTMLResponse

from app.paths import STANDALONE_DIR
from app.player_report_schema import (
    NEXT_ACTIONS,
    PVFC_LEVELS,
    REPORT_POSITIONS,
    report_group_for_position,
)
from app.player_reports import (
    HOME_AWAY_OPTIONS,
    VIEWING_OPTIONS,
    all_report_rows,
    clean_match_info,
    decorate_conditions,
    detailed_from_stored,
    general_from_stored,
    infer_home_away,
    is_stub_player,
    option_catalog,
    report_scout,
    report_source,
)

KINDS = ("general", "detailed")
_POSITION_SHORT = {code: short for code, short, _label in REPORT_POSITIONS}
_POSITION_LABEL = {code: label for code, _short, label in REPORT_POSITIONS}
_LEVEL_LABEL = {key: label for key, label, _hint in PVFC_LEVELS}
_ACTION_LABEL = {key: label for key, label in NEXT_ACTIONS}
_VIEWING_LABEL = dict(VIEWING_OPTIONS)
_HOME_AWAY_LABEL = dict(HOME_AWAY_OPTIONS)


def _split_key(key: str) -> tuple[int, str]:
    pid, _sep, fixture = str(key or "").partition(":")
    try:
        return int(pid), fixture.strip()
    except (TypeError, ValueError):
        return 0, ""


class _PlayerFallback:
    """Name / club / league for older reports that were saved without them."""

    def __init__(self, stubs: dict[str, Any] | None = None) -> None:
        self._seen: dict[int, dict[str, Any]] = {}
        self._pipeline: dict[int, dict[str, Any]] | None = None
        self._stubs = stubs or {}

    def _pipeline_index(self) -> dict[int, dict[str, Any]]:
        if self._pipeline is None:
            try:
                from app.player_pipelines import pipeline_index_by_player_id

                self._pipeline = pipeline_index_by_player_id()
            except Exception:
                self._pipeline = {}
        return self._pipeline

    def lookup(self, player_id: int) -> dict[str, Any]:
        if player_id in self._seen:
            return self._seen[player_id]
        stub = self._stubs.get(str(player_id))
        if isinstance(stub, dict):
            out = {key: stub.get(key) for key in ("name", "club", "league", "age")}
            out["position_label"] = _POSITION_LABEL.get(str(stub.get("position") or ""), "")
            self._seen[player_id] = out
            return out
        out: dict[str, Any] = {}
        try:
            from app.player_dossier import _cached_rows_for_player

            rows = _cached_rows_for_player(player_id)
        except Exception:
            rows = []
        if rows:
            row = rows[0]
            out = {
                "name": row.get("name") or "",
                "club": row.get("club") or "",
                "league": row.get("league") or "",
                "age": row.get("age"),
                "position_label": row.get("positionLabel") or "",
            }
        if not out.get("name"):
            target = self._pipeline_index().get(player_id) or {}
            out = {
                "name": target.get("name") or "",
                "club": target.get("club") or "",
                "league": target.get("league") or "",
                "age": target.get("age"),
                "position_label": target.get("position_label") or "",
            }
        self._seen[player_id] = out
        return out


def _meta_for(
    player_id: int,
    fixture_id: str,
    rows: list[dict[str, Any]],
    conditions: dict[str, Any],
    fallback: _PlayerFallback,
) -> dict[str, Any]:
    def first(key: str) -> Any:
        for row in rows:
            value = row.get(key) if isinstance(row, dict) else None
            if value not in (None, ""):
                return value
        return None

    cond = conditions.get(fixture_id) if isinstance(conditions.get(fixture_id), dict) else {}
    meta = {
        "name": first("name"),
        "club": first("club"),
        "league": first("league"),
        "age": first("age"),
        "position_label": first("position_label"),
        "fixture_label": first("fixture_label") or (cond or {}).get("fixture_label") or "",
        "home_name": first("home_name") or "",
        "away_name": first("away_name") or "",
        "sheet_side": first("sheet_side") or "",
    }
    if not meta["name"] or not meta["club"]:
        extra = fallback.lookup(player_id)
        for key in ("name", "club", "league", "age", "position_label"):
            if meta.get(key) in (None, ""):
                meta[key] = extra.get(key)
    meta["name"] = str(meta.get("name") or f"Player {player_id}")
    for key in ("club", "league", "position_label"):
        meta[key] = str(meta.get(key) or "")
    meta["source"] = report_source(rows[0] if rows else None, fixture_id)
    info = clean_match_info(first("match_info"))
    meta["match_info"] = info
    meta["competition"] = info["competition"]
    meta["match_date"] = info["match_date"]
    meta["viewing"] = info["viewing"]
    meta["viewing_label"] = _VIEWING_LABEL.get(info["viewing"], "")
    if meta["source"] == "manual":
        meta["home_away"] = _HOME_AWAY_LABEL.get(info["home_away"], "")
        meta["fixture_label"] = meta["fixture_label"] or "Manual report"
    else:
        meta["home_away"] = infer_home_away(
            club=meta["club"],
            fixture_label=meta["fixture_label"],
            home_name=meta["home_name"],
            away_name=meta["away_name"],
            sheet_side=meta["sheet_side"],
        ).get("label", "")
    meta["is_stub"] = is_stub_player(player_id)
    return meta


def _excerpt(*parts: Any, limit: int = 220) -> str:
    for part in parts:
        text = " ".join(str(part or "").split())
        if text:
            return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"
    return ""


def _summary(kind: str, key: str, report: dict[str, Any], meta: dict[str, Any], stored: dict[str, Any]) -> dict[str, Any]:
    player_id, fixture_id = _split_key(key)
    position = str(report.get("position_in_game") or "")
    level = str(report.get("pvfc_level") or "")
    action = str(report.get("next_action") or "")
    body = report.get("write_up") if kind == "detailed" else report.get("notes")
    return {
        "id": f"{kind}:{key}",
        "kind": kind,
        "player_id": player_id,
        "fixture_id": fixture_id,
        "name": meta["name"],
        "club": meta["club"],
        "league": meta["league"],
        "age": meta.get("age"),
        "fixture_label": meta["fixture_label"],
        "home_away": meta["home_away"],
        "position_in_game": position,
        "position_short": _POSITION_SHORT.get(position, ""),
        "position_label": _POSITION_LABEL.get(position, "") or meta["position_label"],
        "match_rating": report.get("match_rating"),
        "pvfc_level": level,
        "pvfc_level_label": _LEVEL_LABEL.get(level, ""),
        "next_action": action,
        "next_action_label": _ACTION_LABEL.get(action, ""),
        "source": meta["source"],
        "competition": meta["competition"],
        "match_date": meta["match_date"],
        "viewing": meta["viewing"],
        "viewing_label": meta["viewing_label"],
        "is_stub": meta["is_stub"],
        "scout": report_scout(stored) or str(report.get("updated_by") or ""),
        "updated_by": str(report.get("updated_by") or ""),
        "created_at": str(stored.get("created_at") or report.get("updated_at") or ""),
        "updated_at": str(report.get("updated_at") or ""),
        "excerpt": _excerpt(body, report.get("next_steps")),
    }


def list_reports() -> dict[str, Any]:
    raw = all_report_rows()
    conditions = raw["match_conditions"]
    fallback = _PlayerFallback(raw.get("players"))
    out: list[dict[str, Any]] = []
    keys = set(raw["general_reports"]) | set(raw["detailed_reports"])
    for key in keys:
        player_id, fixture_id = _split_key(key)
        if not player_id or not fixture_id:
            continue
        general_row = raw["general_reports"].get(key)
        detailed_row = raw["detailed_reports"].get(key)
        meta = _meta_for(
            player_id,
            fixture_id,
            [row for row in (detailed_row, general_row) if isinstance(row, dict)],
            conditions,
            fallback,
        )
        kinds_here: list[str] = []
        pending: list[dict[str, Any]] = []
        for kind, row, builder in (
            ("general", general_row, general_from_stored),
            ("detailed", detailed_row, detailed_from_stored),
        ):
            if not isinstance(row, dict):
                continue
            report = builder(player_id, fixture_id, row)
            if not report.get("filled"):
                continue
            kinds_here.append(kind)
            pending.append(_summary(kind, key, report, meta, row))
        for item in pending:
            item["has_general"] = "general" in kinds_here
            item["has_detailed"] = "detailed" in kinds_here
            out.append(item)
    out.sort(key=lambda row: row.get("updated_at") or "", reverse=True)
    return {
        "reports": out,
        "counts": {
            "total": len(out),
            "general": sum(1 for row in out if row["kind"] == "general"),
            "detailed": sum(1 for row in out if row["kind"] == "detailed"),
            "players": len({row["player_id"] for row in out}),
            "manual": sum(1 for row in out if row["source"] == "manual"),
        },
        "options": {
            "positions": [
                {"id": code, "short": short, "label": label} for code, short, label in REPORT_POSITIONS
            ],
            "pvfc_levels": [{"id": key, "label": label} for key, label, _hint in PVFC_LEVELS],
            "next_actions": [{"id": key, "label": label} for key, label in NEXT_ACTIONS],
        },
    }


def report_detail(kind: str, player_id: int, fixture_id: str) -> dict[str, Any]:
    kind = str(kind or "").strip().casefold()
    if kind not in KINDS:
        raise HTTPException(status_code=400, detail="kind must be general or detailed")
    token = str(fixture_id or "").strip()
    key = f"{int(player_id)}:{token}"
    raw = all_report_rows()
    general_row = raw["general_reports"].get(key)
    detailed_row = raw["detailed_reports"].get(key)
    row = general_row if kind == "general" else detailed_row
    if not isinstance(row, dict):
        raise HTTPException(status_code=404, detail="Report not found")
    builder = general_from_stored if kind == "general" else detailed_from_stored
    report = builder(int(player_id), token, row)
    meta = _meta_for(
        int(player_id),
        token,
        [r for r in (detailed_row, general_row) if isinstance(r, dict)],
        raw["match_conditions"],
        _PlayerFallback(raw.get("players")),
    )
    cond_row = raw["match_conditions"].get(token)
    position = str(report.get("position_in_game") or "")
    companion_kind = "detailed" if kind == "general" else "general"
    companion_row = detailed_row if kind == "general" else general_row
    companion_builder = detailed_from_stored if kind == "general" else general_from_stored
    companion_filled = isinstance(companion_row, dict) and companion_builder(
        int(player_id), token, companion_row
    ).get("filled")
    return {
        "summary": _summary(kind, key, report, meta, row),
        "report": report,
        "meta": meta,
        "match_conditions": decorate_conditions(
            cond_row if isinstance(cond_row, dict) else None,
            fixture_id=token,
            fixture_label=meta["fixture_label"],
        ),
        "report_group": report_group_for_position(position),
        "options": option_catalog(),
        "companion": {"kind": companion_kind, "available": bool(companion_filled)},
    }


def register_reports_library_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "reports-library.html"

    @app.get("/reports-library", response_class=HTMLResponse)
    def reports_library_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="Reports Library UI not found.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/reports-library")
    def reports_library_list() -> dict[str, Any]:
        return list_reports()

    @app.get("/api/reports-library/report")
    def reports_library_report(
        kind: str = Query(...),
        player_id: int = Query(...),
        fixture_id: str = Query(...),
    ) -> dict[str, Any]:
        return report_detail(kind, player_id, fixture_id)
