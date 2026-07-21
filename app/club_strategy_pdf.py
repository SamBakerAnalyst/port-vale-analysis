from __future__ import annotations

from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.pdf_report import SLIDE_HEIGHT_MM, SLIDE_WIDTH_MM, pdf_safe

BG = (10, 10, 10)
PANEL = (17, 17, 17)
BORDER = (42, 42, 42)
TEXT = (245, 245, 245)
MUTED = (156, 163, 175)
GOLD = (245, 197, 24)
FOCUS = (245, 197, 24)
HEAT_GOOD = (22, 101, 52)
HEAT_MID = (133, 77, 14)
HEAT_BAD = (153, 27, 27)
ROW_ALT = (20, 20, 20)

FRAME_INSET = 5.0
INNER_PAD = 8.0


def _get(row: dict[str, Any], path: str) -> Any:
    cur: Any = row
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _fmt(value: Any, kind: str) -> str:
    if value is None:
        return "-"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return pdf_safe(str(value))
    if kind == "int":
        return str(int(round(number)))
    if kind == "dec":
        return f"{number:.2f}"
    if kind == "pct":
        return f"{number:.1f}%"
    if kind == "signed":
        rounded = f"{number:.2f}".rstrip("0").rstrip(".")
        return f"+{rounded}" if number > 0 else rounded
    return pdf_safe(str(value))


def _heat_rgb(
    value: Any,
    minimum: float,
    maximum: float,
    *,
    higher_better: bool = True,
) -> tuple[int, int, int] | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if maximum <= minimum:
        return None
    score = (number - minimum) / (maximum - minimum)
    if not higher_better:
        score = 1 - score
    if score >= 0.66:
        return HEAT_GOOD
    if score >= 0.33:
        return HEAT_MID
    return HEAT_BAD


