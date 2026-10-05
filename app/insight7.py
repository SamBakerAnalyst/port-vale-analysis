"""Insight7 — monthly Emerging Talent Bulletin PDFs, consolidated per player.

Staff upload one Insight7 bulletin PDF per league per month. Each PDF is parsed
(PyMuPDF table extraction, header-driven so column order can vary between
leagues), stored with its original file, and rolled up into one player list
with month-on-month changes.
"""

from __future__ import annotations

import json
import re
import threading
import unicodedata
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse

from app.paths import DATA_ROOT, STANDALONE_DIR

INSIGHT7_DIR = DATA_ROOT / "insight7"
INDEX_PATH = INSIGHT7_DIR / "reports.json"
PDF_DIR = INSIGHT7_DIR / "pdfs"
MAX_PDF_BYTES = 25 * 1024 * 1024

_LOCK = threading.Lock()

_MONTHS = {m: i for i, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), start=1
)}

# Canonical column keys, matched against the bulletin header text.
_HEADER_KEYS: tuple[tuple[str, str], ...] = (
    ("age", "age"),
    ("primary position", "position_code"),
    ("position", "position_code"),
    ("club", "club"),
    ("contract", "contract"),
    ("league mins", "league_mins"),
    ("league gt", "league_gt"),
    ("league apps", "league_apps"),
    ("league starts", "league_starts"),
    ("monthly", "monthly"),
    ("goals", "goals"),
    ("assists", "assists"),
    ("international", "international"),
    ("debut", "debut"),
    ("agent", "agent"),
    ("career note", "career_note"),
    ("mins per g", "mins_per_ga"),
)

_INT_FIELDS = ("age", "league_mins", "league_gt", "league_apps", "league_starts", "goals", "assists", "mins_per_ga")
_BOILERPLATE = (
    "emerging talent bulletin",
    "new addition to the review",
    "emerging players are defined",
    "insight7",
)
_SEASON_LINE = re.compile(r"^(?P<league>.+?)\s*-\s*(?P<season>\d{4}-\d{2,4})\s*$")
_DATE_TAIL = re.compile(r"^(?P<intl>.*?)\s+(?P<debut>\d{1,2}/\d{1,2}/\d{2,4})$")


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _clean(value: Any) -> str:
    text = " ".join(str(value or "").replace("\n", " ").split())
    return "" if text in ("-", "–") else text


def _norm_name(name: str) -> str:
    text = unicodedata.normalize("NFKD", name or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _norm_name(text)).strip("-") or "league"


def _to_int(value: Any) -> int | None:
    text = _clean(value).replace("%", "").replace(",", "")
    if not text:
        return None
    try:
        return int(round(float(text)))
    except ValueError:
        return None


def _parse_dmy(text: str) -> str:
    match = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{2,4})$", _clean(text))
    if not match:
        return ""
    day, month, year = (int(g) for g in match.groups())
    if year < 100:
        year += 2000
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def _position_short(code: str) -> str:
    code = _clean(code)
    return code.split("-", 1)[1] if "-" in code else code


def _header_map(row: list[Any]) -> dict[int, str] | None:
    cells = [_clean(c).casefold() for c in row]
    if "age" not in cells or not any("club" == c for c in cells):
        return None
    mapping: dict[int, str] = {}
    used: set[str] = set()
    for idx, text in enumerate(cells):
        if not text:
            continue
        for needle, key in _HEADER_KEYS:
            if text.startswith(needle) and key not in used:
                mapping[idx] = key
                used.add(key)
                break
    age_idx = cells.index("age")
    if age_idx > 0:
        mapping[age_idx - 1] = "name"
    return mapping


def _meta_lines(row: list[Any]) -> list[str]:
    lines: list[str] = []
    for cell in row:
        for line in str(cell or "").split("\n"):
            line = " ".join(line.split())
            if line:
                lines.append(line)
    return lines


