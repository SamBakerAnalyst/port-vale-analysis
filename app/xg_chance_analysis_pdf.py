from __future__ import annotations

from io import BytesIO
from pathlib import Path
from typing import Any

import requests
from fpdf import FPDF

from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe

# Match webpage CSS variables as closely as Helvetica + RGB allow.
BG = (12, 15, 20)
SURFACE = (20, 26, 34)
SURFACE_2 = (26, 34, 45)
BORDER = (42, 53, 68)
TEXT = (232, 237, 244)
MUTED = (139, 155, 176)
ACCENT = (52, 211, 153)
VALE = (61, 139, 253)
OPP = (100, 116, 139)
GOLD = (251, 191, 36)
GOOD = (34, 197, 94)
BAD = (239, 68, 68)
ROW_ALT = (18, 23, 30)

MARGIN = 6.0
GAP = 4.0

CHANCE_COLORS = {
    "excellent": (22, 101, 52),
    "very_good": (34, 197, 94),
    "ok": (250, 204, 21),
    "poor": (249, 115, 22),
    "very_poor": (239, 68, 68),
}

from app.paths import PORT_VALE_BADGE


def _fmt(value: Any, kind: str = "dec", digits: int = 3) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return pdf_safe(str(value))
    if kind == "int":
        return str(int(round(number)))
    if kind == "pct":
        return f"{number:.1f}%"
    if digits == 2:
        return f"{number:.2f}"
    return f"{number:.3f}"


def _direction_color(direction: str) -> tuple[int, int, int]:
    if direction == "up":
        return GOOD
    if direction == "down":
        return BAD
    return MUTED


def _fetch_image_bytes(url: str | None) -> BytesIO | None:
    if not url:
        return None
    try:
        response = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "Mozilla/5.0 (Port Vale analysis dashboard)"},
        )
        if response.status_code >= 400 or len(response.content) < 64:
            return None
        return BytesIO(response.content)
    except requests.RequestException:
        return None


def _local_badge() -> Path | None:
    return PORT_VALE_BADGE if PORT_VALE_BADGE.exists() else None


