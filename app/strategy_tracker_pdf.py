"""16:9 board pack for the Season Progress Report."""

from __future__ import annotations

from typing import Any

from fpdf import FPDF

from app.paths import PORT_VALE_BADGE
from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe

BG = (12, 15, 20)
PANEL = (20, 26, 34)
BORDER = (42, 53, 68)
TEXT = (232, 237, 244)
MUTED = (139, 155, 176)
GOLD = (245, 197, 24)
AHEAD = (52, 211, 153)
BEHIND = (248, 113, 113)
TRACK = (251, 191, 36)
AUTO = (61, 139, 253)
PLAYOFF = (148, 163, 184)
CHAMP = (52, 211, 153)
FRAME_INSET = 5.0
INNER_PAD = 8.0
ATTACK_IDS = {
    "defenders_bypassed",
    "ball_progression",
    "xg_for",
    "xg_diff",
    "offensive_interventions",
    "altered_threat",
    "packing_xg",
}
DEFEND_IDS = {
    "xg_against",
    "duel_rate",
    "defensive_interventions",
    "ball_wins_defenders",
    "defenders_bypassed_against",
}


def _fmt(value: Any, digits: int = 0) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return pdf_safe(str(value))
    if digits <= 0:
        return str(int(round(number)))
    return f"{number:.{digits}f}"


def _signed(value: Any, digits: int = 1) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    sign = "+" if number > 0 else ""
    return f"{sign}{number:.{digits}f}"


def _status_rgb(status: str) -> tuple[int, int, int]:
    if status == "ahead":
        return AHEAD
    if status == "behind":
        return BEHIND
    if status == "awaiting":
        return AUTO
    return TRACK


def _status_label(status: str, *, pack: bool = False) -> str:
    if status == "ahead":
        return "AHEAD OF TOP 7" if pack else "AHEAD OF AUTO"
    if status == "behind":
        return "BEHIND TOP 7" if pack else "BEHIND AUTO"
    if status == "awaiting":
        return "KICK-OFF READY"
    return "ON TRACK VS TOP 7" if pack else "ON TRACK VS AUTO"


def _metric(payload: dict[str, Any], metric_id: str) -> dict[str, Any]:
    for row in (payload.get("metrics") or []) + (payload.get("style_metrics") or []):
        if row.get("id") == metric_id:
            return row
    return {}