def _parse_pdf(pdf_bytes: bytes) -> dict[str, Any]:
    import fitz  # PyMuPDF

    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Could not open PDF: {exc}") from exc

    league_line = ""
    season = ""
    footer_date = ""
    section = ""
    mapping: dict[int, str] | None = None
    players: dict[str, dict[str, Any]] = {}
    sections_seen: list[str] = []

    with doc:
        for page in doc:
            text = page.get_text("text") or ""
            if not footer_date:
                m = re.search(r"\b(\d{1,2})-([A-Za-z]{3})-(\d{4})\b", text)
                if m and m.group(2).casefold() in _MONTHS:
                    try:
                        footer_date = date(int(m.group(3)), _MONTHS[m.group(2).casefold()], int(m.group(1))).isoformat()
                    except ValueError:
                        pass
            try:
                tables = page.find_tables().tables
            except Exception:
                tables = []
            for table in tables:
                for row in table.extract():
                    header = _header_map(row)
                    if header:
                        mapping = header
                        continue
                    record = _row_record(row, mapping) if mapping else None
                    if record:
                        _merge_player(players, record, section)
                        continue
                    for line in _meta_lines(row):
                        low = line.casefold()
                        if any(b in low for b in _BOILERPLATE):
                            continue
                        season_match = _SEASON_LINE.match(line)
                        if season_match:
                            league_line = league_line or season_match.group("league").strip()
                            season = season or season_match.group("season")
                            continue
                        if len(line) <= 80 and not re.search(r"\d{2}/\d{2}/\d{2}", line):
                            section = line
                            if section not in sections_seen:
                                sections_seen.append(section)

    if not players:
        raise HTTPException(
            status_code=400,
            detail="No player tables found — is this an Insight7 Emerging Talent Bulletin PDF?",
        )
    return {
        "league_line": league_line,
        "season": season,
        "footer_date": footer_date,
        "sections": sections_seen,
        "players": list(players.values()),
    }


def _row_record(row: list[Any], mapping: dict[int, str]) -> dict[str, Any] | None:
    raw: dict[str, str] = {}
    for idx, key in mapping.items():
        if idx < len(row):
            raw[key] = _clean(row[idx])
    name = raw.get("name", "")
    if not name or _to_int(raw.get("age")) is None:
        return None
    intl = raw.get("international", "")
    debut = raw.get("debut", "")
    if intl and not debut:
        tail = _DATE_TAIL.match(intl)
        if tail:
            intl, debut = tail.group("intl").strip(), tail.group("debut")
    record: dict[str, Any] = {
        "name": name.replace("**", "").strip(),
        "position_code": raw.get("position_code", ""),
        "position": _position_short(raw.get("position_code", "")),
        "club": raw.get("club", ""),
        "contract": _parse_dmy(raw.get("contract", "")),
        "international": intl,
        "debut": _parse_dmy(debut) or debut,
        "agent": raw.get("agent", ""),
        "career_note": raw.get("career_note", ""),
    }
    for key in _INT_FIELDS:
        if key in raw:
            record[key] = _to_int(raw.get(key))
    return record


def _merge_player(players: dict[str, dict[str, Any]], record: dict[str, Any], section: str) -> None:
    key = f"{_norm_name(record['name'])}|{_norm_name(record.get('club', ''))}"
    existing = players.get(key)
    if existing is None:
        record["sections"] = [section] if section else []
        players[key] = record
        return
    for field, value in record.items():
        if existing.get(field) in (None, "") and value not in (None, ""):
            existing[field] = value
    if section and section not in existing["sections"]:
        existing["sections"].append(section)


def _report_date(filename: str, footer_date: str) -> str:
    m = re.search(r"(20\d{2})[.\-_ ](\d{1,2})[.\-_ ](\d{1,2})", filename or "")
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3))).isoformat()
        except ValueError:
            pass
    return footer_date or date.today().isoformat()


def _league_label(filename: str, league_line: str) -> str:
    stem = Path(filename or "").stem
    prefix = re.split(r"\s+-\s+emerging talent bulletin", stem, flags=re.IGNORECASE)[0].strip()
    if league_line and prefix and prefix != stem and league_line.casefold() in prefix.casefold():
        return prefix
    return league_line or prefix or "Unknown league"


# ---------------------------------------------------------------- storage


def _load() -> dict[str, Any]:
    if not INDEX_PATH.exists():
        return {"reports": {}}
    try:
        data = json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"reports": {}}
    if not isinstance(data.get("reports"), dict):
        data["reports"] = {}
    return data


def _save(data: dict[str, Any]) -> None:
    INSIGHT7_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    tmp.replace(INDEX_PATH)


def _report_meta(report: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in report.items() if k != "players"}


def _username(request: Request) -> str:
    try:
        from app.auth import current_user_payload

        payload = current_user_payload(request)
        return str(payload.get("display_name") or payload.get("username") or "")
    except Exception:
        return ""


