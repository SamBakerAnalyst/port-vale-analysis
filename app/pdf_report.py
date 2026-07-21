from __future__ import annotations

import base64
from datetime import datetime
from io import BytesIO
from typing import Any

from fpdf import FPDF

from app.label_utils import humanize_profile_name
from app.metric_bars import format_metric_value, format_percentile_label, percentile_colors

SLIDE_WIDTH_MM = 338.67
SLIDE_HEIGHT_MM = 190.5
PHOTO_PANEL_WIDTH_MM = 112.0


def pdf_safe(text: str) -> str:
    """Normalize text for Helvetica / WinAnsi (avoids FPDFUnicodeEncodingException)."""
    cleaned = (
        str(text or "")
        .replace("·", " - ")
        .replace("—", "-")
        .replace("–", "-")
        .replace("…", "...")
        .replace("★", "*")
        .replace("→", "->")
        .replace("←", "<-")
        .replace("≥", ">=")
        .replace("≤", "<=")
        .replace("×", "x")
        .replace("’", "'")
        .replace("‘", "'")
        .replace("“", '"')
        .replace("”", '"')
    )
    return cleaned.encode("latin-1", "replace").decode("latin-1")


def decode_image_data(data_url: str) -> bytes:
    payload = data_url.split(",", 1)[-1].strip()
    if not payload:
        raise ValueError("Chart image data is missing.")
    return base64.b64decode(payload)


class SlideDeckPDF(FPDF):
    """Full-bleed 16:9 widescreen pages (Keynote / PowerPoint dimensions)."""

    def __init__(self) -> None:
        # FPDF swaps (w, h) for orientation L — pass wide×tall with orientation P instead.
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.set_auto_page_break(auto=False)
        self.set_margins(0, 0, 0)
        self.set_display_mode(zoom="fullpage", layout="single")

    def add_full_bleed_image(self, image_data: str) -> None:
        self.add_page()
        self.image(
            BytesIO(decode_image_data(image_data)),
            x=0,
            y=0,
            w=self.w,
            h=self.h,
        )


