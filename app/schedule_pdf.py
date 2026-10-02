"""Print-quality A4 landscape PDF of the Schedule calendar (one page per month).

Rendered by real Chrome (Playwright ``page.pdf``) so text stays vector and the
layout matches the browser — never html2canvas.
"""

from __future__ import annotations

import base64
import calendar
from datetime import date, datetime
from html import escape
from typing import Any

from app.paths import STANDALONE_DIR

try:
    from zoneinfo import ZoneInfo

    _LONDON = ZoneInfo("Europe/London")
except Exception:  # noqa: BLE001 — tzdata missing in slim images
    _LONDON = None


class ScheduleExportError(RuntimeError):
    pass


def _crest_data_uri() -> str:
    path = STANDALONE_DIR / "port-vale-badge.png"
    try:
        return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")
    except OSError:
        return ""


def _kickoff_label(iso: str | None) -> str:
    if not iso:
        return "TBC"
    try:
        dt = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
    except ValueError:
        return "TBC"
    if dt.tzinfo is not None and _LONDON is not None:
        dt = dt.astimezone(_LONDON)
    return dt.strftime("%H:%M")


def _report_label(hhmm: str | None) -> str:
    if not hhmm:
        return "9am report"
    try:
        hour, minute = (int(part) for part in hhmm.split(":"))
    except ValueError:
        return f"{hhmm} report"
    suffix = "pm" if hour >= 12 else "am"
    hour12 = (hour + 11) % 12 + 1
    return f"{hour12}:{minute:02d}{suffix} report" if minute else f"{hour12}{suffix} report"


def _month_range(start_month: str, months: int) -> list[tuple[int, int]]:
    year, month = (int(part) for part in start_month.split("-"))
    out = []
    for _ in range(months):
        out.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return out


def _season_label(year: int, month: int) -> str:
    start = year if month >= 7 else year - 1
    return f"{start}/{str(start + 1)[-2:]} season"


def _opponent(row: dict[str, Any]) -> tuple[str, str]:
    is_home = bool(row.get("isHome"))
    name = (row.get("opponent") or {}).get("name") or (row.get("away") if is_home else row.get("home"))
    badge = (row.get("opponent") or {}).get("badge") or (
        row.get("away_badge") if is_home else row.get("home_badge")
    )
    if badge and not str(badge).startswith(("http", "data:")):
        badge = ""
    return str(name or "TBC"), str(badge or "")


def _short_competition(value: str | None) -> str:
    text = str(value or "").strip()
    low = text.lower()
    if "trophy" in low:
        return "EFL Trophy"
    if "fa cup" in low:
        return "FA Cup"
    if "carabao" in low or "league cup" in low or "efl cup" in low:
        return "Carabao Cup"
    if "league two" in low or "league 2" in low:
        return "League Two"
    if "league one" in low or "league 1" in low:
        return "League One"
    if "friendl" in low:
        return "Friendly"
    return text


def _fixture_strip(year: int, month: int, payload: dict[str, Any]) -> str:
    prefix = f"{year}-{month:02d}-"
    rows = []
    for key in sorted(payload.get("fixtures_by_date") or {}):
        fixtures = (payload.get("fixtures_by_date") or {}).get(key) or []
        if not key.startswith(prefix) or not fixtures:
            continue
        match = fixtures[0]
        is_home = bool(match.get("isHome"))
        name, badge = _opponent(match)
        played = match.get("status") == "completed" or bool(match.get("outcome"))
        score = (match.get("scoreLabel") or match.get("score")) if played else None
        when = date.fromisoformat(key)
        badge_html = f'<img src="{escape(badge)}" alt="" />' if badge else ""
        rows.append(
            f"""<div class="fx fx--{"home" if is_home else "away"}">
              <div class="fx-date"><b>{when.day}</b><span>{when.strftime("%a")}</span></div>
              <div class="fx-crest">{badge_html}</div>
              <div class="fx-main">
                <div class="fx-opp">{escape(name)}</div>
                <div class="fx-meta">{escape(_short_competition(match.get("competition")))}</div>
              </div>
              <div class="fx-side">
                <span class="fx-ha">{"H" if is_home else "A"}</span>
                <span class="fx-ko">{escape(str(score)) if score else escape(_kickoff_label(match.get("kickoff_utc")))}</span>
              </div>
            </div>"""
        )
    if not rows:
        return ""
    return f'<div class="fixtures"><div class="fixtures-title">Fixtures</div><div class="fx-grid">{"".join(rows)}</div></div>'