def save_upload(filename: str, pdf_bytes: bytes, user: str) -> dict[str, Any]:
    parsed = _parse_pdf(pdf_bytes)
    report_date = _report_date(filename, parsed["footer_date"])
    league = _league_label(filename, parsed["league_line"])
    report = {
        "id": uuid.uuid4().hex[:12],
        "league": league,
        "league_key": _slug(league),
        "season": parsed["season"],
        "month": report_date[:7],
        "report_date": report_date,
        "filename": filename,
        "sections": parsed["sections"],
        "player_count": len(parsed["players"]),
        "uploaded_by": user,
        "uploaded_at": _now(),
        "players": parsed["players"],
    }
    with _LOCK:
        data = _load()
        replaced = [
            rid for rid, r in data["reports"].items()
            if r.get("league_key") == report["league_key"] and r.get("month") == report["month"]
        ]
        for rid in replaced:
            data["reports"].pop(rid, None)
            (PDF_DIR / f"{rid}.pdf").unlink(missing_ok=True)
        PDF_DIR.mkdir(parents=True, exist_ok=True)
        (PDF_DIR / f"{report['id']}.pdf").write_bytes(pdf_bytes)
        data["reports"][report["id"]] = report
        _save(data)
    out = _report_meta(report)
    out["replaced"] = len(replaced)
    return out


def update_report(report_id: str, league: str | None, month: str | None) -> dict[str, Any]:
    with _LOCK:
        data = _load()
        report = data["reports"].get(report_id)
        if not report:
            raise HTTPException(status_code=404, detail="Report not found")
        if league is not None and league.strip():
            report["league"] = league.strip()
            report["league_key"] = _slug(report["league"])
        if month is not None and month.strip():
            if not re.match(r"^20\d{2}-(0[1-9]|1[0-2])$", month.strip()):
                raise HTTPException(status_code=400, detail="Month must look like 2026-10")
            report["month"] = month.strip()
        clash = [
            rid for rid, r in data["reports"].items()
            if rid != report_id and r.get("league_key") == report["league_key"] and r.get("month") == report["month"]
        ]
        if clash:
            raise HTTPException(status_code=409, detail="There is already a bulletin for that league and month")
        _save(data)
        return _report_meta(report)


def delete_report(report_id: str) -> None:
    with _LOCK:
        data = _load()
        if data["reports"].pop(report_id, None) is None:
            raise HTTPException(status_code=404, detail="Report not found")
        (PDF_DIR / f"{report_id}.pdf").unlink(missing_ok=True)
        _save(data)


# ---------------------------------------------------------------- consolidation