class ClubStrategyPDF(FPDF):
    """16:9 Keynote / widescreen slide deck."""

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
        self.set_line_width(0.8)
        self.rect(x, y, width, height, style="DF")
        return x, y, width, height

    def add_title_slide(self, competition: str, season: str) -> None:
        self.add_page()
        frame_x, frame_y, frame_w, frame_h = self._frame()
        inner_x = frame_x + INNER_PAD
        inner_y = frame_y + INNER_PAD
        inner_w = frame_w - (INNER_PAD * 2)

        self.set_xy(inner_x, inner_y + 42)
        self.set_font("Helvetica", "B", 12)
        self._text(GOLD)
        self.cell(inner_w, 7, "PORT VALE F.C.", align="C")

        self.set_xy(inner_x, inner_y + 58)
        self.set_font("Helvetica", "B", 30)
        self._text(TEXT)
        self.cell(inner_w, 14, "CLUB STRATEGY", align="C")

        self.set_xy(inner_x, inner_y + 78)
        self.set_font("Helvetica", "", 14)
        self._text(MUTED)
        self.cell(
            inner_w,
            8,
            pdf_safe(f"{competition}  |  {season}"),
            align="C",
        )

        self.set_xy(inner_x, inner_y + 100)
        self.set_font("Helvetica", "", 11)
        self._text(MUTED)
        self.cell(
            inner_w,
            6,
            "League table, xG strategy, and first-goal outcomes",
            align="C",
        )

        footer_y = frame_y + frame_h - 18
        self.set_xy(inner_x, footer_y)
        self.set_font("Helvetica", "", 9)
        self._text(MUTED)
        self.cell(inner_w, 5, "Full deck export", align="C")

    def add_table_slide(
        self,
        *,
        title: str,
        subtitle: str,
        competition: str,
        season: str,
        columns: list[dict[str, Any]],
        rows: list[dict[str, Any]],
        averages: dict[str, Any] | None = None,
    ) -> None:
        self.add_page()
        frame_x, frame_y, frame_w, frame_h = self._frame()
        inner_x = frame_x + INNER_PAD
        inner_y = frame_y + INNER_PAD
        inner_w = frame_w - (INNER_PAD * 2)

        self.set_xy(inner_x, inner_y)
        self.set_font("Helvetica", "B", 9)
        self._text(GOLD)
        self.cell(inner_w * 0.55, 5, "PORT VALE F.C.")

        self.set_xy(inner_x + inner_w * 0.55, inner_y)
        self.set_font("Helvetica", "", 8)
        self._text(MUTED)
        self.cell(inner_w * 0.45, 5, pdf_safe(f"{competition}  |  {season}"), align="R")

        self.set_xy(inner_x, inner_y + 7)
        self.set_font("Helvetica", "B", 16)
        self._text(TEXT)
        self.cell(inner_w, 8, pdf_safe(title))

        self.set_xy(inner_x, inner_y + 15)
        self.set_font("Helvetica", "", 8)
        self._text(MUTED)
        self.cell(inner_w, 4, pdf_safe(subtitle))

        table_top = inner_y + 22
        table_bottom = frame_y + frame_h - INNER_PAD
        available_h = table_bottom - table_top
        needs_wrap = any("\n" in str(col.get("label") or "") for col in columns)
        header_h = 11.0 if needs_wrap else 7.0
        footer_h = 6.0 if averages else 0.0
        body_rows = len(rows)
        body_h = available_h - header_h - footer_h
        row_h = min(6.2, body_h / max(body_rows, 1))

        club_w = 34.0
        other_cols = [col for col in columns if col["key"] != "club"]
        other_w = (inner_w - club_w) / max(len(other_cols), 1)
        widths = {
            "club": club_w,
            **{col["key"]: other_w for col in other_cols},
        }

        heat_ranges: dict[str, tuple[float, float]] = {}
        for col in columns:
            if not col.get("heat"):
                continue
            values: list[float] = []
            for row in rows:
                raw = _get(row, col["key"]) if "." in col["key"] else row.get(col["key"])
                try:
                    values.append(float(raw))
                except (TypeError, ValueError):
                    continue
            if values:
                heat_ranges[col["key"]] = (min(values), max(values))

        # Header
        x = inner_x
        self._fill((31, 31, 31))
        self.rect(inner_x, table_top, inner_w, header_h, style="F")
        self.set_font("Helvetica", "B", 5.2 if needs_wrap else 5.5)
        self._text(MUTED)
        for col in columns:
            width = widths[col["key"]]
            label = pdf_safe(str(col["label"]))
            align = "L" if col["key"] == "club" else "C"
            if "\n" in label:
                self.set_xy(x, table_top + 0.8)
                self.multi_cell(width, 3.2, label, align=align)
            else:
                self.set_xy(x, table_top + (header_h - 4.5) / 2)
                self.cell(width, 4.5, label, align=align)
            x += width
            # multi_cell moves the cursor; keep absolute x for the next column
            self.set_xy(x, table_top)

        # Body
        y = table_top + header_h
        for index, row in enumerate(rows):
            focus = bool(row.get("focus"))
            fill = (28, 24, 8) if focus else (ROW_ALT if index % 2 else PANEL)
            self._fill(fill)
            self.rect(inner_x, y, inner_w, row_h, style="F")

            x = inner_x
            for col in columns:
                width = widths[col["key"]]
                raw = _get(row, col["key"]) if "." in col["key"] else row.get(col["key"])
                text = (
                    pdf_safe(str(raw or ""))
                    if col["key"] == "club"
                    else _fmt(raw, col.get("fmt", "int"))
                )
                heat = None
                if col.get("heat") and col["key"] in heat_ranges:
                    lo, hi = heat_ranges[col["key"]]
                    heat = _heat_rgb(
                        raw,
                        lo,
                        hi,
                        higher_better=col.get("higher_better", True),
                    )
                if heat is not None and col["key"] != "club":
                    self._fill(heat)
                    self.rect(x + 0.3, y + 0.35, width - 0.6, row_h - 0.7, style="F")
                    self._text(TEXT)
                else:
                    self._text(FOCUS if focus else TEXT)

                font_style = "B" if focus or col["key"] == "club" else ""
                self.set_font("Helvetica", font_style, 5.8 if col["key"] == "club" else 5.5)
                self.set_xy(x, y + (row_h - 3.8) / 2)
                align = "L" if col["key"] == "club" else "C"
                self.cell(width, 3.8, text, align=align)
                x += width
            y += row_h

        if averages:
            self._fill((24, 24, 24))
            self.rect(inner_x, y, inner_w, footer_h, style="F")
            x = inner_x
            self.set_font("Helvetica", "B", 5.5)
            self._text(TEXT)
            for col in columns:
                width = widths[col["key"]]
                if col["key"] == "club":
                    text = "AVERAGE"
                else:
                    raw = (
                        _get(averages, col["key"])
                        if "." in col["key"]
                        else averages.get(col["key"])
                    )
                    text = _fmt(raw, col.get("fmt", "int"))
                self.set_xy(x, y + 1)
                align = "L" if col["key"] == "club" else "C"
                self.cell(width, 4, text, align=align)
                x += width