def _cell_html(day: date, payload: dict[str, Any]) -> str:
    key = day.isoformat()
    entry = (payload.get("days") or {}).get(key) or {}
    day_type = entry.get("type")
    fixtures = (payload.get("fixtures_by_date") or {}).get(key) or []
    events = (payload.get("events_by_date") or {}).get(key) or []
    match = fixtures[0] if fixtures else None

    classes = ["cell"]
    body = ""
    if match:
        is_home = bool(match.get("isHome"))
        classes.append("cell--home" if is_home else "cell--away")
        name, badge = _opponent(match)
        played = match.get("status") == "completed" or bool(match.get("outcome"))
        score = (match.get("scoreLabel") or match.get("score")) if played else None
        meta = escape(str(score)) if score else f"{escape(_kickoff_label(match.get('kickoff_utc')))} KO"
        badge_html = (
            f'<span class="crest"><img src="{escape(badge)}" alt="" /></span>' if badge else ""
        )
        comp = _short_competition(match.get("competition"))
        body = f"""
          <div class="match">
            {badge_html}
            <div class="opp">{escape(name)}</div>
            <div class="chip">{"Home" if is_home else "Away"} · {meta}</div>
          </div>"""
    elif day_type == "training":
        late = str(entry.get("report_time") or "09:00") != "09:00"
        classes.append("cell--in-late" if late else "cell--in")
        body = f"""
          <div class="session">
            <div class="label">IN</div>
            <div class="chip">{escape(_report_label(entry.get("report_time")))}</div>
          </div>"""
    elif day_type == "regen":
        classes.append("cell--regen")
        body = '<div class="session"><div class="label">REGEN</div></div>'
    elif day_type == "preseason":
        classes.append("cell--preseason")
        body = '<div class="session"><div class="label label--sm">PRE-SEASON</div></div>'

    if events:
        classes.append("cell--has-notes")
    notes = "".join(
        '<div class="note">'
        + '<span class="note-body">'
        + (f'<span class="note-time">{escape(str(ev.get("time")))}</span>' if ev.get("time") else "")
        + f'{escape(str(ev.get("title") or "Note"))}</span></div>'
        for ev in events[:2]
    )
    if len(events) > 2:
        notes += f'<div class="note-more note-more--full">+{len(events) - 2} more</div>'
    if len(events) > 1:
        notes += f'<div class="note-more note-more--compact">+{len(events) - 1} more</div>'
    r_flag = '<span class="r">R</span>' if entry.get("recruitment_in") else ""
    return f"""
      <div class="{' '.join(classes)}">
        <div class="head"><span class="num">{day.day}</span>{r_flag}</div>
        {body}
        {f'<div class="notes">{notes}</div>' if notes else ""}
      </div>"""


def _month_stats(year: int, month: int, payload: dict[str, Any]) -> dict[str, int]:
    prefix = f"{year}-{month:02d}-"
    stats = {"home": 0, "away": 0, "in": 0, "regen": 0}
    for key, rows in (payload.get("fixtures_by_date") or {}).items():
        if key.startswith(prefix) and rows:
            stats["home" if rows[0].get("isHome") else "away"] += 1
    match_days = {k for k, v in (payload.get("fixtures_by_date") or {}).items() if v}
    for key, entry in (payload.get("days") or {}).items():
        if not key.startswith(prefix) or key in match_days:
            continue
        if entry.get("type") == "training":
            stats["in"] += 1
        elif entry.get("type") == "regen":
            stats["regen"] += 1
    return stats