def _snapshot(report: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    snap = {k: v for k, v in row.items()}
    snap.update(
        report_id=report["id"],
        league=report["league"],
        league_key=report["league_key"],
        month=report["month"],
        season=report.get("season", ""),
    )
    mins = row.get("league_mins")
    ga = (row.get("goals") or 0) + (row.get("assists") or 0)
    snap["ga"] = ga
    if row.get("mins_per_ga") is None and mins and ga:
        snap["mins_per_ga"] = round(mins / ga)
    return snap


def _diff(cur: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any] | None:
    if not prev:
        return None
    out: dict[str, Any] = {"from_month": prev["month"]}
    for key in ("league_mins", "league_gt", "goals", "assists", "ga"):
        a, b = cur.get(key), prev.get(key)
        out[key] = (a - b) if isinstance(a, int) and isinstance(b, int) else None
    out["club_changed"] = _norm_name(cur.get("club", "")) != _norm_name(prev.get("club", ""))
    return out


def consolidated() -> dict[str, Any]:
    data = _load()
    reports = sorted(data["reports"].values(), key=lambda r: (r.get("month", ""), r.get("report_date", "")))

    league_months: dict[str, list[str]] = {}
    league_names: dict[str, str] = {}
    for r in reports:
        league_months.setdefault(r["league_key"], []).append(r["month"])
        league_names[r["league_key"]] = r["league"]
    latest_month = {k: v[-1] for k, v in league_months.items()}
    prev_month = {k: (v[-2] if len(v) > 1 else None) for k, v in league_months.items()}

    by_player: dict[str, list[dict[str, Any]]] = {}
    for r in reports:
        for row in r.get("players") or []:
            by_player.setdefault(_norm_name(row.get("name", "")), []).append(_snapshot(r, row))

    players: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for key, snaps in by_player.items():
        snaps.sort(key=lambda s: s["month"])
        latest = snaps[-1]
        newest_month = latest["month"]
        same_month = [s for s in snaps if s["month"] == newest_month]
        primary = max(same_month, key=lambda s: s.get("league_mins") or 0)
        league_key = primary["league_key"]
        prev_in_league = [s for s in snaps if s["league_key"] == league_key and s["month"] < newest_month]
        prev = prev_in_league[-1] if prev_in_league else None

        is_current = newest_month == latest_month.get(league_key)
        expected_prev = prev_month.get(league_key)
        summary = {
            **{k: v for k, v in primary.items() if k not in ("report_id",)},
            "key": key,
            "leagues": sorted({s["league"] for s in snaps}),
            "months_listed": len({s["month"] for s in snaps}),
            "first_month": snaps[0]["month"],
            "is_current": is_current,
            "is_new": bool(is_current and expected_prev and not prev),
            "change": _diff(primary, prev) if prev and prev["month"] == expected_prev else None,
            "history": [
                {k: s.get(k) for k in (
                    "month", "league", "club", "league_mins", "league_gt", "goals", "assists",
                    "ga", "mins_per_ga", "sections", "contract", "age",
                )}
                for s in snaps
            ],
        }
        if is_current:
            players.append(summary)
        else:
            dropped.append(summary)

    coverage = []
    for league_key, months in league_months.items():
        by_month = {
            r["month"]: _report_meta(r) for r in reports if r["league_key"] == league_key
        }
        coverage.append({
            "league_key": league_key,
            "league": league_names[league_key],
            "latest_month": latest_month[league_key],
            "previous_month": prev_month[league_key],
            "months": by_month,
        })
    coverage.sort(key=lambda c: c["league"].casefold())

    all_months = sorted({r["month"] for r in reports})
    return {
        "players": players,
        "dropped": dropped,
        "coverage": coverage,
        "months": all_months,
        "reports": [_report_meta(r) for r in reversed(reports)],
        "sections": sorted({s for r in reports for s in r.get("sections") or []}),
        "today": date.today().isoformat(),
    }


# ---------------------------------------------------------------- routes


def register_insight7_routes(app: FastAPI) -> None:
    page_path = STANDALONE_DIR / "insight7.html"

    @app.get("/insight7", response_class=HTMLResponse)
    def insight7_page() -> HTMLResponse:
        if not page_path.is_file():
            raise HTTPException(status_code=404, detail="Insight7 UI not found.")
        return HTMLResponse(page_path.read_text(encoding="utf-8"))

    @app.get("/api/insight7")
    def insight7_data() -> dict[str, Any]:
        return consolidated()

    @app.post("/api/insight7/upload")
    async def insight7_upload(request: Request, files: list[UploadFile] = File(...)) -> dict[str, Any]:
        user = _username(request)
        results: list[dict[str, Any]] = []
        for upload in files:
            name = upload.filename or "bulletin.pdf"
            body = await upload.read()
            if not body:
                results.append({"filename": name, "ok": False, "error": "Empty file"})
                continue
            if len(body) > MAX_PDF_BYTES:
                results.append({"filename": name, "ok": False, "error": "File is larger than 25 MB"})
                continue
            if not body.startswith(b"%PDF"):
                results.append({"filename": name, "ok": False, "error": "Not a PDF"})
                continue
            try:
                meta = save_upload(name, body, user)
                results.append({"filename": name, "ok": True, "report": meta})
            except HTTPException as exc:
                results.append({"filename": name, "ok": False, "error": str(exc.detail)})
        return {"results": results}

    @app.post("/api/insight7/reports/{report_id}")
    def insight7_update(
        report_id: str,
        league: str | None = Form(None),
        month: str | None = Form(None),
    ) -> dict[str, Any]:
        return update_report(report_id, league, month)

    @app.delete("/api/insight7/reports/{report_id}")
    def insight7_delete(report_id: str) -> dict[str, Any]:
        delete_report(report_id)
        return {"ok": True}

    @app.get("/api/insight7/reports/{report_id}/pdf")
    def insight7_pdf(report_id: str) -> FileResponse:
        if not re.fullmatch(r"[a-f0-9]{12}", report_id):
            raise HTTPException(status_code=404, detail="Report not found")
        path = PDF_DIR / f"{report_id}.pdf"
        report = _load()["reports"].get(report_id)
        if not path.is_file() or not report:
            raise HTTPException(status_code=404, detail="PDF not found")
        return FileResponse(path, media_type="application/pdf", filename=report.get("filename") or f"{report_id}.pdf")
