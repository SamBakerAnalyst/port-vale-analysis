"""Best-effort Google Sheets backup for LIVE/VIDEO fixture assignments.

Disabled until FIXTURE_SHEETS_ENABLED=1 and credentials + spreadsheet ID are set.
Assignment saves never fail because of Sheets errors.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

SHEET_HEADERS: tuple[str, ...] = (
    "Fixture ID",
    "Date",
    "Kickoff",
    "Season",
    "League",
    "Home",
    "Away",
    "Staff",
    "Watch",
    "Players",
    "Updated",
)

_lock = threading.Lock()
_last_status: dict[str, Any] = {
    "ok": True,
    "configured": False,
    "enabled": False,
    "reason": "not checked yet",
    "updated_at": None,
    "last_action": None,
    "last_error": None,
}


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name) or default).strip()


def sheets_backup_enabled() -> bool:
    return _env("FIXTURE_SHEETS_ENABLED", "0").lower() in {"1", "true", "yes", "on"}


def sheets_spreadsheet_id() -> str:
    return _env("FIXTURE_SHEETS_SPREADSHEET_ID")


def sheets_worksheet_name() -> str:
    return _env("FIXTURE_SHEETS_WORKSHEET", "Fixture backup") or "Fixture backup"


def _set_status(**kwargs: Any) -> dict[str, Any]:
    _last_status.update(kwargs)
    _last_status["updated_at"] = datetime.now(UTC).isoformat()
    return dict(_last_status)


def get_sheets_backup_status() -> dict[str, Any]:
    configured = bool(sheets_spreadsheet_id() and _service_account_info() is not None)
    enabled = sheets_backup_enabled()
    status = dict(_last_status)
    status["enabled"] = enabled
    status["configured"] = configured
    status["spreadsheet_id"] = sheets_spreadsheet_id() or None
    status["worksheet"] = sheets_worksheet_name()
    if not enabled:
        status["reason"] = "FIXTURE_SHEETS_ENABLED is off"
    elif not configured:
        status["reason"] = (
            "Set FIXTURE_SHEETS_SPREADSHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON "
            "(path or raw JSON), then share the sheet with the service account as Editor"
        )
    elif not status.get("reason"):
        status["reason"] = "ready"
    return status


def _service_account_info() -> dict[str, Any] | None:
    raw = _env("GOOGLE_SERVICE_ACCOUNT_JSON")
    if not raw:
        # Common alternate env names
        raw = _env("GOOGLE_SHEETS_CREDENTIALS_JSON") or _env("GOOGLE_APPLICATION_CREDENTIALS")
    if not raw:
        return None
    path = Path(raw)
    try:
        if path.exists() and path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
        if raw.lstrip().startswith("{"):
            return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Invalid Google service account JSON: %s", exc)
        return None
    return None


def _format_kickoff(kickoff_utc: Any, date_key: str = "") -> str:
    raw = str(kickoff_utc or "").strip()
    if not raw:
        return str(date_key or "").strip()
    try:
        # Accept Z or offset timestamps
        token = raw.replace("Z", "+00:00")
        dt = datetime.fromisoformat(token)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")
    except ValueError:
        return raw


def _staff_label(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple, set)):
        names: list[str] = []
        seen: set[str] = set()
        for item in value:
            name = str(item or "").strip()
            if not name:
                continue
            key = name.casefold()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
        return ", ".join(names)
    return str(value).strip()


def _players_label(rows: Any) -> str:
    names: list[str] = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("player_name") or row.get("name") or "").strip()
        if name:
            names.append(name)
    return ", ".join(names)


def assignment_should_backup(assignment: dict[str, Any] | None) -> bool:
    if not isinstance(assignment, dict) or not assignment:
        return False
    watch = str(assignment.get("watch_type") or "").strip().upper()
    if watch not in {"LIVE", "VIDEO"}:
        return False
    return bool(_staff_label(assignment.get("staff")))


def assignment_to_sheet_row(fixture_id: str, assignment: dict[str, Any]) -> list[str]:
    date_key = str(assignment.get("date") or "")[:10]
    return [
        str(fixture_id or "").strip(),
        date_key,
        _format_kickoff(assignment.get("kickoff_utc"), date_key),
        str(assignment.get("season") or "").strip(),
        str(assignment.get("league") or "").strip(),
        str(assignment.get("home") or "").strip(),
        str(assignment.get("away") or "").strip(),
        _staff_label(assignment.get("staff")),
        str(assignment.get("watch_type") or "").strip().upper(),
        _players_label(assignment.get("watched_players")),
        str(assignment.get("updated_at") or "").strip(),
    ]


def _open_worksheet():
    info = _service_account_info()
    spreadsheet_id = sheets_spreadsheet_id()
    if not info or not spreadsheet_id:
        raise RuntimeError("Google Sheets credentials or spreadsheet ID not configured")

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError(
            "gspread/google-auth not installed — add them to requirements.txt"
        ) from exc

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    credentials = Credentials.from_service_account_info(info, scopes=scopes)
    client = gspread.authorize(credentials)
    spreadsheet = client.open_by_key(spreadsheet_id)
    title = sheets_worksheet_name()
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(title=title, rows=2000, cols=len(SHEET_HEADERS))
        worksheet.append_row(list(SHEET_HEADERS), value_input_option="USER_ENTERED")
    values = worksheet.get_all_values()
    if not values:
        worksheet.append_row(list(SHEET_HEADERS), value_input_option="USER_ENTERED")
    elif [str(cell).strip() for cell in values[0]] != list(SHEET_HEADERS):
        # Keep existing sheet usable: rewrite header row if blank/mismatched first row.
        if not any(str(cell).strip() for cell in values[0]):
            worksheet.update(
                values=[list(SHEET_HEADERS)],
                range_name="A1",
                value_input_option="USER_ENTERED",
            )
        elif str(values[0][0]).strip().casefold() != "fixture id":
            worksheet.insert_row(list(SHEET_HEADERS), index=1, value_input_option="USER_ENTERED")
    return worksheet


def _find_row_index(worksheet, fixture_id: str) -> int | None:
    """1-based sheet row index for fixture_id in column A, or None."""
    needle = str(fixture_id or "").strip()
    if not needle:
        return None
    try:
        column = worksheet.col_values(1)
    except Exception:  # noqa: BLE001
        return None
    for index, value in enumerate(column):
        if index == 0:
            continue  # header
        if str(value or "").strip() == needle:
            return index + 1
    return None


def sync_assignment_to_sheet(fixture_id: str, assignment: dict[str, Any] | None) -> dict[str, Any]:
    """Upsert or remove one assignment row. Safe no-op when disabled/unconfigured."""
    if not sheets_backup_enabled():
        return _set_status(
            ok=True,
            configured=bool(sheets_spreadsheet_id() and _service_account_info()),
            enabled=False,
            reason="FIXTURE_SHEETS_ENABLED is off",
            last_action="skip",
            last_error=None,
        )

    if not sheets_spreadsheet_id() or _service_account_info() is None:
        return _set_status(
            ok=False,
            configured=False,
            enabled=True,
            reason="missing FIXTURE_SHEETS_SPREADSHEET_ID or GOOGLE_SERVICE_ACCOUNT_JSON",
            last_action="skip",
            last_error="not configured",
        )

    fixture_token = str(fixture_id or "").strip()
    if not fixture_token:
        return _set_status(ok=False, last_action="skip", last_error="missing fixture_id", reason="missing fixture_id")

    try:
        with _lock:
            worksheet = _open_worksheet()
            if not assignment_should_backup(assignment):
                row_index = _find_row_index(worksheet, fixture_token)
                if row_index and row_index > 1:
                    worksheet.delete_rows(row_index)
                return _set_status(
                    ok=True,
                    configured=True,
                    enabled=True,
                    reason="ready",
                    last_action="remove" if row_index else "noop",
                    last_error=None,
                )

            row = assignment_to_sheet_row(fixture_token, assignment or {})
            row_index = _find_row_index(worksheet, fixture_token)
            if row_index and row_index > 1:
                end_col = chr(ord("A") + len(SHEET_HEADERS) - 1)
                worksheet.update(
                    values=[row],
                    range_name=f"A{row_index}:{end_col}{row_index}",
                    value_input_option="USER_ENTERED",
                )
                action = "update"
            else:
                worksheet.append_row(row, value_input_option="USER_ENTERED")
                action = "append"
            return _set_status(
                ok=True,
                configured=True,
                enabled=True,
                reason="ready",
                last_action=action,
                last_error=None,
            )
    except Exception as exc:  # noqa: BLE001 - never break assignment saves
        logger.exception("Google Sheets backup failed for %s", fixture_token)
        return _set_status(
            ok=False,
            configured=True,
            enabled=True,
            reason="sheets sync failed",
            last_action="error",
            last_error=str(exc),
        )


def remove_assignment_from_sheet(fixture_id: str) -> dict[str, Any]:
    return sync_assignment_to_sheet(fixture_id, None)


def rebuild_sheet_from_assignments(assignments: dict[str, Any] | None = None) -> dict[str, Any]:
    """Replace worksheet contents with all LIVE/VIDEO assignments that have staff."""
    if not sheets_backup_enabled():
        return _set_status(
            ok=True,
            configured=bool(sheets_spreadsheet_id() and _service_account_info()),
            enabled=False,
            reason="FIXTURE_SHEETS_ENABLED is off",
            last_action="rebuild-skip",
            last_error=None,
        )

    if assignments is None:
        from app.fixture_planner import get_fixture_assignments

        assignments = get_fixture_assignments().get("assignments") or {}

    rows: list[list[str]] = [list(SHEET_HEADERS)]
    for fixture_id, assignment in sorted((assignments or {}).items(), key=lambda item: str(item[0])):
        if not isinstance(assignment, dict):
            continue
        if not assignment_should_backup(assignment):
            continue
        rows.append(assignment_to_sheet_row(str(fixture_id), assignment))

    try:
        with _lock:
            worksheet = _open_worksheet()
            worksheet.clear()
            worksheet.update(values=rows, range_name="A1", value_input_option="USER_ENTERED")
            return _set_status(
                ok=True,
                configured=True,
                enabled=True,
                reason="ready",
                last_action=f"rebuild:{len(rows) - 1}",
                last_error=None,
                row_count=len(rows) - 1,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("Google Sheets rebuild failed")
        return _set_status(
            ok=False,
            configured=True,
            enabled=True,
            reason="sheets rebuild failed",
            last_action="rebuild-error",
            last_error=str(exc),
        )