def _page_html(
    year: int,
    month: int,
    payload: dict[str, Any],
    *,
    crest: str,
    owner_label: str,
    page_no: int,
    page_total: int,
    generated: str,
) -> str:
    weeks = calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    cells = []
    for week in weeks:
        for day in week:
            if day.month != month:
                cells.append('<div class="cell cell--out"></div>')
            else:
                cells.append(_cell_html(day, payload))
    stats = _month_stats(year, month, payload)
    compact = len(weeks) >= 6 or stats["home"] + stats["away"] > 4
    month_name = date(year, month, 1).strftime("%B %Y")
    crest_html = f'<img class="logo" src="{crest}" alt="Port Vale" />' if crest else ""
    weekdays = "".join(
        f"<div>{d}</div>" for d in ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
    )
    return f"""
    <section class="page{' page--compact' if compact else ''}">
      <header class="top">
        {crest_html}
        <div class="titles">
          <div class="eyebrow">Port Vale Football Club · {escape(owner_label)} schedule</div>
          <h1>{escape(month_name)}</h1>
          <div class="season">{escape(_season_label(year, month))}</div>
        </div>
        <div class="stats">
          <div class="stat"><b>{stats["home"] + stats["away"]}</b><span>Matches</span></div>
          <div class="stat"><b>{stats["home"]}<i>H</i> {stats["away"]}<i>A</i></b><span>Home / Away</span></div>
          <div class="stat"><b>{stats["in"]}</b><span>IN days</span></div>
          <div class="stat"><b>{stats["regen"]}</b><span>Regen</span></div>
        </div>
      </header>
      <div class="legend">
        <span><i class="sw sw--in"></i>IN 9am</span>
        <span><i class="sw sw--in-late"></i>IN 10am</span>
        <span><i class="sw sw--regen"></i>Regen</span>
        <span><i class="sw sw--pre"></i>Pre-season</span>
        <span><i class="sw sw--home"></i>Home match</span>
        <span><i class="sw sw--away"></i>Away match</span>
        <span><i class="sw sw--note"></i>Travel / notes</span>
        <span><i class="sw sw--r">R</i>Recruitment in</span>
      </div>
      <div class="weekdays">{weekdays}</div>
      <div class="grid" style="grid-template-rows: repeat({len(weeks)}, minmax(0, 1fr))">{"".join(cells)}</div>
      {_fixture_strip(year, month, payload)}
      <footer class="foot">
        <span>Port Vale Analysis · Generated {escape(generated)} · Fixtures via FotMob, kick-offs UK time</span>
        <span>{page_no} / {page_total}</span>
      </footer>
    </section>"""