class SeasonProgressPDF(FPDF):
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

    def _frame(self) -> tuple[float, float, float, float]:
        self._fill(BG)
        self.rect(0, 0, SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM, style="F")
        x = FRAME_INSET
        y = FRAME_INSET
        width = SLIDE_WIDTH_MM - (FRAME_INSET * 2)
        height = SLIDE_HEIGHT_MM - (FRAME_INSET * 2)
        self._fill(PANEL)
        self._draw(GOLD)
        self.set_line_width(0.7)
        self.rect(x, y, width, height, style="DF")
        return x, y, width, height

    def _chrome(self, title: str, payload: dict[str, Any]) -> tuple[float, float, float, float]:
        frame_x, frame_y, frame_w, frame_h = self._frame()
        inner_x = frame_x + INNER_PAD
        inner_y = frame_y + INNER_PAD
        inner_w = frame_w - (INNER_PAD * 2)
        inner_h = frame_h - (INNER_PAD * 2)
        self.set_xy(inner_x, inner_y)
        self.set_font("Helvetica", "B", 9)
        self._text(GOLD)
        self.cell(inner_w * 0.55, 5, pdf_safe(str(payload.get("club") or "Port Vale")).upper())
        self.set_xy(inner_x + inner_w * 0.55, inner_y)
        self.set_font("Helvetica", "", 8)
        self._text(MUTED)
        self.cell(
            inner_w * 0.45,
            5,
            pdf_safe(f"{payload.get('competition') or ''}  |  {payload.get('season') or ''}"),
            align="R",
        )
        self.set_xy(inner_x, inner_y + 7)
        self.set_font("Helvetica", "B", 18)
        self._text(TEXT)
        self.cell(inner_w, 8, pdf_safe(title))
        return inner_x, inner_y + 18, inner_w, inner_h - 18

    def add_cover(self, payload: dict[str, Any]) -> None:
        self.add_page()
        frame_x, frame_y, frame_w, frame_h = self._frame()
        if PORT_VALE_BADGE.exists():
            self.image(str(PORT_VALE_BADGE), x=frame_x + frame_w / 2 - 9, y=frame_y + 28, w=18)
        self.set_xy(frame_x, frame_y + 58)
        self.set_font("Helvetica", "B", 11)
        self._text(GOLD)
        self.cell(frame_w, 6, "PORT VALE F.C.", align="C")
        self.set_xy(frame_x, frame_y + 70)
        self.set_font("Helvetica", "B", 28)
        self._text(TEXT)
        self.cell(frame_w, 14, "SEASON PROGRESS REPORT", align="C")
        self.set_xy(frame_x, frame_y + 88)
        self.set_font("Helvetica", "", 14)
        self._text(MUTED)
        self.cell(
            frame_w,
            8,
            pdf_safe(f"{payload.get('competition') or ''}  |  {payload.get('season') or ''}"),
            align="C",
        )
        self.set_xy(frame_x + 40, frame_y + 112)
        self.set_font("Helvetica", "", 11)
        self._text(TEXT)
        self.multi_cell(
            frame_w - 80,
            6,
            "Board pack: promotion pace, style numbers that win games, and the player board.",
            align="C",
        )
        self.set_xy(frame_x, frame_y + frame_h - 22)
        self.set_font("Helvetica", "", 9)
        self._text(MUTED)
        self.cell(frame_w, 5, "Present in the room  |  This PDF is the leave-behind", align="C")

    def add_headline(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, _h = self._chrome("Where we are", payload)
        summary = payload.get("summary") or {}
        status = str(summary.get("status") or "awaiting")
        self._fill(_status_rgb(status))
        self.rect(x, y, 62, 10, style="F")
        self.set_xy(x, y + 2)
        self.set_font("Helvetica", "B", 8)
        self._text((12, 15, 20) if status != "behind" else TEXT)
        self.cell(62, 6, _status_label(status), align="C")
        headline = (
            "Waiting for kick-off - auto target "
            f"{_fmt(summary.get('auto_target'), 1)} pts"
            if payload.get("kickoff_ready")
            else (
                f"Projected {_fmt(summary.get('projected_points'), 1)} pts   "
                f"auto {_fmt(summary.get('auto_target'), 1)}   "
                f"({_signed(summary.get('delta_vs_auto'))})"
            )
        )
        self.set_xy(x + 68, y)
        self.set_font("Helvetica", "B", 14)
        self._text(TEXT)
        self.cell(w - 68, 10, pdf_safe(headline))
        boxes = [
            ("PLAYED", _fmt(payload.get("played"))),
            ("POINTS", _fmt(_metric(payload, "points").get("current"))),
            ("SEASON PROJ.", "-" if payload.get("kickoff_ready") else _fmt(summary.get("projected_points"), 1)),
            ("POSITION", "-" if payload.get("position") is None else str(payload.get("position"))),
            ("AUTO", _fmt(summary.get("auto_target"), 1)),
            ("CHAMPIONS", _fmt(summary.get("champion_target"), 1)),
        ]
        box_w = (w - 10) / 6
        for i, (label, value) in enumerate(boxes):
            bx = x + i * (box_w + 2)
            by = y + 18
            self._fill(BG)
            self._draw(BORDER)
            self.set_line_width(0.3)
            self.rect(bx, by, box_w, 28, style="DF")
            self.set_xy(bx, by + 4)
            self.set_font("Helvetica", "B", 16)
            self._text(GOLD)
            self.cell(box_w, 10, pdf_safe(value), align="C")
            self.set_xy(bx, by + 16)
            self.set_font("Helvetica", "", 7)
            self._text(MUTED)
            self.cell(box_w, 6, label, align="C")
        remaining = payload.get("games_remaining")
        self.set_xy(x, y + 54)
        self.set_font("Helvetica", "", 11)
        self._text(TEXT)
        self.multi_cell(
            w,
            6,
            pdf_safe(
                f"{payload.get('played') or 0}/46 league games  |  "
                f"{remaining if remaining is not None else '-'} remaining  |  "
                "Dashed targets on the next slide are champions / auto / play-off averages."
            ),
        )

    def add_pace(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, h = self._chrome("Points pace", payload)
        series = payload.get("series") or []
        points = _metric(payload, "points")
        bench = (points.get("benchmarks") or {}) if points else {}
        chart_x, chart_y, chart_w, chart_h = x + 4, y + 4, w - 8, h - 18
        self._fill(BG)
        self.rect(chart_x, chart_y, chart_w, chart_h, style="F")
        y_max = max(
            100.0,
            float(bench.get("champion") or 0),
            float(bench.get("auto") or 0),
            float(points.get("projected") or 0),
            float((series[-1].get("points") if series else 0) or 0),
            1.0,
        ) * 1.08

        def px(game: float) -> float:
            return chart_x + 8 + (game / 46.0) * (chart_w - 16)

        def py(pts: float) -> float:
            return chart_y + chart_h - 10 - (pts / y_max) * (chart_h - 18)

        self.set_line_width(0.2)
        self._draw(BORDER)
        for game in range(0, 47, 5):
            self.line(px(game), chart_y + 4, px(game), chart_y + chart_h - 10)
        for pts in range(0, int(y_max) + 1, 20):
            self.line(px(0), py(pts), px(46), py(pts))

        def target(value: Any, color: tuple[int, int, int]) -> None:
            if value is None:
                return
            self._draw(color)
            self.set_line_width(0.5)
            self.set_dash_pattern(dash=1.8, gap=1.4)
            self.line(px(0), py(0), px(46), py(float(value)))
            self.set_dash_pattern(dash=0, gap=0)

        target(bench.get("playoff"), PLAYOFF)
        target(bench.get("auto"), AUTO)
        target(bench.get("champion"), CHAMP)
        if series:
            self._draw(GOLD)
            self.set_line_width(0.9)
            last = (px(0), py(0))
            for row in series:
                now = (px(float(row.get("played") or 0)), py(float(row.get("points") or 0)))
                self.line(last[0], last[1], now[0], now[1])
                last = now
        self.set_xy(x, y + h - 8)
        self.set_font("Helvetica", "", 8)
        self._text(MUTED)
        self.cell(w, 4, "Gold = Port Vale  |  Dashed = play-off / auto / champions", align="L")

    def add_scorecard(self, payload: dict[str, Any], *, title: str, metrics: list[dict[str, Any]]) -> None:
        self.add_page()
        x, y, w, h = self._chrome(title, payload)
        if not metrics:
            self.set_xy(x, y + 28)
            self.set_font("Helvetica", "", 12)
            self._text(MUTED)
            self.cell(w, 8, "No metrics for this slide yet.", align="C")
            return
        cols = 4
        rows = (len(metrics) + cols - 1) // cols
        gap = 3.0
        card_w = (w - gap * (cols - 1)) / cols
        card_h = min(42.0, (h - 4) / max(rows, 1) - gap)
        for i, metric in enumerate(metrics):
            col = i % cols
            row = i // cols
            cx = x + col * (card_w + gap)
            cy = y + row * (card_h + gap)
            status = str(metric.get("status") or "awaiting")
            self._fill(BG)
            self._draw(_status_rgb(status))
            self.set_line_width(0.4)
            self.rect(cx, cy, card_w, card_h, style="DF")
            self.set_xy(cx + 2, cy + 2)
            self.set_font("Helvetica", "B", 8)
            self._text(MUTED)
            self.cell(card_w - 4, 5, pdf_safe(str(metric.get("label") or "")).upper())
            digits = int(metric.get("digits") or 0)
            self.set_xy(cx + 2, cy + 10)
            self.set_font("Helvetica", "B", 16)
            self._text(TEXT)
            self.cell(card_w - 4, 9, _fmt(metric.get("current"), digits if digits else 0))
            self.set_xy(cx + 2, cy + 22)
            self.set_font("Helvetica", "B", 7)
            self._text(_status_rgb(status))
            pack = metric.get("benchmark_set") == "league_pack"
            self.cell(card_w - 4, 5, _status_label(status, pack=pack))
            self.set_xy(cx + 2, cy + 28)
            self.set_font("Helvetica", "", 7)
            self._text(MUTED)
            delta = metric.get("delta_vs_auto")
            self.cell(
                card_w - 4,
                5,
                "Waiting for kick-off" if status == "awaiting" else f"{_signed(delta)} vs target",
            )

    def add_goals(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, h = self._chrome("Goals by time", payload)
        times = payload.get("goal_times") or {}
        order = times.get("bucket_order") or []
        labels = times.get("bucket_labels") or {}
        scored = (times.get("for") or {}).get("buckets") or {}
        conceded = (times.get("against") or {}).get("buckets") or {}
        spot = payload.get("goal_spotlight") or {}
        if payload.get("kickoff_ready") or not order:
            self.set_xy(x, y + 30)
            self.set_font("Helvetica", "", 12)
            self._text(MUTED)
            self.cell(w, 8, "Timing splits unlock after the first league goal.", align="C")
            return
        chart_w, chart_h = w * 0.68, h - 8
        n = max(len(order), 1)
        group_w = chart_w / n
        max_val = max(
            1.0,
            max(float((scored.get(key) or {}).get("total") or 0) for key in order),
            max(float((conceded.get(key) or {}).get("total") or 0) for key in order),
        )
        bar_w = group_w * 0.32
        for i, key in enumerate(order):
            gf = float((scored.get(key) or {}).get("total") or 0)
            ga = float((conceded.get(key) or {}).get("total") or 0)
            cx = x + i * group_w + group_w / 2
            gf_h = (gf / max_val) * (chart_h - 14)
            ga_h = (ga / max_val) * (chart_h - 14)
            self._fill(GOLD)
            self.rect(cx - bar_w - 1, y + chart_h - 12 - gf_h, bar_w, max(gf_h, 0.4), style="F")
            self._fill(BEHIND)
            self.rect(cx + 1, y + chart_h - 12 - ga_h, bar_w, max(ga_h, 0.4), style="F")
            self.set_xy(cx - group_w / 2, y + chart_h - 10)
            self.set_font("Helvetica", "", 6)
            self._text(MUTED)
            self.cell(group_w, 4, pdf_safe(str(labels.get(key) or key)), align="C")
        side_x = x + w * 0.72
        lines = [
            f"Scored  {_fmt((times.get('for') or {}).get('total'))}",
            f"Conceded  {_fmt((times.get('against') or {}).get('total'))}",
            f"1H  {_fmt(spot.get('first_half_for'))} for / {_fmt(spot.get('first_half_against'))} against",
            f"2H  {_fmt(spot.get('second_half_for'))} for / {_fmt(spot.get('second_half_against'))} against",
        ]
        if spot.get("best_scoring"):
            best = spot["best_scoring"]
            lines.append(f"Best window  {best.get('label')} ({best.get('total')})")
        self.set_xy(side_x, y + 4)
        self.set_font("Helvetica", "", 10)
        self._text(TEXT)
        for line in lines:
            self.cell(w * 0.28, 7, pdf_safe(str(line)))
            self.set_xy(side_x, self.get_y() + 7)

    def add_players(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, h = self._chrome("Player board", payload)
        players = [
            row
            for row in (payload.get("players") or [])
            if float(row.get("minutes") or 0) >= 90
        ]
        players = sorted(players, key=lambda row: float(row.get("minutes") or 0), reverse=True)[:12]
        if not players:
            self.set_xy(x, y + 30)
            self.set_font("Helvetica", "", 12)
            self._text(MUTED)
            self.cell(w, 8, "Player board unlocks after the first league match (90+ minutes).", align="C")
            return
        headers = ["Player", "Pos", "Mins", "Def byp", "Prog", "xG", "Duel %", "OI", "DI", "PXT"]
        keys = [
            "name",
            "position_short",
            "minutes",
            "defenders_bypassed",
            "ball_progression",
            "xg_for",
            "duel_rate",
            "offensive_interventions",
            "defensive_interventions",
            "altered_threat",
        ]
        digits = {"minutes": 0, "xg_for": 1, "duel_rate": 1, "altered_threat": 1}
        col_w = [w * 0.22, w * 0.07, w * 0.08, w * 0.09, w * 0.08, w * 0.08, w * 0.09, w * 0.08, w * 0.08, w * 0.13]
        self.set_font("Helvetica", "B", 7)
        self._text(MUTED)
        cx = x
        for header, width in zip(headers, col_w, strict=True):
            self.set_xy(cx, y)
            self.cell(width, 6, header)
            cx += width
        row_h = min(9.5, (h - 8) / max(len(players), 1))
        for i, player in enumerate(players):
            cy = y + 7 + i * row_h
            if i % 2 == 0:
                self._fill(BG)
                self.rect(x, cy, w, row_h, style="F")
            cx = x
            for key, width in zip(keys, col_w, strict=True):
                self.set_xy(cx, cy + 1.5)
                self.set_font("Helvetica", "B" if key == "name" else "", 8)
                self._text(TEXT)
                value = player.get(key)
                if key == "name":
                    raw = str(value or "-")
                    text = pdf_safe(raw if len(raw) <= 22 else raw[:21] + ".")
                elif key == "position_short":
                    text = pdf_safe(str(value or "-"))
                else:
                    text = _fmt(value, digits.get(key, 0))
                self.cell(width, row_h - 2, text)
                cx += width

    def add_form(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, _h = self._chrome("Form and recent results", payload)
        form = payload.get("form") or []
        self.set_font("Helvetica", "B", 10)
        self._text(MUTED)
        self.set_xy(x, y)
        self.cell(w * 0.34, 6, "LAST SIX")
        if not form:
            self.set_xy(x, y + 10)
            self.set_font("Helvetica", "", 11)
            self._text(MUTED)
            self.cell(w * 0.34, 6, "Starts after game 1.")
        else:
            for i, result in enumerate(form):
                bx = x + i * 16
                color = AHEAD if result == "W" else BEHIND if result == "L" else PLAYOFF
                self._fill(color)
                self.rect(bx, y + 10, 13, 13, style="F")
                self.set_xy(bx, y + 13)
                self.set_font("Helvetica", "B", 10)
                self._text(BG)
                self.cell(13, 7, str(result), align="C")
        gf = _metric(payload, "goals_for").get("current")
        ga = _metric(payload, "goals_against").get("current")
        extras = [
            ("GOALS VS xG", f"{_fmt(gf)} scored  /  xG {_fmt(payload.get('xg_for'), 1)}"),
            ("CONCEDED VS xGA", f"{_fmt(ga)} against  /  xGA {_fmt(payload.get('xg_against'), 1)}"),
            ("PTS VS xPTS", _signed(payload.get("xp_vs_actual"))),
        ]
        box_w = (w * 0.62 - 4) / 3
        for i, (label, value) in enumerate(extras):
            bx = x + w * 0.38 + i * (box_w + 2)
            self._fill(BG)
            self._draw(BORDER)
            self.set_line_width(0.3)
            self.rect(bx, y, box_w, 24, style="DF")
            self.set_xy(bx + 2, y + 3)
            self.set_font("Helvetica", "B", 7)
            self._text(MUTED)
            self.cell(box_w - 4, 5, label)
            self.set_xy(bx + 2, y + 11)
            self.set_font("Helvetica", "B", 11)
            self._text(TEXT)
            self.cell(box_w - 4, 8, pdf_safe(value))
        series = list(reversed((payload.get("series") or [])[-8:]))
        self.set_xy(x, y + 32)
        self.set_font("Helvetica", "B", 10)
        self._text(MUTED)
        self.cell(w, 6, "RECENT LEAGUE RESULTS")
        if not series:
            self.set_xy(x, y + 42)
            self.set_font("Helvetica", "", 11)
            self._text(MUTED)
            self.cell(w, 6, "Results land here after kick-off.")
            return
        headers = ["#", "Date", "Opp", "V", "Score", "Pts", "GD"]
        widths = [18, 32, w - 18 - 32 - 18 - 28 - 22 - 22, 18, 28, 22, 22]
        self.set_font("Helvetica", "B", 7)
        self.set_xy(x, y + 40)
        for header, width in zip(headers, widths, strict=True):
            self.cell(width, 6, header)
        for i, row in enumerate(series):
            cy = y + 48 + i * 8
            self.set_font("Helvetica", "", 8)
            self._text(TEXT)
            values = [
                _fmt(row.get("played")),
                pdf_safe(str(row.get("date") or "-")),
                pdf_safe(str(row.get("opponent") or "-")),
                pdf_safe(f"{row.get('venue') or ''} {row.get('result') or ''}"),
                f"{row.get('scored', '-')} - {row.get('conceded', '-')}",
                _fmt(row.get("points")),
                _signed(row.get("goal_difference"), 0),
            ]
            cx = x
            for value, width in zip(values, widths, strict=True):
                self.set_xy(cx, cy)
                self.cell(width, 7, value)
                cx += width

    def add_close(self, payload: dict[str, Any]) -> None:
        self.add_page()
        x, y, w, _h = self._chrome("How we use this", payload)
        ahead = [
            row.get("label")
            for row in (payload.get("metrics") or []) + (payload.get("style_metrics") or [])
            if row.get("status") == "ahead"
        ][:4]
        behind = [
            row.get("label")
            for row in (payload.get("metrics") or []) + (payload.get("style_metrics") or [])
            if row.get("status") == "behind"
        ][:4]
        if payload.get("kickoff_ready"):
            body = (
                "Season not started. After each league game this pack updates: "
                "points pace vs auto, style numbers vs the top 7, and the player board."
            )
        else:
            keep = ", ".join(str(item) for item in ahead) or "the metrics already at promotion pace"
            fix = ", ".join(str(item) for item in behind) or "nothing currently behind the auto / top-7 line"
            body = f"Keep going: {keep}. Fix next: {fix}."
        self.set_xy(x, y + 8)
        self.set_font("Helvetica", "", 14)
        self._text(TEXT)
        self.multi_cell(w, 8, pdf_safe(body))
        self.set_xy(x, y + 70)
        self.set_font("Helvetica", "", 11)
        self._text(MUTED)
        self.multi_cell(
            w,
            6,
            "Present this deck in the room. Export PDF is the same story for the board pack.",
        )


def build_season_progress_pdf(payload: dict[str, Any]) -> bytes:
    pdf = SeasonProgressPDF()
    pdf.add_cover(payload)
    pdf.add_headline(payload)
    pdf.add_pace(payload)
    pdf.add_scorecard(payload, title="Outcome scorecard", metrics=payload.get("metrics") or [])
    pdf.add_goals(payload)
    style = payload.get("style_metrics") or []
    pdf.add_scorecard(
        payload,
        title="Attack - style that wins games",
        metrics=[row for row in style if row.get("id") in ATTACK_IDS],
    )
    pdf.add_scorecard(
        payload,
        title="Defend - style that wins games",
        metrics=[row for row in style if row.get("id") in DEFEND_IDS],
    )
    pdf.add_players(payload)
    pdf.add_form(payload)
    pdf.add_close(payload)
    return bytes(pdf.output())