class XgChanceAnalysisPDF(FPDF):
    """16:9 Keynote slides styled to mirror the xG Chance Analysis webpage."""

    def __init__(self) -> None:
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)
        self.set_display_mode(zoom="fullpage", layout="single")

    def _fill(self, color: tuple[int, int, int]) -> None:
        self.set_fill_color(*color)

    def _text(self, color: tuple[int, int, int]) -> None:
        self.set_text_color(*color)

    def _draw(self, color: tuple[int, int, int]) -> None:
        self.set_draw_color(*color)

    def _bg(self) -> None:
        self._fill(BG)
        self.rect(0, 0, SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM, style="F")

    def _card(self, x: float, y: float, w: float, h: float, *, fill: tuple[int, int, int] = SURFACE) -> None:
        self._fill(fill)
        self._draw(BORDER)
        self.set_line_width(0.35)
        self.rect(x, y, w, h, style="DF")

    def _chip(self, x: float, y: float, label: str, *, accent: bool = False) -> float:
        text = pdf_safe(label).upper()
        self.set_font("Helvetica", "B", 7)
        text_w = self.get_string_width(text) + 6
        chip_h = 6.0
        if accent:
            self._fill(ACCENT)
            self.rect(x, y, text_w, chip_h, style="F")
            self._text(BG)
        else:
            self._fill(SURFACE_2)
            self._draw(BORDER)
            self.set_line_width(0.25)
            self.rect(x, y, text_w, chip_h, style="DF")
            self._text(MUTED)
        self.set_xy(x, y + 1.2)
        self.cell(text_w, 4, text, align="C")
        return text_w + 2.5

    def _pill(self, x: float, y: float, w: float, h: float, label: str, color: tuple[int, int, int]) -> None:
        self._fill(color)
        self.rect(x, y, w, h, style="F")
        self.set_xy(x, y + 0.8)
        self.set_font("Helvetica", "B", 6.5)
        # Light text on dark greens/reds; dark text on yellow/orange.
        luminance = (0.299 * color[0]) + (0.587 * color[1]) + (0.114 * color[2])
        self._text((12, 15, 20) if luminance > 150 else TEXT)
        self.cell(w, h - 1.5, pdf_safe(label), align="C")

    def _toolbar(self, title: str, subtitle: str) -> float:
        x = MARGIN
        y = MARGIN
        w = SLIDE_WIDTH_MM - (MARGIN * 2)
        self.set_xy(x, y)
        self.set_font("Helvetica", "B", 16)
        self._text(TEXT)
        self.cell(w, 8, pdf_safe(title.upper()))
        self.set_xy(x, y + 8)
        self.set_font("Helvetica", "", 8)
        self._text(MUTED)
        self.cell(w, 4, pdf_safe(subtitle))
        return y + 14

    def _xg_bar(
        self,
        x: float,
        y: float,
        w: float,
        label: str,
        value: float,
        max_value: float,
        fill: tuple[int, int, int],
    ) -> None:
        label_w = 22.0
        value_w = 18.0
        track_w = w - label_w - value_w - 4
        self.set_xy(x, y)
        self.set_font("Helvetica", "B", 7)
        self._text(MUTED)
        self.cell(label_w, 5, pdf_safe(label.upper()))

        track_x = x + label_w
        self._fill(SURFACE_2)
        self.rect(track_x, y + 1.2, track_w, 3.2, style="F")
        pct = max(0.08, min(1.0, float(value) / max(max_value, 0.01)))
        self._fill(fill)
        self.rect(track_x, y + 1.2, track_w * pct, 3.2, style="F")

        self.set_xy(track_x + track_w + 2, y)
        self.set_font("Helvetica", "B", 8)
        self._text(TEXT)
        self.cell(value_w, 5, _fmt(value), align="R")

    def _draw_crest(self, x: float, y: float, size: float, image: BytesIO | Path | None, initials: str) -> None:
        if image is not None:
            try:
                self.image(image, x=x, y=y, w=size, h=size)
                return
            except Exception:
                pass
        self._fill(SURFACE_2)
        self._draw(BORDER)
        self.rect(x, y, size, size, style="DF")
        self.set_xy(x, y + size * 0.32)
        self.set_font("Helvetica", "B", 9)
        self._text(MUTED)
        self.cell(size, 5, pdf_safe(initials[:2].upper()), align="C")

    def _bucket_table(self, x: float, y: float, w: float, h: float, title: str, summary: dict[str, Any]) -> None:
        self._card(x, y, w, h)
        pad = 4.0
        self.set_xy(x + pad, y + 3)
        self.set_font("Helvetica", "B", 9)
        self._text(TEXT)
        self.cell(w - pad * 2, 5, pdf_safe(title.upper()))

        headers = ["Chance rating", "Goals", "Count", "%", "Cumulative xG"]
        widths = [w * 0.36, w * 0.12, w * 0.14, w * 0.12, w * 0.26]
        row_y = y + 11
        cursor = x + pad
        self.set_font("Helvetica", "B", 6.5)
        self._text(MUTED)
        for header, col_w in zip(headers, widths):
            self.set_xy(cursor, row_y)
            align = "L" if header == "Chance rating" else "R"
            self.cell(col_w - 1, 4, header.upper() if header != "Chance rating" else header, align=align)
            cursor += col_w

        self._draw(BORDER)
        self.set_line_width(0.2)
        self.line(x + pad, row_y + 5, x + w - pad, row_y + 5)

        buckets = summary.get("buckets") or []
        grouped = summary.get("grouped") or {}
        totals = summary.get("totals") or {}
        body_top = row_y + 6.5
        body_h = h - (body_top - y) - 4
        row_count = len(buckets) + 3  # + HQ / LQ / Total
        row_h = min(8.2, body_h / max(row_count, 1))

        def draw_row(values: list[str], *, pill: tuple[str, tuple[int, int, int]] | None = None, muted: bool = False, bold: bool = False) -> None:
            nonlocal body_top
            cursor_x = x + pad
            for col_i, (value, col_w) in enumerate(zip(values, widths)):
                if col_i == 0 and pill is not None:
                    self._pill(cursor_x, body_top + 1.1, min(28.0, col_w - 2), row_h - 2.2, pill[0], pill[1])
                else:
                    self.set_xy(cursor_x, body_top + 1.4)
                    self.set_font("Helvetica", "B" if bold else "", 7)
                    self._text(MUTED if muted else TEXT)
                    align = "L" if col_i == 0 else "R"
                    self.cell(col_w - 1, row_h - 2.5, pdf_safe(value), align=align)
                cursor_x += col_w
            body_top += row_h

        for row in buckets:
            bucket_id = str(row.get("id") or "")
            color = CHANCE_COLORS.get(bucket_id, MUTED)
            draw_row(
                [
                    str(row.get("label") or ""),
                    str(row.get("goals") or 0),
                    str(row.get("count") or 0),
                    f"{row.get('pct') or 0}%",
                    _fmt(row.get("cumulativeXg")),
                ],
                pill=(str(row.get("label") or ""), color),
            )

        hq = grouped.get("highQuality") or {}
        lq = grouped.get("lowQuality") or {}
        draw_row(
            [
                str(hq.get("label") or "Excellent / Very Good"),
                str(hq.get("goals") or 0),
                str(hq.get("count") or 0),
                "-",
                _fmt(hq.get("cumulativeXg")),
            ],
            muted=True,
        )
        draw_row(
            [
                str(lq.get("label") or "Poor / Very Poor"),
                str(lq.get("goals") or 0),
                str(lq.get("count") or 0),
                "-",
                _fmt(lq.get("cumulativeXg")),
            ],
            muted=True,
        )
        draw_row(
            [
                "Total",
                str(totals.get("goals") or 0),
                str(totals.get("shots") or 0),
                "100%",
                _fmt(totals.get("cumulativeXg")),
            ],
            bold=True,
        )

    def _player_table(self, x: float, y: float, w: float, h: float, title: str, players: list[dict[str, Any]], *, limit: int = 9) -> None:
        self._card(x, y, w, h)
        pad = 3.5
        self.set_xy(x + pad, y + 3)
        self.set_font("Helvetica", "B", 9)
        self._text(TEXT)
        self.cell(w - pad * 2, 5, pdf_safe(title.upper()))

        headers = ["#", "Player", "Shots", "xG", "Exc", "VG", "OK", "Poor", "VP", "G"]
        widths = [w * 0.05, w * 0.30, w * 0.08, w * 0.10, w * 0.07, w * 0.07, w * 0.07, w * 0.08, w * 0.07, w * 0.06]
        row_y = y + 11
        cursor = x + pad
        self.set_font("Helvetica", "B", 6)
        self._text(MUTED)
        for header, col_w in zip(headers, widths):
            self.set_xy(cursor, row_y)
            self.cell(col_w, 4, header, align="C" if header != "Player" else "L")
            cursor += col_w

        rows = (players or [])[:limit]
        body_top = row_y + 5.5
        available = h - (body_top - y) - 3
        row_h = min(8.0, available / max(len(rows) or 1, 1))
        if not rows:
            self.set_xy(x + pad, body_top + 2)
            self.set_font("Helvetica", "", 8)
            self._text(MUTED)
            self.cell(w - pad * 2, 5, "No shots")
            return

        for index, row in enumerate(rows):
            if index % 2 == 0:
                self._fill(ROW_ALT)
                self.rect(x + 1.5, body_top, w - 3, row_h, style="F")
            counts = row.get("chanceCounts") or {}
            values = [
                str(index + 1),
                str(row.get("playerName") or "Unknown"),
                str(row.get("shots") or 0),
                _fmt(row.get("xg"), digits=2),
                str(counts.get("excellent") or 0),
                str(counts.get("very_good") or 0),
                str(counts.get("ok") or 0),
                str(counts.get("poor") or 0),
                str(counts.get("very_poor") or 0),
                str(row.get("goals") or 0),
            ]
            cursor = x + pad
            for col_i, (value, col_w) in enumerate(zip(values, widths)):
                self.set_xy(cursor, body_top + 1.5)
                self.set_font("Helvetica", "B" if col_i == 1 else "", 7)
                self._text(TEXT)
                self.cell(col_w, row_h - 2.5, pdf_safe(value), align="C" if col_i != 1 else "L")
                cursor += col_w
            body_top += row_h

    def add_match_summary_slide(self, report: dict[str, Any]) -> None:
        match = (report.get("matches") or [{}])[0]
        opponent = (match.get("opponent") or {})
        opponent_name = str(opponent.get("name") or "Opponent")
        competition = str(report.get("competition") or "")
        season = str(report.get("season") or "")
        vale_goals = match.get("valeGoals")
        opp_goals = match.get("oppGoals")
        vale_xg = float(match.get("valeXg") or 0)
        opp_xg = float(match.get("oppXg") or 0)
        max_xg = max(vale_xg, opp_xg, 0.01)
        vale_won = isinstance(vale_goals, (int, float)) and isinstance(opp_goals, (int, float)) and vale_goals > opp_goals
        opp_won = isinstance(vale_goals, (int, float)) and isinstance(opp_goals, (int, float)) and opp_goals > vale_goals

        self.add_page()
        self._bg()
        content_top = self._toolbar(
            "xG Chance Analysis",
            f"{competition} {season}  |  Latest / selected match  |  {opponent_name}",
        )

        hero_x = MARGIN
        hero_y = content_top
        hero_w = SLIDE_WIDTH_MM - (MARGIN * 2)
        hero_h = 72.0
        self._card(hero_x, hero_y, hero_w, hero_h)

        chip_x = hero_x + 5
        chip_y = hero_y + 4
        chip_x += self._chip(chip_x, chip_y, f"MD{match.get('matchDay') or '?'}", accent=True)
        if match.get("dateLabel"):
            chip_x += self._chip(chip_x, chip_y, str(match.get("dateLabel")))
        if match.get("venue"):
            self._chip(chip_x, chip_y, str(match.get("venue")))

        self.set_xy(hero_x + hero_w * 0.55, hero_y + 4.5)
        self.set_font("Helvetica", "B", 7)
        self._text(MUTED)
        self.cell(hero_w * 0.45 - 5, 4, pdf_safe(f"{competition} {season}").upper(), align="R")

        crest_size = 16.0
        score_y = hero_y + 15
        mid = hero_x + hero_w / 2
        vale_badge = _local_badge()
        opp_badge = _fetch_image_bytes(opponent.get("imageUrl"))

        # Vale (left block): crest + name + goals
        vale_block_x = mid - 95
        self._draw_crest(vale_block_x + 13, score_y, crest_size, vale_badge, "PV")
        self.set_xy(vale_block_x, score_y + crest_size + 1.5)
        self.set_font("Helvetica", "B", 12)
        self._text(TEXT)
        self.cell(42, 5, "PORT VALE", align="C")
        self.set_xy(vale_block_x + 42, score_y + 2)
        self.set_font("Helvetica", "B", 30)
        self._text(ACCENT if vale_won else TEXT)
        self.cell(24, 16, pdf_safe(str(vale_goals if vale_goals is not None else "-")), align="C")

        self.set_xy(mid - 8, score_y + 5)
        self.set_font("Helvetica", "B", 18)
        self._text(MUTED)
        self.cell(16, 12, "-", align="C")

        # Opp (right block)
        opp_block_x = mid + 29
        self.set_xy(opp_block_x, score_y + 2)
        self.set_font("Helvetica", "B", 30)
        self._text(ACCENT if opp_won else TEXT)
        self.cell(24, 16, pdf_safe(str(opp_goals if opp_goals is not None else "-")), align="C")
        self._draw_crest(opp_block_x + 28, score_y, crest_size, opp_badge, opponent_name[:2])
        self.set_xy(opp_block_x + 16, score_y + crest_size + 1.5)
        self.set_font("Helvetica", "B", 12)
        self._text(TEXT)
        self.cell(42, 5, pdf_safe(opponent_name.upper())[:18], align="C")

        bar_x = hero_x + 28
        bar_w = hero_w - 56
        self._xg_bar(bar_x, hero_y + 48, bar_w, "Vale xG", vale_xg, max_xg, VALE)
        self._xg_bar(bar_x, hero_y + 56, bar_w, "Opp xG", opp_xg, max_xg, ACCENT)

        self.set_xy(hero_x, hero_y + hero_h - 8)
        self.set_font("Helvetica", "", 7.5)
        self._text(MUTED)
        self.cell(
            hero_w,
            4,
            pdf_safe(
                f"{match.get('valeShots') or 0} Vale shots  ·  {match.get('shotCount') or 0} total shots  ·  "
                f"{match.get('oppShots') or 0} Opp shots"
            ),
            align="C",
        )

        tables_y = hero_y + hero_h + GAP
        tables_h = SLIDE_HEIGHT_MM - tables_y - MARGIN
        table_w = (hero_w - GAP) / 2
        self._bucket_table(hero_x, tables_y, table_w, tables_h, "xG created (Vale)", report.get("xgCreated") or {})
        self._bucket_table(
            hero_x + table_w + GAP,
            tables_y,
            table_w,
            tables_h,
            "xG against (Opposition)",
            report.get("xgAgainst") or {},
        )

    def add_match_players_slide(self, report: dict[str, Any]) -> None:
        match = (report.get("matches") or [{}])[0]
        opponent = ((match.get("opponent") or {}).get("name")) or "Opponent"
        self.add_page()
        self._bg()
        top = self._toolbar(
            "Shot quality by player",
            f"MD{match.get('matchDay') or '?'} vs {opponent}  |  {report.get('competition') or ''} {report.get('season') or ''}",
        )
        panel_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP) / 2
        panel_h = SLIDE_HEIGHT_MM - top - MARGIN
        players = report.get("playerBreakdown") or {}
        self._player_table(MARGIN, top, panel_w, panel_h, "Vale", players.get("vale") or {}, limit=10)
        self._player_table(MARGIN + panel_w + GAP, top, panel_w, panel_h, "Opposition", players.get("opp") or {}, limit=10)

    def add_last6_overview_slide(self, report: dict[str, Any]) -> None:
        averages = report.get("averages") or {}
        trends = report.get("trends") or {}
        self.add_page()
        self._bg()
        top = self._toolbar(
            "xG Chance Analysis",
            f"{report.get('competition') or ''} {report.get('season') or ''}  |  Last 6 average",
        )

        kpis = [
            ("Games", _fmt(averages.get("games"), "int")),
            ("xG for /g", _fmt(averages.get("valeXg"), digits=2)),
            ("xG against /g", _fmt(averages.get("oppXg"), digits=2)),
            ("xG diff /g", _fmt(averages.get("xgDiff"), digits=2)),
            ("HQ share", _fmt(averages.get("valeHighQualityPct"), "pct")),
        ]
        card_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP * 4) / 5
        for i, (label, value) in enumerate(kpis):
            x = MARGIN + i * (card_w + GAP)
            self._card(x, top, card_w, 22, fill=SURFACE)
            self.set_xy(x + 2, top + 3)
            self.set_font("Helvetica", "", 6.5)
            self._text(MUTED)
            self.cell(card_w - 4, 4, pdf_safe(label.upper()), align="C")
            self.set_xy(x + 2, top + 9)
            self.set_font("Helvetica", "B", 13)
            self._text(TEXT)
            self.cell(card_w - 4, 8, pdf_safe(value), align="C")

        body_y = top + 26
        body_h = SLIDE_HEIGHT_MM - body_y - MARGIN
        left_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP) * 0.48
        right_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP) * 0.52

        self._card(MARGIN, body_y, left_w, body_h)
        self.set_xy(MARGIN + 4, body_y + 3)
        self.set_font("Helvetica", "B", 9)
        self._text(ACCENT)
        self.cell(left_w - 8, 5, "RECENT FORM")
        insight_y = body_y + 11
        for insight in (trends.get("insights") or [])[:6]:
            self.set_xy(MARGIN + 5, insight_y)
            self.set_font("Helvetica", "", 8)
            self._text(TEXT)
            self.multi_cell(left_w - 10, 4.5, pdf_safe(f"- {insight}"))
            insight_y = self.get_y() + 1.5

        right_x = MARGIN + left_w + GAP
        self._card(right_x, body_y, right_w, body_h)
        self.set_xy(right_x + 4, body_y + 3)
        self.set_font("Helvetica", "B", 9)
        self._text(ACCENT)
        self.cell(right_w - 8, 5, "TREND METRICS")
        metric_y = body_y + 12
        for row in (trends.get("metrics") or [])[:6]:
            direction = str(row.get("direction") or "flat")
            kind = "pct" if "Pct" in str(row.get("id") or "") else "dec"
            self.set_xy(right_x + 4, metric_y)
            self.set_font("Helvetica", "B", 7.5)
            self._text(TEXT)
            self.cell(right_w * 0.38, 5, pdf_safe(str(row.get("label") or "")))
            self.set_font("Helvetica", "", 7.5)
            self._text(MUTED)
            self.cell(
                right_w * 0.40,
                5,
                pdf_safe(f"{_fmt(row.get('earlier'), kind, 2)}  ->  {_fmt(row.get('recent'), kind, 2)}"),
            )
            self.set_font("Helvetica", "B", 7.5)
            self._text(_direction_color(direction))
            self.cell(right_w * 0.14, 5, direction.upper(), align="R")
            metric_y += 9

    def add_last6_matches_slide(self, report: dict[str, Any]) -> None:
        self.add_page()
        self._bg()
        top = self._toolbar(
            "Last 6 - match by match",
            f"{report.get('competition') or ''} {report.get('season') or ''}  |  Scoreline, xG and high-quality shot share",
        )
        rows = report.get("matchTrends") or []
        panel_h = SLIDE_HEIGHT_MM - top - MARGIN
        self._card(MARGIN, top, SLIDE_WIDTH_MM - (MARGIN * 2), panel_h)
        inner_w = SLIDE_WIDTH_MM - (MARGIN * 2) - 8
        headers = ["MD", "Opponent", "Venue", "Score", "Vale xG", "Opp xG", "Diff", "HQ%"]
        widths = [
            inner_w * 0.07,
            inner_w * 0.30,
            inner_w * 0.10,
            inner_w * 0.10,
            inner_w * 0.11,
            inner_w * 0.11,
            inner_w * 0.10,
            inner_w * 0.11,
        ]
        row_y = top + 5
        cursor = MARGIN + 4
        self.set_font("Helvetica", "B", 7)
        self._text(MUTED)
        for header, col_w in zip(headers, widths):
            self.set_xy(cursor, row_y)
            self.cell(col_w, 5, header, align="C" if header != "Opponent" else "L")
            cursor += col_w

        row_y += 7
        row_h = min(12.0, (panel_h - 16) / max(len(rows) or 1, 1))
        for index, row in enumerate(rows):
            if index % 2 == 0:
                self._fill(ROW_ALT)
                self.rect(MARGIN + 2, row_y, SLIDE_WIDTH_MM - (MARGIN * 2) - 4, row_h, style="F")
            values = [
                str(row.get("matchDay") or ""),
                str((row.get("opponent") or {}).get("name") or ""),
                str(row.get("venue") or ""),
                str(row.get("score") or "-"),
                _fmt(row.get("valeXg"), digits=2),
                _fmt(row.get("oppXg"), digits=2),
                _fmt(row.get("xgDiff"), digits=2),
                _fmt(row.get("valeHighQualityPct"), "pct"),
            ]
            cursor = MARGIN + 4
            for col_i, (value, col_w) in enumerate(zip(values, widths)):
                self.set_xy(cursor, row_y + 2.5)
                self.set_font("Helvetica", "B" if col_i == 1 else "", 8)
                self._text(TEXT)
                self.cell(col_w, 6, pdf_safe(value), align="C" if col_i != 1 else "L")
                cursor += col_w
            row_y += row_h

    def add_season_overview_slide(self, report: dict[str, Any]) -> None:
        averages = report.get("averages") or {}
        self.add_page()
        self._bg()
        top = self._toolbar(
            "xG Chance Analysis",
            f"{report.get('competition') or ''} {report.get('season') or ''}  |  Full season  |  "
            f"{report.get('matchCount') or 0} completed matches",
        )
        kpis = [
            ("Matches", _fmt(report.get("matchCount"), "int")),
            ("xG for /g", _fmt(averages.get("valeXg"), digits=2)),
            ("xG against /g", _fmt(averages.get("oppXg"), digits=2)),
            ("xG diff /g", _fmt(averages.get("xgDiff"), digits=2)),
            ("HQ share", _fmt(averages.get("valeHighQualityPct"), "pct")),
        ]
        card_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP * 4) / 5
        for i, (label, value) in enumerate(kpis):
            x = MARGIN + i * (card_w + GAP)
            self._card(x, top, card_w, 20, fill=SURFACE)
            self.set_xy(x + 2, top + 2.5)
            self.set_font("Helvetica", "", 6.5)
            self._text(MUTED)
            self.cell(card_w - 4, 4, pdf_safe(label.upper()), align="C")
            self.set_xy(x + 2, top + 8)
            self.set_font("Helvetica", "B", 12)
            self._text(TEXT)
            self.cell(card_w - 4, 8, pdf_safe(value), align="C")

        tables_y = top + 24
        tables_h = SLIDE_HEIGHT_MM - tables_y - MARGIN
        table_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP) / 2
        self._bucket_table(MARGIN, tables_y, table_w, tables_h, "Season xG created", report.get("xgCreated") or {})
        self._bucket_table(
            MARGIN + table_w + GAP,
            tables_y,
            table_w,
            tables_h,
            "Season xG against",
            report.get("xgAgainst") or {},
        )

    def add_season_players_slide(self, report: dict[str, Any]) -> None:
        self.add_page()
        self._bg()
        top = self._toolbar(
            "Season shot leaders",
            f"{report.get('competition') or ''} {report.get('season') or ''}  |  Top shooters by cumulative xG",
        )
        panel_w = (SLIDE_WIDTH_MM - (MARGIN * 2) - GAP) / 2
        panel_h = SLIDE_HEIGHT_MM - top - MARGIN
        players = report.get("playerBreakdown") or {}
        self._player_table(MARGIN, top, panel_w, panel_h, "Vale", players.get("vale") or {}, limit=11)
        self._player_table(MARGIN + panel_w + GAP, top, panel_w, panel_h, "Opposition", players.get("opp") or {}, limit=11)


def build_xg_chance_analysis_pdf(
    report: dict[str, Any],
    *,
    scope: str = "match",
) -> bytes:
    pdf = XgChanceAnalysisPDF()
    normalized = (scope or "match").strip().lower()
    if normalized == "last6":
        pdf.add_last6_overview_slide(report)
        pdf.add_last6_matches_slide(report)
    elif normalized == "season":
        pdf.add_season_overview_slide(report)
        pdf.add_season_players_slide(report)
    else:
        pdf.add_match_summary_slide(report)
        pdf.add_match_players_slide(report)

    output = pdf.output()
    if isinstance(output, (bytes, bytearray)):
        return bytes(output)
    return str(output).encode("latin-1")