_CSS = """
@page { size: A4 landscape; margin: 0; }
* { box-sizing: border-box; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
html, body { margin: 0; padding: 0; background: #0e1116; }
body { font-family: "Manrope", "Helvetica Neue", Arial, sans-serif; color: #f3f4f6; }
.page {
  width: 297mm; height: 210mm; padding: 0 9mm 6mm; display: flex; flex-direction: column;
  background: radial-gradient(140mm 80mm at 0% 0%, rgba(245,197,24,0.07), transparent 70%), #0e1116;
  page-break-after: always; break-after: page; overflow: hidden;
}
.page:last-child { page-break-after: auto; break-after: auto; }
.top {
  margin: 0 -9mm; padding: 5mm 9mm 4.5mm; display: flex; align-items: center; gap: 5mm;
  background: linear-gradient(100deg, #07080b 0%, #151920 60%, #1f242c 100%);
  border-bottom: 1.2mm solid #f5c518; color: #fff;
}
.logo { height: 17mm; width: auto; }
.titles { flex: 1; min-width: 0; }
.eyebrow { font-size: 7.5pt; letter-spacing: 0.16em; text-transform: uppercase; color: #f5c518; font-weight: 700; }
h1 {
  margin: 0.6mm 0 0; font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-weight: 800;
  font-size: 30pt; line-height: 1; letter-spacing: 0.02em; text-transform: uppercase;
}
.season { margin-top: 0.8mm; font-size: 8pt; color: #b6bdc9; font-weight: 600; }
.stats { display: flex; gap: 2.5mm; }
.stat {
  min-width: 21mm; padding: 2mm 3mm; border-radius: 2mm; text-align: center;
  background: rgba(255,255,255,0.06); border: 0.3mm solid rgba(255,255,255,0.12);
}
.stat b { display: block; font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-size: 17pt; line-height: 1; }
.stat b i { font-style: normal; font-size: 9pt; color: #9aa3b2; margin-left: 0.4mm; }
.stat span { display: block; margin-top: 0.8mm; font-size: 6.5pt; letter-spacing: 0.1em; text-transform: uppercase; color: #9aa3b2; font-weight: 700; }
.legend { display: flex; flex-wrap: wrap; gap: 5mm; padding: 3mm 0 2.4mm; font-size: 7.5pt; font-weight: 700; color: #c5cad3; }
.legend span { display: inline-flex; align-items: center; gap: 1.6mm; }
.sw { display: inline-block; width: 3.6mm; height: 3.6mm; border-radius: 0.8mm; font-style: normal; }
.sw--in { background: #1fa855; } .sw--in-late { background: #128a45; } .sw--regen { background: #e2405d; } .sw--pre { background: #0b7fc0; }
.sw--home { background: #d4a82a; } .sw--away { background: #1e40af; } .sw--note { background: #f9a8c9; }
.sw--r { background: #f5c518; color: #111; font-size: 6.5pt; font-weight: 800; text-align: center; line-height: 3.6mm; }
.weekdays { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1.4mm; margin-bottom: 1.4mm; }
.weekdays div {
  text-align: center; font-size: 7pt; font-weight: 800; letter-spacing: 0.14em; text-transform: uppercase;
  color: #8b94a3; padding: 1.2mm 0; border-bottom: 0.4mm solid #262b34;
}
.grid { flex: 1; min-height: 0; display: grid; grid-template-columns: repeat(7, 1fr); gap: 1.4mm; }
.cell {
  position: relative; min-height: 0; overflow: hidden; border-radius: 1.8mm; background: #1a1e25;
  border: 0.3mm solid #262b34; display: flex; flex-direction: column; padding: 1.4mm 1.8mm 1.6mm;
}
.cell--out { background: transparent; border: 0.3mm dashed #1f242c; }
.head { display: flex; align-items: center; justify-content: space-between; height: 4.2mm; }
.num { font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-size: 11pt; font-weight: 800; color: #8b94a3; }
.r { width: 4mm; height: 4mm; border-radius: 0.8mm; background: #f5c518; color: #111; font-size: 6.5pt; font-weight: 800; text-align: center; line-height: 4mm; }
.cell--in { background: linear-gradient(160deg, #26b862, #179448); border-color: #179448; }
.cell--in-late { background: linear-gradient(160deg, #128a45, #0b6b34); border-color: #0b6b34; }
.cell--regen { background: linear-gradient(160deg, #ea546f, #cc2f4c); border-color: #cc2f4c; }
.cell--preseason { background: linear-gradient(160deg, #1592d6, #0868a3); border-color: #0868a3; }
.cell--home { background: linear-gradient(160deg, #e2b93d, #c4961b); border-color: #c4961b; }
.cell--away { background: linear-gradient(160deg, #2a4fc4, #1b3592); border-color: #1b3592; }
.cell--in .num, .cell--in-late .num, .cell--regen .num, .cell--preseason .num, .cell--away .num { color: rgba(255,255,255,0.85); }
.cell--home .num { color: rgba(30,22,0,0.7); }
.notes { display: flex; flex-direction: column; gap: 0.6mm; margin-top: 0.8mm; }
.note-body { display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; overflow-wrap: anywhere; }
.cell--has-notes .notes { flex-shrink: 0; }
.cell--has-notes .session, .cell--has-notes .match { flex: 1 0 auto; min-height: auto; justify-content: center; }
.cell--has-notes .comp { display: none; }
.cell--has-notes .head { height: 3.6mm; }
.note {
  padding: 0.6mm 1.3mm; border-radius: 1mm; border-left: 0.8mm solid #e75a96;
  background: #fff; color: #111827; font-size: 7pt; font-weight: 700; line-height: 1.22;
  box-shadow: 0 0.2mm 0.6mm rgba(0,0,0,0.15);
}
.note-time { margin-right: 1mm; color: #be185d; font-weight: 800; }
.note-more { align-self: flex-start; font-size: 5.8pt; font-weight: 800; padding: 0.1mm 1.2mm; border-radius: 1mm; background: rgba(255,255,255,0.85); color: #be185d; }
.note-more--compact, .page--compact .note-more--full { display: none; }
.cell--has-notes .session, .cell--has-notes .match { gap: 0.7mm; }
.session, .match { flex: 1; min-height: 0; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 1mm; }
.label { font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-weight: 800; font-size: 17pt; line-height: 1; letter-spacing: 0.05em; color: #fff; }
.label--sm { font-size: 12pt; }
.page--compact .cell { padding: 1mm 1.6mm 1.2mm; }
.page--compact .head { height: 3.4mm; }
.page--compact .num { font-size: 10pt; }
.page--compact .label { font-size: 14pt; }
.page--compact .label--sm { font-size: 10pt; }
.page--compact .session, .page--compact .match { gap: 0.6mm; }
.page--compact .crest { width: 7.4mm; height: 7.4mm; }
.page--compact .crest img { max-width: 7.4mm; max-height: 7.4mm; }
.page--compact .opp { font-size: 9pt; }
.page--compact .note-body { -webkit-line-clamp: 1; }
.page--compact .note + .note { display: none; }
.page--compact .note-more--compact { display: block; }
.cell--has-notes .crest { display: none; }
.grid > .cell { height: 100%; }
.page--compact .notes { margin-top: 0.5mm; }
.fixtures { display: flex; align-items: stretch; gap: 3mm; margin-top: 2.6mm; padding-top: 2.4mm; border-top: 0.4mm solid #262b34; }
.fixtures-title {
  writing-mode: vertical-rl; transform: rotate(180deg); text-align: center;
  font-size: 6.5pt; font-weight: 800; letter-spacing: 0.18em; text-transform: uppercase; color: #f5c518;
}
.fx-grid { flex: 1; display: grid; grid-template-columns: repeat(4, 1fr); gap: 1.6mm 2mm; }
.fx {
  display: flex; align-items: center; gap: 2mm; padding: 1.1mm 2mm 1.1mm 1.6mm; border-radius: 1.4mm;
  background: #1a1e25; border: 0.3mm solid #262b34; border-left: 1.2mm solid #d4a82a; min-width: 0;
}
.fx--away { border-left-color: #1e40af; }
.fx-date { width: 7mm; text-align: center; line-height: 1; flex-shrink: 0; }
.fx-date b { display: block; font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-size: 13pt; font-weight: 800; color: #fff; }
.fx-date span { display: block; font-size: 5.6pt; font-weight: 800; letter-spacing: 0.1em; text-transform: uppercase; color: #8b94a3; }
.fx-crest { width: 6.6mm; height: 6.6mm; flex-shrink: 0; display: flex; align-items: center; justify-content: center; }
.fx-crest img { max-width: 6.6mm; max-height: 6.6mm; width: auto; height: auto; object-fit: contain; filter: drop-shadow(0 0.2mm 0.5mm rgba(0,0,0,0.5)); }
.fx-main { flex: 1; min-width: 0; }
.fx-opp {
  font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-weight: 800; font-size: 9.5pt; line-height: 1.05;
  text-transform: uppercase; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.fx-opp { color: #fff; }
.fx-meta { font-size: 5.8pt; font-weight: 700; color: #8b94a3; text-transform: uppercase; letter-spacing: 0.08em; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fx-side { display: flex; flex-direction: column; align-items: flex-end; gap: 0.5mm; flex-shrink: 0; }
.fx-ha { font-size: 6pt; font-weight: 800; padding: 0.2mm 1.4mm; border-radius: 0.8mm; background: #d4a82a; color: #1d1600; }
.fx--away .fx-ha { background: #2a4fc4; color: #fff; }
.fx--away { border-left-color: #2a4fc4; }
.fx-ko { font-size: 7pt; font-weight: 800; color: #fff; font-variant-numeric: tabular-nums; }
.chip {
  display: inline-block; padding: 0.5mm 2mm; border-radius: 10mm; font-size: 6.5pt; font-weight: 800;
  background: rgba(255,255,255,0.94); color: #111827; letter-spacing: 0.02em; white-space: nowrap;
}
.crest { flex: 0 0 auto; width: 9mm; height: 9mm; display: flex; align-items: center; justify-content: center; }
.crest img { max-width: 9mm; max-height: 9mm; width: auto; height: auto; object-fit: contain; filter: drop-shadow(0 0.3mm 0.7mm rgba(0,0,0,0.45)); }
.opp { font-family: "Barlow Condensed", "Arial Narrow", sans-serif; font-weight: 800; font-size: 10pt; line-height: 1.05; text-transform: uppercase; letter-spacing: 0.02em; }
.cell--away .opp { color: #fff; }
.cell--home .opp { color: #1d1600; }
.comp { max-width: 100%; font-size: 5.8pt; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; opacity: 0.8; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.cell--away .comp { color: #dbe4ff; }
.foot { display: flex; justify-content: space-between; padding-top: 2.4mm; font-size: 6.5pt; color: #6b7280; font-weight: 600; }
"""