def _standings_columns() -> list[dict[str, Any]]:
    return [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": "played", "label": "P", "fmt": "int"},
        {"key": "won", "label": "W", "fmt": "int", "heat": True},
        {"key": "drawn", "label": "D", "fmt": "int"},
        {"key": "lost", "label": "L", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "goals_for", "label": "GF", "fmt": "int", "heat": True},
        {"key": "goals_against", "label": "GA", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "goal_difference", "label": "GD", "fmt": "signed", "heat": True},
        {"key": "shots", "label": "Sh", "fmt": "int", "heat": True},
        {"key": "sot", "label": "SoT", "fmt": "int", "heat": True},
        {"key": "sot_pct", "label": "SoT%", "fmt": "pct", "heat": True},
        {"key": "clean_sheets", "label": "CS", "fmt": "int", "heat": True},
        {"key": "clean_sheet_pct", "label": "CS%", "fmt": "pct", "heat": True},
        {"key": "points", "label": "Pts", "fmt": "int", "heat": True},
        {"key": "ppg", "label": "PPG", "fmt": "dec", "heat": True},
        {"key": "ppg_x46", "label": "Proj", "fmt": "dec", "heat": True},
    ]


def _strategy_columns() -> list[dict[str, Any]]:
    return [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": "xg_for", "label": "xG for", "fmt": "dec", "heat": True},
        {"key": "xg_against", "label": "xGA", "fmt": "dec", "heat": True, "higher_better": False},
        {"key": "xg_difference", "label": "xGD", "fmt": "signed", "heat": True},
        {"key": "xpoints", "label": "xPts", "fmt": "dec", "heat": True},
        {"key": "xppg", "label": "xPPG", "fmt": "dec", "heat": True},
        {"key": "xppg_x46", "label": "xProj", "fmt": "dec", "heat": True},
        {"key": "xp_vs_actual", "label": "Pts-xPts", "fmt": "signed", "heat": True},
        {"key": "points", "label": "Pts", "fmt": "int", "heat": True},
    ]


def _first_goal_overview_columns() -> list[dict[str, Any]]:
    return [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": "fg_scored", "label": "Scored\nfirst", "fmt": "int", "heat": True},
        {"key": "nil_nil", "label": "Finished\n0-0", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "fg_conceded", "label": "Conceded\nfirst", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "fgs_ppg", "label": "PPG after\nscoring 1st", "fmt": "dec", "heat": True},
        {"key": "fgs_w_pct", "label": "Win % after\nscoring 1st", "fmt": "pct", "heat": True},
        {"key": "fgc_ppg", "label": "PPG after\nconceding 1st", "fmt": "dec", "heat": True},
        {"key": "fgc_w_pct", "label": "Win % after\nconceding 1st", "fmt": "pct", "heat": True},
    ]


def _first_goal_scored_columns() -> list[dict[str, Any]]:
    return [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": "fg_scored", "label": "Games\nscored 1st", "fmt": "int", "heat": True},
        {"key": "fgs_w", "label": "Won", "fmt": "int", "heat": True},
        {"key": "fgs_d", "label": "Drew", "fmt": "int"},
        {"key": "fgs_l", "label": "Lost", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "fgs_ppg", "label": "Points\nper game", "fmt": "dec", "heat": True},
        {"key": "fgs_w_pct", "label": "Win %", "fmt": "pct", "heat": True},
    ]