class CoachSlidePDF(FPDF):
    MARGIN = 18.0
    NAVY = (15, 23, 42)
    SLATE = (30, 41, 59)
    MUTED = (100, 116, 139)
    ACCENT = (56, 189, 248)
    LIGHT = (241, 245, 249)
    WHITE = (255, 255, 255)

    def __init__(self, report_label: str) -> None:
        super().__init__(orientation="P", unit="mm", format=(SLIDE_WIDTH_MM, SLIDE_HEIGHT_MM))
        self.report_label = pdf_safe(report_label)
        self.set_auto_page_break(auto=False)
        self.set_margins(self.MARGIN, self.MARGIN, self.MARGIN)
        self.alias_nb_pages()

    @property
    def photo_panel_left(self) -> float:
        return self.w - PHOTO_PANEL_WIDTH_MM - self.MARGIN

    @property
    def left_panel_width(self) -> float:
        return self.photo_panel_left - self.MARGIN - 10

    def _fill(self, color: tuple[int, int, int]) -> None:
        self.set_fill_color(*color)

    def _rgb(self, color: tuple[int, int, int]) -> None:
        self.set_text_color(*color)

    def _draw(self, color: tuple[int, int, int]) -> None:
        self.set_draw_color(*color)

    def _draw_photo_panel(self, top: float, height: float, dark: bool = False) -> None:
        fill = (30, 41, 59) if dark else self.LIGHT
        border = (71, 85, 105) if dark else (226, 232, 240)
        self._fill(fill)
        self._draw(border)
        self.rect(self.photo_panel_left, top, PHOTO_PANEL_WIDTH_MM, height, style="DF")
        self.set_xy(self.photo_panel_left, top + (height / 2) - 4)
        self.set_font("Helvetica", "I", 11)
        self._rgb((148, 163, 184) if not dark else (203, 213, 225))
        self.cell(PHOTO_PANEL_WIDTH_MM, 8, "Player image", align="C")

    def _slide_background(self, dark: bool = False) -> None:
        if dark:
            self._fill(self.NAVY)
            self.rect(0, 0, self.w, self.h, style="F")
            self._fill(self.ACCENT)
            self.rect(0, self.h - 2.5, self.w, 2.5, style="F")
            return
        self._fill(self.LIGHT)
        self.rect(0, 0, self.w, self.h, style="F")

    def _draw_factor_bar_row(
        self,
        x: float,
        y: float,
        width: float,
        label: str,
        percentile: float | None,
        raw_value: float | None,
    ) -> None:
        label_w = 58.0
        badge_w = 16.0
        gap = 2.5
        track_w = max(width - label_w - badge_w - (gap * 2), 40.0)
        track_h = 7.0

        self.set_xy(x, y + 1.2)
        self.set_font("Helvetica", "", 11)
        self._rgb(self.MUTED)
        self.multi_cell(label_w, 4.5, pdf_safe(label))

        track_x = x + label_w + gap
        track_y = y + 0.8
        self._fill((232, 237, 244))
        self._draw((210, 218, 228))
        self.rect(track_x, track_y, track_w, track_h, style="DF")

        fill_color, badge_bg, badge_text = percentile_colors(percentile)
        if percentile is not None:
            fill_w = max(track_w * (percentile / 100.0), 10.0 if raw_value is not None else 0.0)
            self._fill(fill_color)
            self.rect(track_x, track_y, fill_w, track_h, style="F")
            if raw_value is not None:
                self.set_xy(track_x, track_y + 1.6)
                self.set_font("Helvetica", "B", 9)
                self._rgb(self.WHITE)
                self.cell(fill_w, 4, pdf_safe(format_metric_value(raw_value)), align="C")

        badge_x = track_x + track_w + gap
        self._fill(badge_bg)
        self._draw(badge_bg)
        self.rect(badge_x, track_y, badge_w, track_h, style="DF")
        self.set_xy(badge_x, track_y + 1.6)
        self.set_font("Helvetica", "B", 8)
        self._rgb(badge_text)
        self.cell(badge_w, 4, pdf_safe(format_percentile_label(percentile)), align="C")

    def _title_bar(self, title: str, subtitle: str = "") -> None:
        self._fill(self.NAVY)
        self.rect(0, 0, self.w, 24, style="F")
        self._fill(self.ACCENT)
        self.rect(0, 24, self.w, 1.5, style="F")
        self.set_xy(self.MARGIN, 7)
        self.set_font("Helvetica", "B", 22)
        self._rgb(self.WHITE)
        self.cell(self.left_panel_width, 10, pdf_safe(title))
        if subtitle:
            self.set_xy(self.MARGIN, 15)
            self.set_font("Helvetica", "", 11)
            self._rgb((203, 213, 225))
            self.cell(self.left_panel_width, 6, pdf_safe(subtitle))
        self.set_y(34)

    def add_cover_slide(self, body: Any) -> None:
        self.add_page()
        self._slide_background(dark=True)
        self._draw_photo_panel(18, self.h - 36, dark=True)

        self.set_xy(self.MARGIN, 22)
        self.set_font("Helvetica", "B", 12)
        self._rgb(self.ACCENT)
        self.cell(0, 6, "PORT VALE FC")

        primary = body.players[0] if body.players else None
        player_name = pdf_safe(primary.player if primary else "Player report")
        self.set_xy(self.MARGIN, 36)
        self.set_font("Helvetica", "B", 38)
        self._rgb(self.WHITE)
        self.multi_cell(self.left_panel_width, 15, player_name)

        y = self.get_y() + 4
        if primary:
            meta_parts = [part for part in [primary.season_label, primary.position_label] if part]
            if meta_parts:
                self.set_xy(self.MARGIN, y)
                self.set_font("Helvetica", "", 15)
                self._rgb((203, 213, 225))
                self.multi_cell(self.left_panel_width, 7, pdf_safe("  |  ".join(meta_parts)))
                y = self.get_y() + 4

        self.set_xy(self.MARGIN, y + 4)
        self.set_font("Helvetica", "", 12)
        self._rgb((148, 163, 184))
        if body.benchmark_subtitle:
            self.multi_cell(self.left_panel_width, 6.5, pdf_safe(body.benchmark_subtitle))
            y = self.get_y() + 2
        if body.profiles:
            self.set_xy(self.MARGIN, y)
            profile_labels = [humanize_profile_name(name) for name in body.profiles]
            self.multi_cell(self.left_panel_width, 6.5, pdf_safe("Profiles: " + ", ".join(profile_labels)))

        self.set_xy(self.MARGIN, self.h - 24)
        self.set_font("Helvetica", "", 10)
        self.cell(
            0,
            6,
            pdf_safe(f"Generated {body.generated_at or datetime.now().strftime('%d %b %Y, %H:%M')}"),
        )

    def add_chart_slide(self, title: str, subtitle: str, image_data: str) -> None:
        self.add_page()
        self._slide_background(dark=False)
        self._title_bar(title, subtitle)
        self._draw_photo_panel(34, self.h - 52)

        image_height = 122.0
        y = self.get_y() + 4
        self._draw((226, 232, 240))
        self._fill(self.WHITE)
        self.rect(self.MARGIN, y, self.left_panel_width, image_height, style="DF")
        self.image(
            BytesIO(decode_image_data(image_data)),
            x=self.MARGIN + 3,
            y=y + 3,
            w=self.left_panel_width - 6,
            h=image_height - 6,
        )

    def add_profile_slide(self, title: str, subtitle: str, image_data: str, entry: Any) -> None:
        self.add_page()
        self._slide_background(dark=False)
        self._title_bar(title, subtitle)
        self._draw_photo_panel(34, self.h - 52)

        factor_count = len(entry.labels or [])
        if factor_count > 6:
            chart_height = 66.0
        elif factor_count > 4:
            chart_height = 74.0
        else:
            chart_height = 92.0
        y = self.get_y() + 2
        self._draw((226, 232, 240))
        self._fill(self.WHITE)
        self.rect(self.MARGIN, y, self.left_panel_width, chart_height, style="DF")
        self.image(
            BytesIO(decode_image_data(image_data)),
            x=self.MARGIN + 3,
            y=y + 3,
            w=self.left_panel_width - 6,
            h=chart_height - 6,
        )
        y += chart_height + 6

        if not entry.labels or not entry.players:
            return

        players = entry.players or []
        row_height = 10.5
        multi_player = len(players) > 1
        cursor_y = y

        for index, label in enumerate(entry.labels):
            for player_index, compared in enumerate(players):
                percentile = (
                    compared.radar_values[index]
                    if index < len(compared.radar_values)
                    else None
                )
                raw_values = getattr(compared, "raw_values", None) or []
                raw_value = raw_values[index] if index < len(raw_values) else None
                if multi_player and player_index > 0:
                    row_label = f"  {compared.player.split(' ')[0]}"
                else:
                    row_label = label
                self._draw_factor_bar_row(
                    self.MARGIN,
                    cursor_y,
                    self.left_panel_width,
                    row_label,
                    percentile,
                    raw_value,
                )
                cursor_y += row_height