def _fetch_badge(url: str) -> tuple[str, str]:
    import requests

    try:
        res = requests.get(url, timeout=6)
        if res.ok and res.content:
            mime = res.headers.get("Content-Type", "image/png").split(";")[0] or "image/png"
            return url, f"data:{mime};base64," + base64.b64encode(res.content).decode("ascii")
    except Exception:  # noqa: BLE001
        pass
    return url, ""


def _embed_badges(payload: dict[str, Any], month_list: list[tuple[int, int]]) -> dict[str, Any]:
    """Inline opponent badges so headless Chrome never prints a half-loaded image."""
    import copy
    from concurrent.futures import ThreadPoolExecutor

    prefixes = tuple(f"{y}-{m:02d}-" for y, m in month_list)
    by_date = copy.deepcopy(payload.get("fixtures_by_date") or {})
    urls = set()
    for key, rows in by_date.items():
        if key.startswith(prefixes):
            for row in rows:
                _, badge = _opponent(row)
                if badge.startswith("http"):
                    urls.add(badge)
    if not urls:
        return payload
    with ThreadPoolExecutor(max_workers=8) as pool:
        inline = dict(pool.map(_fetch_badge, urls))
    for key, rows in by_date.items():
        if not key.startswith(prefixes):
            continue
        for row in rows:
            _, badge = _opponent(row)
            if inline.get(badge):
                row["opponent"] = {**(row.get("opponent") or {}), "badge": inline[badge]}
    return {**payload, "fixtures_by_date": by_date}