def _first_goal_conceded_columns() -> list[dict[str, Any]]:
    return [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": "fg_conceded", "label": "Games\nconceded 1st", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "fgc_w", "label": "Won", "fmt": "int", "heat": True},
        {"key": "fgc_d", "label": "Drew", "fmt": "int"},
        {"key": "fgc_l", "label": "Lost", "fmt": "int", "heat": True, "higher_better": False},
        {"key": "fgc_ppg", "label": "Points\nper game", "fmt": "dec", "heat": True},
        {"key": "fgc_w_pct", "label": "Win %", "fmt": "pct", "heat": True},
    ]


def _timing_columns(prefix: str, *, invert: bool = False) -> list[dict[str, Any]]:
    cols: list[dict[str, Any]] = [
        {"key": "position", "label": "Pos", "fmt": "int"},
        {"key": "club", "label": "Club", "fmt": "club"},
        {"key": f"{prefix}.total", "label": "Total", "fmt": "int"},
    ]
    for bucket, label in (
        ("0-15", "0-15\nmin"),
        ("16-30", "16-30\nmin"),
        ("31-45", "31-45\nmin"),
        ("45+", "1st half\nadded time"),
        ("45-60", "45-60\nmin"),
        ("61-75", "61-75\nmin"),
        ("76-90", "76-90\nmin"),
        ("90+", "2nd half\nadded time"),
        ("unknown", "Time\nunknown"),
    ):
        cols.append(
            {
                "key": f"{prefix}.buckets.{bucket}.total",
                "label": label,
                "fmt": "int",
                "heat": bucket != "unknown",
                "higher_better": not invert,
            }
        )
    return cols


def build_club_strategy_pdf(iteration_id: int) -> tuple[bytes, dict[str, Any]]:
    from app.club_strategy import build_club_strategy_report, build_first_goal_report

    report = build_club_strategy_report(iteration_id)
    first_goal = build_first_goal_report(iteration_id)
    standings = report.get("standings") or []
    if not standings:
        raise ValueError("No standings data available to export.")

    competition = str(report.get("competition") or "")
    season = str(report.get("season") or "")
    fg_rows = first_goal.get("rows") or []
    fg_avg = first_goal.get("averages") or {}

    pdf = ClubStrategyPDF()
    pdf.add_title_slide(competition, season)

    pdf.add_table_slide(
        title="League + Shooting",
        subtitle="League table with shots, shots on target, clean sheets, and season projections",
        competition=competition,
        season=season,
        columns=_standings_columns(),
        rows=standings,
        averages=report.get("averages") or {},
    )
    pdf.add_table_slide(
        title="Club Strategy (xG)",
        subtitle="Expected goals and points vs actual - green Pts vs xPts = over-performing",
        competition=competition,
        season=season,
        columns=_strategy_columns(),
        rows=standings,
        averages=report.get("averages") or {},
    )
    if fg_rows:
        pdf.add_table_slide(
            title="First Goal Outcomes - Overview",
            subtitle="How often each club scores or concedes the opening goal, and points earned after",
            competition=competition,
            season=season,
            columns=_first_goal_overview_columns(),
            rows=fg_rows,
            averages=fg_avg,
        )
        pdf.add_table_slide(
            title="When They Score First",
            subtitle="Result of the match after this club scores the opening goal",
            competition=competition,
            season=season,
            columns=_first_goal_scored_columns(),
            rows=fg_rows,
            averages=fg_avg,
        )
        pdf.add_table_slide(
            title="When They Concede First",
            subtitle="Result of the match after this club concedes the opening goal",
            competition=competition,
            season=season,
            columns=_first_goal_conceded_columns(),
            rows=fg_rows,
            averages=fg_avg,
        )
        pdf.add_table_slide(
            title="Goals Scored First - Times",
            subtitle="When the opening goal is scored by this club - by match period",
            competition=competition,
            season=season,
            columns=_timing_columns("fg_scored_times"),
            rows=fg_rows,
            averages=fg_avg,
        )
        pdf.add_table_slide(
            title="Goals Conceded First - Times",
            subtitle="When the opening goal is conceded by this club - green = less often",
            competition=competition,
            season=season,
            columns=_timing_columns("fg_conceded_times", invert=True),
            rows=fg_rows,
            averages=fg_avg,
        )

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue(), {
        "competition": competition,
        "season": season,
        "iteration_id": iteration_id,
    }