def build_whole_deck_pdf(body: Any) -> bytes:
    if not body.sections:
        raise ValueError("No chart images to export.")

    pdf = SlideDeckPDF()
    for section in body.sections:
        pdf.add_full_bleed_image(section.image_data)

    output = pdf.output()
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    return output.encode("latin-1")


def build_coach_report_pdf(body: Any) -> bytes:
    if not body.sections:
        raise ValueError("No chart images to export.")

    export_mode = getattr(body, "export_mode", "coach") or "coach"
    if export_mode == "whole":
        return build_whole_deck_pdf(body)

    primary_name = body.players[0].player if body.players else "Player report"
    pdf = CoachSlidePDF(primary_name)
    pdf.add_cover_slide(body)

    section_map = {section.title: section for section in body.sections}

    radar = section_map.get("Profile radar")
    if radar is not None:
        pdf.add_chart_slide(
            "Profile overview",
            "Percentile scores vs the cross-league benchmark cohort.",
            radar.image_data,
        )

    for entry in body.drilldowns:
        section = section_map.get(entry.profile)
        if section is None:
            continue
        subtitle = f"{len(entry.labels)} factors assessed"
        if len(entry.players) > 1:
            subtitle += f"  |  {len(entry.players)} players compared"
        pdf.add_profile_slide(
            humanize_profile_name(entry.profile),
            subtitle,
            section.image_data,
            entry,
        )

    pizza = section_map.get("Squad percentile pizza")
    if pizza is not None:
        pdf.add_chart_slide(
            "Squad percentile view",
            "Distribution view against the benchmark cohort.",
            pizza.image_data,
        )

    output = pdf.output()
    if isinstance(output, bytearray):
        return bytes(output)
    if isinstance(output, bytes):
        return output
    return output.encode("latin-1")