def build_schedule_html(payload: dict[str, Any], *, start_month: str, months: int) -> str:
    owner_id = payload.get("owner") or "team"
    owner_label = next(
        (row.get("label") for row in payload.get("owners") or [] if row.get("id") == owner_id),
        "Team",
    )
    crest = _crest_data_uri()
    now = datetime.now(_LONDON) if _LONDON else datetime.now()
    generated = now.strftime("%d %b %Y, %H:%M")
    month_list = _month_range(start_month, months)
    payload = _embed_badges(payload, month_list)
    pages = "".join(
        _page_html(
            year,
            month,
            payload,
            crest=crest,
            owner_label=str(owner_label),
            page_no=index,
            page_total=len(month_list),
            generated=generated,
        )
        for index, (year, month) in enumerate(month_list, start=1)
    )
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8" />
<link href="https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@700;800&family=Manrope:wght@500;600;700;800&display=swap" rel="stylesheet" />
<style>{_CSS}</style></head><body>{pages}</body></html>"""


def build_schedule_pdf(payload: dict[str, Any], *, start_month: str, months: int = 1) -> bytes:
    html = build_schedule_html(payload, start_month=start_month, months=months)
    try:
        from playwright.sync_api import sync_playwright

        from app.wysiwyg_capture import WysiwygCaptureError, _launch_browser
    except Exception as exc:  # noqa: BLE001
        raise ScheduleExportError(f"PDF export unavailable: {exc}") from exc

    try:
        with sync_playwright() as playwright:
            browser = _launch_browser(playwright)
            try:
                page = browser.new_page()
                page.set_content(html, wait_until="load", timeout=45_000)
                try:
                    page.wait_for_function(
                        "() => [...document.images].every((img) => img.complete)",
                        timeout=10_000,
                    )
                except Exception:  # noqa: BLE001
                    pass
                # Google Fonts can hang headless Chrome; cap the wait.
                page.evaluate(
                    "() => Promise.race([document.fonts.ready, new Promise(r => setTimeout(r, 3000))])"
                )
                return page.pdf(
                    format="A4",
                    landscape=True,
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
                )
            finally:
                browser.close()
    except WysiwygCaptureError as exc:
        raise ScheduleExportError(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise ScheduleExportError(f"PDF render failed: {exc}") from exc
