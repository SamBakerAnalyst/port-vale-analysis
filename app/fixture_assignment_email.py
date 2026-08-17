from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
import smtplib
import ssl
import time
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from io import BytesIO
from typing import Any
from urllib.parse import quote

import requests

logger = logging.getLogger(__name__)

SCOUT_EMAILS: dict[str, str] = {
    "Lee Darnbrough": "Lee.darnbrough@port-vale.co.uk",
    "Tommy Johnson": "Tommy.johnson@port-vale.co.uk",
    "Martin Foyle": "Martin.Foyle@port-vale.co.uk",
    "Sam Baker": "sam.baker@port-vale.co.uk",
}

# Coaching addresses used for assignment emails + fortnight schedule updates.
COACHING_EMAILS: dict[str, str] = {
    "Jon Brady": "jon.brady@port-vale.co.uk",
    "Gary Mills": "Gary.mills@port-vale.co.uk",
    "Richard O'Donnell": "Richard.O'Donnell@port-vale.co.uk",
    "Jamie Smith": "jamie.smith@port-vale.co.uk",
    "Dan Watson": "Dan.watson@port-vale.co.uk",
}

# Admin addresses for ticket requests (overridable via FIXTURE_ADMIN_EMAILS).
DEFAULT_ADMIN_EMAILS: tuple[str, ...] = (
    "jack.mountford@port-vale.co.uk",
    "jess.frost@port-vale.co.uk",
)

DEFAULT_FROM_EMAIL = "sam.baker@port-vale.co.uk"
DEFAULT_FROM_NAME = "Sam Baker · Port Vale Recruitment"
DEFAULT_SMTP_HOST = "smtp.office365.com"
DEFAULT_SMTP_PORT = 587

_http = requests.Session()
_http.trust_env = False


def scout_email_for(staff: str) -> str | None:
    name = str(staff or "").strip()
    return SCOUT_EMAILS.get(name) or COACHING_EMAILS.get(name) or None


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def _parse_email_list(raw: str) -> list[str]:
    seen: set[str] = set()
    emails: list[str] = []
    for part in str(raw or "").replace(";", ",").split(","):
        email = part.strip()
        if not email or "@" not in email:
            continue
        key = email.casefold()
        if key in seen:
            continue
        seen.add(key)
        emails.append(email)
    return emails


def admin_team_emails() -> list[str]:
    configured = _parse_email_list(_env("FIXTURE_ADMIN_EMAILS"))
    if configured:
        return configured
    return list(DEFAULT_ADMIN_EMAILS)


def _pdf_safe_text(value: Any) -> str:
    """Helvetica core fonts are Latin-1; map common Unicode punctuation to ASCII."""
    text = str(value or "")
    replacements = {
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2018": "'",
        "\u2019": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u2022": "*",
        "\u00a0": " ",
        "\u2026": "...",
        "\u00b7": "-",
    }
    for src, dst in replacements.items():
        text = text.replace(src, dst)
    return text.encode("latin-1", errors="replace").decode("latin-1")


def schedule_update_emails() -> list[str]:
    configured = _parse_email_list(_env("FIXTURE_SCHEDULE_EMAILS"))
    if configured:
        return configured
    emails: list[str] = []
    seen: set[str] = set()
    for mapping in (SCOUT_EMAILS, COACHING_EMAILS):
        for value in mapping.values():
            email = str(value or "").strip()
            if not email or "@" not in email:
                continue
            key = email.casefold()
            if key in seen:
                continue
            seen.add(key)
            emails.append(email)
    return emails


def app_base_url() -> str:
    # Live hub is the only URL staff use — never default to localhost.
    return (_env("FIXTURE_APP_BASE_URL") or "http://178.128.161.215").rstrip("/")


def reject_notify_email() -> str:
    return (
        _env("FIXTURE_REJECT_NOTIFY_EMAIL")
        or _env("FIXTURE_EMAIL_FROM")
        or DEFAULT_FROM_EMAIL
    )


def _reject_secret() -> bytes:
    raw = _env("FIXTURE_REJECT_SECRET") or _env("SMTP_PASSWORD") or "fixture-planner-dev-secret"
    return raw.encode("utf-8")


def make_reject_token(*, fixture_id: str, staff: str, ttl_days: int = 45) -> str:
    exp = int(time.time()) + max(1, int(ttl_days)) * 86400
    payload = f"{fixture_id}\n{staff}\n{exp}"
    sig = hmac.new(_reject_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    raw = f"{payload}\n{sig}".encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def parse_reject_token(token: str) -> dict[str, Any] | None:
    raw = str(token or "").strip()
    if not raw:
        return None
    pad = "=" * (-len(raw) % 4)
    try:
        decoded = base64.urlsafe_b64decode(raw + pad).decode("utf-8")
    except Exception:
        return None
    parts = decoded.split("\n")
    if len(parts) != 4:
        return None
    fixture_id, staff, exp_raw, sig = parts
    try:
        exp = int(exp_raw)
    except ValueError:
        return None
    payload = f"{fixture_id}\n{staff}\n{exp}"
    expected = hmac.new(_reject_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, sig):
        return None
    if exp < int(time.time()):
        return None
    return {"fixture_id": fixture_id, "staff": staff, "exp": exp}


def build_reject_assignment_url(*, fixture_id: str, staff: str) -> str:
    token = make_reject_token(fixture_id=fixture_id, staff=staff)
    return f"{app_base_url()}/fixture-planner/reject-assignment?token={quote(token)}"


def smtp_configured() -> bool:
    return bool(_env("SMTP_PASSWORD") or _env("FIXTURE_EMAIL_PASSWORD"))


def email_configured() -> bool:
    return smtp_configured() or _resend_configured() or _graph_configured()


def _smtp_settings() -> dict[str, Any]:
    password = _env("SMTP_PASSWORD") or _env("FIXTURE_EMAIL_PASSWORD")
    user = _env("SMTP_USER") or _env("FIXTURE_EMAIL_FROM") or DEFAULT_FROM_EMAIL
    from_email = _env("FIXTURE_EMAIL_FROM") or DEFAULT_FROM_EMAIL
    return {
        "host": _env("SMTP_HOST") or DEFAULT_SMTP_HOST,
        "port": int(_env("SMTP_PORT") or DEFAULT_SMTP_PORT),
        "user": user,
        "password": password,
        "from_email": from_email,
        "from_name": _env("FIXTURE_EMAIL_FROM_NAME") or DEFAULT_FROM_NAME,
    }


def _email_transport_mode() -> str:
    mode = (_env("FIXTURE_EMAIL_TRANSPORT") or "auto").lower()
    return mode if mode in {"auto", "smtp", "graph", "resend"} else "auto"


def _resend_configured() -> bool:
    return bool(_env("RESEND_API_KEY"))


def _graph_configured() -> bool:
    return bool(
        _env("MS_GRAPH_TENANT_ID")
        and _env("MS_GRAPH_CLIENT_ID")
        and _env("MS_GRAPH_CLIENT_SECRET")
    )


def _choose_email_transport() -> str:
    mode = _email_transport_mode()
    if mode == "smtp":
        return "smtp"
    if mode == "resend":
        return "resend" if _resend_configured() else "smtp"
    if mode == "graph":
        return "graph" if _graph_configured() else "smtp"
    if _resend_configured():
        return "resend"
    if _graph_configured():
        return "graph"
    return "smtp"


def _smtp_network_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, ConnectionError)):
        return True
    if isinstance(exc, OSError) and getattr(exc, "errno", None) in {51, 61, 101, 111, 113}:
        return True
    text = str(exc).lower()
    return "network is unreachable" in text or "timed out" in text or "connection refused" in text


def _smtp_blocked_hint() -> str:
    return (
        "Mail server unreachable from the hub (hosting blocks SMTP ports). "
        "Set RESEND_API_KEY or Microsoft Graph credentials in .env — see .env.example."
    )


def _graph_access_token() -> str:
    tenant = _env("MS_GRAPH_TENANT_ID")
    response = _http.post(
        f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token",
        data={
            "client_id": _env("MS_GRAPH_CLIENT_ID"),
            "client_secret": _env("MS_GRAPH_CLIENT_SECRET"),
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials",
        },
        timeout=30,
    )
    if not response.ok:
        raise RuntimeError(f"Graph auth failed ({response.status_code}): {response.text[:240]}")
    token = response.json().get("access_token")
    if not token:
        raise RuntimeError("Graph auth returned no access token")
    return str(token)


def _send_via_resend(
    *,
    settings: dict[str, Any],
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    api_key = _env("RESEND_API_KEY")
    payload: dict[str, Any] = {
        "from": formataddr((settings["from_name"], settings["from_email"])),
        "to": to_emails,
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    attach_payload: list[dict[str, str]] = []
    for attachment in attachments or []:
        content = attachment.get("content")
        if not content:
            continue
        row: dict[str, str] = {
            "filename": str(attachment.get("filename") or "attachment.bin"),
            "content": base64.b64encode(content).decode("ascii"),
        }
        cid = str(attachment.get("cid") or "").strip()
        if cid:
            row["content_id"] = cid
        content_type = str(attachment.get("content_type") or "").strip()
        if content_type:
            row["content_type"] = content_type
        attach_payload.append(row)
    if attach_payload:
        payload["attachments"] = attach_payload

    response = _http.post(
        "https://api.resend.com/emails",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=45,
    )
    if not response.ok:
        detail = response.text[:240].replace("\n", " ")
        return {"sent": False, "reason": f"Resend API error ({response.status_code}): {detail}"}
    return {"sent": True, "to": to_emails, "transport": "resend"}


def _send_via_graph(
    *,
    settings: dict[str, Any],
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    token = _graph_access_token()
    send_as = _env("MS_GRAPH_SEND_AS") or settings["from_email"]
    graph_attachments: list[dict[str, Any]] = []
    for attachment in attachments or []:
        content = attachment.get("content")
        if not content:
            continue
        row: dict[str, Any] = {
            "@odata.type": "#microsoft.graph.fileAttachment",
            "name": str(attachment.get("filename") or "attachment.bin"),
            "contentType": str(attachment.get("content_type") or "application/octet-stream"),
            "contentBytes": base64.b64encode(content).decode("ascii"),
        }
        cid = str(attachment.get("cid") or "").strip()
        if cid:
            row["isInline"] = True
            row["contentId"] = cid
        graph_attachments.append(row)

    message: dict[str, Any] = {
        "subject": subject,
        "body": {"contentType": "HTML", "content": html_body or text_body},
        "toRecipients": [{"emailAddress": {"address": email}} for email in to_emails],
    }
    if graph_attachments:
        message["attachments"] = graph_attachments

    response = _http.post(
        f"https://graph.microsoft.com/v1.0/users/{quote(send_as)}/sendMail",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        json={"message": message, "saveToSentItems": True},
        timeout=45,
    )
    if not response.ok:
        detail = response.text[:240].replace("\n", " ")
        return {"sent": False, "reason": f"Microsoft Graph error ({response.status_code}): {detail}"}
    return {"sent": True, "to": to_emails, "transport": "graph"}


def _send_via_smtp(
    *,
    settings: dict[str, Any],
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not settings["password"]:
        return {
            "sent": False,
            "reason": "SMTP password not configured (set SMTP_PASSWORD in .env)",
        }

    root = MIMEMultipart("mixed")
    root["Subject"] = subject
    root["From"] = formataddr((settings["from_name"], settings["from_email"]))
    root["To"] = ", ".join(to_emails)
    root["Reply-To"] = settings["from_email"]

    alt = MIMEMultipart("alternative")
    root.attach(alt)
    alt.attach(MIMEText(text_body, "plain", "utf-8"))
    alt.attach(MIMEText(html_body, "html", "utf-8"))

    for attachment in attachments or []:
        payload = attachment.get("content")
        if not payload:
            continue
        filename = str(attachment.get("filename") or "attachment.bin")
        maintype = str(attachment.get("maintype") or "application")
        subtype = str(attachment.get("subtype") or "octet-stream")
        cid = str(attachment.get("cid") or "").strip()
        if maintype == "image" and cid:
            image = MIMEImage(payload, _subtype=subtype)
            image.add_header("Content-ID", f"<{cid}>")
            image.add_header("Content-Disposition", "inline", filename=filename)
            root.attach(image)
            continue
        from email.mime.base import MIMEBase
        from email import encoders

        part = MIMEBase(maintype, subtype)
        part.set_payload(payload)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", "attachment", filename=filename)
        root.attach(part)

    try:
        context = _ssl_context()
        with smtplib.SMTP(settings["host"], settings["port"], timeout=45) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(settings["user"], settings["password"])
            server.sendmail(settings["from_email"], to_emails, root.as_string())
    except Exception as exc:
        if _smtp_network_error(exc):
            return {"sent": False, "reason": _smtp_blocked_hint()}
        return {"sent": False, "reason": str(exc)}

    return {"sent": True, "to": to_emails, "transport": "smtp"}


def _send_email_payload(
    *,
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    recipients = _parse_email_list(",".join(to_emails))
    if not recipients:
        return {"sent": False, "reason": "No recipient email addresses configured"}

    settings = _smtp_settings()
    transport = _choose_email_transport()
    if transport == "resend":
        if not _resend_configured():
            return {"sent": False, "reason": "RESEND_API_KEY not configured"}
        return _send_via_resend(
            settings=settings,
            to_emails=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            attachments=attachments,
        )
    if transport == "graph":
        if not _graph_configured():
            return {"sent": False, "reason": "Microsoft Graph credentials not configured"}
        return _send_via_graph(
            settings=settings,
            to_emails=recipients,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
            attachments=attachments,
        )
    return _send_via_smtp(
        settings=settings,
        to_emails=recipients,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )


def _fotmob_badge_url(team_id: str | int | None) -> str | None:
    token = str(team_id or "").strip()
    if not token or not token.isdigit():
        return None
    return f"https://images.fotmob.com/image_resources/logo/teamlogo/{token}.png"


def team_badge_url(side: dict[str, Any] | None) -> str | None:
    side = side or {}
    image_url = str(side.get("image_url") or "").strip()
    if image_url.startswith("http"):
        return image_url
    fotmob_id = side.get("fotmob_id") or side.get("id")
    # Impect squad ids are large integers; FotMob team ids are typically smaller.
    # Prefer explicit fotmob_id when present.
    if side.get("fotmob_id"):
        return _fotmob_badge_url(side.get("fotmob_id"))
    if fotmob_id and str(fotmob_id).isdigit() and int(fotmob_id) < 1_000_000:
        return _fotmob_badge_url(fotmob_id)
    return None


def _download_image(url: str | None) -> bytes | None:
    token = str(url or "").strip()
    if not token.startswith("http"):
        return None
    try:
        response = _http.get(token, headers={"User-Agent": "Mozilla/5.0"}, timeout=12)
        if not response.ok or not response.content:
            return None
        content_type = str(response.headers.get("Content-Type") or "").lower()
        if "image" not in content_type and not token.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
            return None
        return response.content
    except requests.RequestException:
        logger.warning("Could not download badge image: %s", token)
        return None


def _format_kickoff(kickoff_utc: str | None, date_key: str | None = None) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo

    raw = str(kickoff_utc or "").strip()
    if raw:
        stamp = _kickoff_datetime(kickoff_utc, None)
        if stamp is not None:
            local = stamp.astimezone(ZoneInfo("Europe/London"))
            return local.strftime("%a %d %b %Y · %H:%M").replace(" 0", " ", 1)
    day = str(date_key or "").strip()[:10]
    if day:
        try:
            stamp = datetime.fromisoformat(f"{day}T12:00:00")
            return stamp.strftime("%a %d %b %Y · kick-off TBC").replace(" 0", " ", 1)
        except ValueError:
            return day
    return "Date / kick-off TBC"


def _kickoff_datetime(kickoff_utc: str | None, date_key: str | None = None):
    from datetime import datetime, timezone
    from zoneinfo import ZoneInfo

    raw = str(kickoff_utc or "").strip()
    if raw:
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                stamp = stamp.replace(tzinfo=timezone.utc)
            return stamp
        except ValueError:
            pass
    day = str(date_key or "").strip()[:10]
    if day:
        try:
            # Unknown kick-off — assume 15:00 UK for calendar placeholder.
            return datetime.fromisoformat(f"{day}T15:00:00").replace(
                tzinfo=ZoneInfo("Europe/London")
            )
        except ValueError:
            return None
    return None


def _assignment_event_times(
    kickoff_utc: str | None,
    date_key: str | None = None,
):
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    start = _kickoff_datetime(kickoff_utc, date_key)
    if start is None:
        return None, None
    local_start = start.astimezone(ZoneInfo("Europe/London"))
    local_end = local_start + timedelta(hours=2, minutes=30)
    return local_start, local_end


def _ics_escape(text: str) -> str:
    return (
        str(text or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\n", "\\n")
    )


def build_assignment_ics(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_utc: str | None,
    date_key: str | None,
    venue: str,
    watched_players: list[dict[str, Any]] | None = None,
    fixture_id: str = "",
) -> str | None:
    start, end = _assignment_event_times(kickoff_utc, date_key)
    if start is None or end is None:
        return None

    from datetime import datetime, timezone

    watch = (watch_type or "LIVE").upper()
    title = f"Scouting · {watch} · {home} vs {away}"
    players = watched_players or []
    player_lines = []
    for row in players:
        name = str(row.get("player_name") or "").strip()
        if name:
            player_lines.append(f"- {name}")
    description_parts = [
        f"Coverage: {watch}",
        f"Competition: {league or 'Fixture'}",
        f"Assigned to: {staff}",
    ]
    if player_lines:
        description_parts.append("Players to watch:")
        description_parts.extend(player_lines)
    else:
        description_parts.append("Players to watch: full game")
    description_parts.append("Port Vale Fixture Planner")

    uid_src = f"{fixture_id}|{staff}|{home}|{away}|{start.isoformat()}"
    uid = hashlib.sha1(uid_src.encode("utf-8")).hexdigest() + "@port-vale.co.uk"
    now = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dt_start = start.strftime("%Y%m%dT%H%M%S")
    dt_end = end.strftime("%Y%m%dT%H%M%S")

    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Port Vale FC//Fixture Planner//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VTIMEZONE",
        "TZID:Europe/London",
        "X-LIC-LOCATION:Europe/London",
        "BEGIN:DAYLIGHT",
        "TZOFFSETFROM:+0000",
        "TZOFFSETTO:+0100",
        "TZNAME:BST",
        "DTSTART:19700329T010000",
        "RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU",
        "END:DAYLIGHT",
        "BEGIN:STANDARD",
        "TZOFFSETFROM:+0100",
        "TZOFFSETTO:+0000",
        "TZNAME:GMT",
        "DTSTART:19701025T020000",
        "RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU",
        "END:STANDARD",
        "END:VTIMEZONE",
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"DTSTAMP:{now}",
        f"DTSTART;TZID=Europe/London:{dt_start}",
        f"DTEND;TZID=Europe/London:{dt_end}",
        f"SUMMARY:{_ics_escape(title)}",
        f"LOCATION:{_ics_escape(venue or f'{home} (home)')}",
        f"DESCRIPTION:{_ics_escape(chr(10).join(description_parts))}",
        "END:VEVENT",
        "END:VCALENDAR",
        "",
    ]
    return "\r\n".join(lines)


def build_outlook_calendar_url(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_utc: str | None,
    date_key: str | None,
    venue: str,
    watched_players: list[dict[str, Any]] | None = None,
) -> str | None:
    start, end = _assignment_event_times(kickoff_utc, date_key)
    if start is None or end is None:
        return None

    watch = (watch_type or "LIVE").upper()
    subject = f"Scouting · {watch} · {home} vs {away}"
    players = watched_players or []
    player_bits = [
        str(row.get("player_name") or "").strip()
        for row in players
        if str(row.get("player_name") or "").strip()
    ]
    body_lines = [
        f"Coverage: {watch}",
        f"Competition: {league or 'Fixture'}",
        f"Assigned to: {staff}",
        f"Venue: {venue or f'{home} (home)'}",
    ]
    if player_bits:
        body_lines.append("Players to watch: " + ", ".join(player_bits))
    else:
        body_lines.append("Players to watch: full game")
    body_lines.append("Port Vale Fixture Planner")

    from urllib.parse import urlencode

    params = {
        "path": "/calendar/action/compose",
        "rru": "addevent",
        "subject": subject,
        "body": "\n".join(body_lines),
        "location": venue or f"{home} (home)",
        "startdt": start.strftime("%Y-%m-%dT%H:%M:%S"),
        "enddt": end.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    return "https://outlook.office.com/calendar/0/deeplink/compose?" + urlencode(params)


def _escape(text: str) -> str:
    return (
        str(text or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_assignment_email_html(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_label: str,
    venue: str,
    home_cid: str | None,
    away_cid: str | None,
    watched_players: list[dict[str, Any]] | None = None,
    reject_url: str = "",
    outlook_url: str = "",
) -> str:
    watch = (watch_type or "LIVE").upper()
    watch_color = "#34d399" if watch == "LIVE" else "#fbbf24"
    home_badge = (
        f'<img src="cid:{home_cid}" alt="{_escape(home)}" width="72" height="72" '
        f'style="display:block;width:72px;height:72px;object-fit:contain;margin:0 auto;" />'
        if home_cid
        else '<div style="width:72px;height:72px;border-radius:50%;background:#1e293b;margin:0 auto;"></div>'
    )
    away_badge = (
        f'<img src="cid:{away_cid}" alt="{_escape(away)}" width="72" height="72" '
        f'style="display:block;width:72px;height:72px;object-fit:contain;margin:0 auto;" />'
        if away_cid
        else '<div style="width:72px;height:72px;border-radius:50%;background:#1e293b;margin:0 auto;"></div>'
    )

    players = watched_players or []
    if players:
        home_targets = [p for p in players if str(p.get("side") or "").lower() == "home"]
        away_targets = [p for p in players if str(p.get("side") or "").lower() == "away"]
        other_targets = [
            p
            for p in players
            if str(p.get("side") or "").lower() not in {"home", "away"}
        ]

        def _player_list(rows: list[dict[str, Any]], title: str) -> str:
            if not rows:
                return ""
            items = "".join(
                f'<li style="margin:0 0 4px;color:#e2e8f0;">{_escape(str(row.get("player_name") or "Player"))}</li>'
                for row in rows
            )
            return (
                f'<div style="margin-top:10px;">'
                f'<div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;">{_escape(title)}</div>'
                f'<ul style="margin:6px 0 0;padding-left:18px;">{items}</ul></div>'
            )

        players_block = f"""
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0f172a;border:1px solid #1f2937;border-radius:12px;margin-top:12px;">
                <tr>
                  <td style="padding:14px 16px;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#f5c518;">Players to watch</div>
                    {_player_list(home_targets, home or "Home")}
                    {_player_list(away_targets, away or "Away")}
                    {_player_list(other_targets, "Targets")}
                  </td>
                </tr>
              </table>
        """
    else:
        players_block = """
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0f172a;border:1px solid #1f2937;border-radius:12px;margin-top:12px;">
                <tr>
                  <td style="padding:14px 16px;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#f5c518;">Players to watch</div>
                    <div style="font-size:14px;color:#94a3b8;margin-top:6px;">No specific players selected — full game watch.</div>
                  </td>
                </tr>
              </table>
        """

    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /></head>
<body style="margin:0;padding:0;background:#0b1220;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1220;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="560" cellspacing="0" cellpadding="0" style="max-width:560px;background:#111827;border:1px solid #1f2937;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="padding:20px 24px;background:#0f172a;border-bottom:1px solid #1f2937;">
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#f5c518;font-weight:700;">Port Vale F.C. · Recruitment</div>
              <div style="font-size:22px;font-weight:700;color:#f8fafc;margin-top:6px;">You've been assigned a game</div>
              <div style="font-size:14px;color:#94a3b8;margin-top:4px;">Hi {_escape(staff.split(' ')[0])}, here's your next scouting fixture.</div>
            </td>
          </tr>
          <tr>
            <td style="padding:28px 24px 12px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0">
                <tr>
                  <td width="38%" align="center" style="vertical-align:middle;">
                    {home_badge}
                    <div style="font-size:14px;font-weight:700;color:#f8fafc;margin-top:10px;">{_escape(home)}</div>
                  </td>
                  <td width="24%" align="center" style="vertical-align:middle;">
                    <div style="font-size:18px;font-weight:700;color:#64748b;">VS</div>
                    <div style="display:inline-block;margin-top:10px;padding:4px 10px;border-radius:999px;background:{watch_color};color:#0f172a;font-size:11px;font-weight:700;letter-spacing:.04em;">{_escape(watch)}</div>
                  </td>
                  <td width="38%" align="center" style="vertical-align:middle;">
                    {away_badge}
                    <div style="font-size:14px;font-weight:700;color:#f8fafc;margin-top:10px;">{_escape(away)}</div>
                  </td>
                </tr>
              </table>
            </td>
          </tr>
          <tr>
            <td style="padding:8px 24px 28px;">
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0f172a;border:1px solid #1f2937;border-radius:12px;">
                <tr>
                  <td style="padding:14px 16px;border-bottom:1px solid #1f2937;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;">Kick-off</div>
                    <div style="font-size:16px;font-weight:700;color:#f8fafc;margin-top:4px;">{_escape(kickoff_label)}</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;border-bottom:1px solid #1f2937;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;">Venue</div>
                    <div style="font-size:16px;font-weight:700;color:#f8fafc;margin-top:4px;">{_escape(venue)}</div>
                  </td>
                </tr>
                <tr>
                  <td style="padding:14px 16px;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;">Competition</div>
                    <div style="font-size:16px;font-weight:700;color:#f8fafc;margin-top:4px;">{_escape(league or "Fixture")}</div>
                  </td>
                </tr>
              </table>
              {players_block}
              {f'''
              <div style="margin-top:18px;text-align:center;">
                <a href="{_escape(outlook_url)}" style="display:inline-block;padding:12px 18px;border-radius:10px;background:#2563eb;color:#eff6ff;text-decoration:none;font-size:14px;font-weight:700;">
                  Add to Outlook calendar
                </a>
                <div style="font-size:12px;color:#64748b;margin-top:8px;">Opens Outlook with this fixture ready to save · an .ics file is also attached.</div>
              </div>
              ''' if outlook_url else ''}
              {f'''
              <div style="margin-top:18px;text-align:center;">
                <a href="{_escape(reject_url)}" style="display:inline-block;padding:12px 18px;border-radius:10px;background:#7f1d1d;color:#fecaca;text-decoration:none;font-size:14px;font-weight:700;">
                  Can't cover — reject this game
                </a>
                <div style="font-size:12px;color:#64748b;margin-top:8px;">This removes you from the fixture and emails Sam.</div>
              </div>
              ''' if reject_url else ''}
              <p style="font-size:13px;line-height:1.5;color:#94a3b8;margin:18px 0 0;">
                Assigned by Sam Baker via the Fixture Planner. Reply to this email if you need to swap, or use the reject button above if you can't cover.
              </p>
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def build_assignment_email_text(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_label: str,
    venue: str,
    watched_players: list[dict[str, Any]] | None = None,
    reject_url: str = "",
    outlook_url: str = "",
) -> str:
    lines = [
        f"Hi {staff.split(' ')[0]},",
        "",
        "You've been assigned a scouting fixture:",
        "",
        f"{home} vs {away}",
        f"Competition: {league or 'Fixture'}",
        f"Coverage: {(watch_type or 'LIVE').upper()}",
        f"Kick-off: {kickoff_label}",
        f"Venue: {venue}",
        "",
        "Players to watch:",
    ]
    players = watched_players or []
    if not players:
        lines.append("- No specific players selected (full game watch)")
    else:
        for row in players:
            team = str(row.get("team") or "").strip()
            name = str(row.get("player_name") or "Player").strip()
            lines.append(f"- {name}" + (f" ({team})" if team else ""))
    if outlook_url:
        lines.extend(
            [
                "",
                "Add to Outlook calendar:",
                outlook_url,
                "(An .ics calendar file is also attached to this email.)",
            ]
        )
    if reject_url:
        lines.extend(
            [
                "",
                "Can't cover this game? Reject it here (removes you and emails Sam):",
                reject_url,
            ]
        )
    lines.extend(["", "Assigned by Sam Baker via the Fixture Planner."])
    return "\n".join(lines)


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi

        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def send_assignment_email(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_utc: str | None,
    date_key: str | None,
    venue: str,
    home_badge_url: str | None,
    away_badge_url: str | None,
    watched_players: list[dict[str, Any]] | None = None,
    fixture_id: str = "",
) -> dict[str, Any]:
    to_email = scout_email_for(staff)
    if not to_email:
        return {"sent": False, "reason": f"No email configured for {staff}"}

    if not email_configured():
        return {
            "sent": False,
            "reason": "Email not configured (set SMTP, RESEND_API_KEY, or Microsoft Graph in .env)",
        }

    kickoff_label = _format_kickoff(kickoff_utc, date_key)
    venue_label = venue or (f"{home} (home)" if home else "Venue TBC")
    targets = watched_players or []
    reject_url = ""
    if fixture_id and staff:
        reject_url = build_reject_assignment_url(fixture_id=fixture_id, staff=staff)
    outlook_url = build_outlook_calendar_url(
        staff=staff,
        home=home,
        away=away,
        league=league,
        watch_type=watch_type,
        kickoff_utc=kickoff_utc,
        date_key=date_key,
        venue=venue_label,
        watched_players=targets,
    )
    ics_body = build_assignment_ics(
        staff=staff,
        home=home,
        away=away,
        league=league,
        watch_type=watch_type,
        kickoff_utc=kickoff_utc,
        date_key=date_key,
        venue=venue_label,
        watched_players=targets,
        fixture_id=fixture_id,
    )

    home_bytes = _download_image(home_badge_url)
    away_bytes = _download_image(away_badge_url)
    home_cid = make_msgid(domain="port-vale.co.uk")[1:-1] if home_bytes else None
    away_cid = make_msgid(domain="port-vale.co.uk")[1:-1] if away_bytes else None

    attachments: list[dict[str, Any]] = []
    if home_bytes and home_cid:
        attachments.append(
            {
                "filename": "home-badge.png",
                "content": home_bytes,
                "maintype": "image",
                "subtype": "png",
                "cid": home_cid,
                "content_type": "image/png",
            }
        )
    if away_bytes and away_cid:
        attachments.append(
            {
                "filename": "away-badge.png",
                "content": away_bytes,
                "maintype": "image",
                "subtype": "png",
                "cid": away_cid,
                "content_type": "image/png",
            }
        )
    if ics_body:
        attachments.append(
            {
                "filename": "scouting-assignment.ics",
                "content": ics_body.encode("utf-8"),
                "maintype": "text",
                "subtype": "calendar",
                "content_type": "text/calendar",
            }
        )

    result = _send_email_payload(
        to_emails=[to_email],
        subject=f"Scouting assignment · {home} vs {away}",
        text_body=build_assignment_email_text(
            staff=staff,
            home=home,
            away=away,
            league=league,
            watch_type=watch_type,
            kickoff_label=kickoff_label,
            venue=venue_label,
            watched_players=targets,
            reject_url=reject_url,
            outlook_url=outlook_url or "",
        ),
        html_body=build_assignment_email_html(
            staff=staff,
            home=home,
            away=away,
            league=league,
            watch_type=watch_type,
            kickoff_label=kickoff_label,
            venue=venue_label,
            home_cid=home_cid,
            away_cid=away_cid,
            watched_players=targets,
            reject_url=reject_url,
            outlook_url=outlook_url or "",
        ),
        attachments=attachments,
    )
    if result.get("sent"):
        logger.info("Assignment email sent to %s for %s vs %s", to_email, home, away)
        result["reject_url"] = reject_url or None
        result["outlook_url"] = outlook_url or None
        result["ics_attached"] = bool(ics_body)
    return result


def send_rejection_notify_email(
    *,
    staff: str,
    home: str,
    away: str,
    league: str,
    watch_type: str,
    kickoff_label: str,
    reason: str = "",
    scout_email: str | None = None,
) -> dict[str, Any]:
    to_email = reject_notify_email()
    if not to_email:
        return {"sent": False, "reason": "No reject notify email configured"}

    if not email_configured():
        return {
            "sent": False,
            "reason": "Email not configured (set SMTP, RESEND_API_KEY, or Microsoft Graph in .env)",
        }

    first = staff.split(" ")[0] if staff else "Scout"
    subject = f"Fixture rejected · {staff} · {home} vs {away}"
    reason_clean = str(reason or "").strip()
    reason_block = reason_clean or "(no reason given)"
    scout_line = scout_email or scout_email_for(staff) or "—"

    text = "\n".join(
        [
            f"{staff} rejected their scouting assignment.",
            "",
            f"Match: {home} vs {away}",
            f"Competition: {league or 'Fixture'}",
            f"Coverage: {(watch_type or 'LIVE').upper()}",
            f"Kick-off: {kickoff_label or 'TBC'}",
            f"Scout email: {scout_line}",
            "",
            "Reason:",
            reason_block,
            "",
            "They have been removed from this fixture in the Fixture Planner.",
        ]
    )
    html = f"""<!DOCTYPE html>
<html>
<body style="margin:0;padding:24px;background:#0f172a;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;color:#e2e8f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="max-width:560px;margin:0 auto;background:#111827;border-radius:14px;border:1px solid #1f2937;">
    <tr>
      <td style="padding:22px 24px;">
        <div style="font-size:12px;letter-spacing:0.08em;text-transform:uppercase;color:#f87171;font-weight:700;">Assignment rejected</div>
        <h1 style="margin:10px 0 6px;font-size:22px;color:#f8fafc;">{_escape(staff)} can't cover</h1>
        <p style="margin:0 0 16px;color:#94a3b8;font-size:14px;">{_escape(home)} vs {_escape(away)}</p>
        <div style="font-size:14px;line-height:1.55;color:#cbd5e1;">
          <div><strong style="color:#f8fafc;">Competition:</strong> {_escape(league or "Fixture")}</div>
          <div><strong style="color:#f8fafc;">Coverage:</strong> {_escape((watch_type or "LIVE").upper())}</div>
          <div><strong style="color:#f8fafc;">Kick-off:</strong> {_escape(kickoff_label or "TBC")}</div>
          <div><strong style="color:#f8fafc;">Scout email:</strong> {_escape(scout_line)}</div>
        </div>
        <div style="margin-top:16px;padding:14px 16px;border-radius:10px;background:#1f2937;border:1px solid #374151;">
          <div style="font-size:12px;color:#94a3b8;margin-bottom:6px;">Reason from {_escape(first)}</div>
          <div style="font-size:14px;color:#f8fafc;white-space:pre-wrap;">{_escape(reason_block)}</div>
        </div>
        <p style="margin:16px 0 0;font-size:13px;color:#94a3b8;">
          They have been removed from this fixture in the Fixture Planner.
        </p>
      </td>
    </tr>
  </table>
</body>
</html>
"""

    result = _send_email_payload(
        to_emails=[to_email],
        subject=subject,
        text_body=text,
        html_body=html,
    )
    if result.get("sent"):
        logger.info("Rejection notify email sent to %s for %s / %s vs %s", to_email, staff, home, away)
    return result


def _fixture_rows_html(fixtures: list[dict[str, Any]], *, ticket_mode: bool = False) -> str:
    if not fixtures:
        return '<p style="color:#94a3b8;margin:0;">No fixtures in this list.</p>'
    rows = []
    for row in fixtures:
        kickoff = _escape(str(row.get("kickoff_label") or row.get("date") or "TBC"))
        match = _escape(f"{row.get('home') or 'Home'} vs {row.get('away') or 'Away'}")
        league = _escape(str(row.get("league") or ""))
        staff = _escape(str(row.get("staff") or "TBC"))
        watch = _escape(str(row.get("watch_type") or "").upper() or "—")
        venue = _escape(str(row.get("venue") or ""))
        watch_color = "#34d399" if watch == "LIVE" else "#fbbf24"
        detail_cell = f"""
              <td style="padding:10px 12px;border-bottom:1px solid #1f2937;vertical-align:top;">
                <div style="font-weight:600;color:#f8fafc;">{staff}</div>
                <div style="font-size:12px;color:{watch_color};margin-top:2px;">{watch}</div>
                {f'<div style="font-size:12px;color:#94a3b8;margin-top:2px;">{venue}</div>' if venue else ''}
              </td>
        """
        if ticket_mode:
            tickets = row.get("tickets")
            parking = str(row.get("parking") or "No").strip() or "No"
            notes = str(row.get("notes") or "").strip()
            ticket_label = _escape(str(tickets if tickets not in (None, "") else "TBC"))
            parking_label = _escape(parking)
            notes_html = (
                f'<div style="font-size:12px;color:#94a3b8;margin-top:4px;">{_escape(notes)}</div>'
                if notes
                else ""
            )
            detail_cell = f"""
              <td style="padding:10px 12px;border-bottom:1px solid #1f2937;vertical-align:top;">
                <div style="font-weight:600;color:#f8fafc;">{staff}</div>
                <div style="font-size:12px;color:#cbd5e1;margin-top:4px;">Tickets: <strong style="color:#f8fafc;">{ticket_label}</strong></div>
                <div style="font-size:12px;color:#cbd5e1;margin-top:2px;">Parking: <strong style="color:#f8fafc;">{parking_label}</strong></div>
                {notes_html}
                {f'<div style="font-size:12px;color:#94a3b8;margin-top:4px;">{venue}</div>' if venue else ''}
              </td>
            """
        rows.append(
            f"""
            <tr>
              <td style="padding:10px 12px;border-bottom:1px solid #1f2937;color:#e2e8f0;vertical-align:top;">
                <div style="font-weight:700;">{match}</div>
                <div style="font-size:12px;color:#94a3b8;margin-top:3px;">{league}</div>
              </td>
              <td style="padding:10px 12px;border-bottom:1px solid #1f2937;color:#cbd5e1;vertical-align:top;white-space:nowrap;">{kickoff}</td>
              {detail_cell}
            </tr>
            """
        )
    attendee_header = "Tickets / parking" if ticket_mode else "Attendee"
    return f"""
      <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;margin-top:8px;">
        <tr>
          <th align="left" style="padding:8px 12px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;border-bottom:1px solid #1f2937;">Fixture</th>
          <th align="left" style="padding:8px 12px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;border-bottom:1px solid #1f2937;">Kick-off</th>
          <th align="left" style="padding:8px 12px;font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#94a3b8;border-bottom:1px solid #1f2937;">{attendee_header}</th>
        </tr>
        {''.join(rows)}
      </table>
    """


def _fixture_rows_text(fixtures: list[dict[str, Any]], *, ticket_mode: bool = False) -> str:
    lines: list[str] = []
    for row in fixtures:
        lines.append(
            f"- {row.get('home') or 'Home'} vs {row.get('away') or 'Away'}"
            f" ({row.get('league') or 'League TBC'})"
            f" · {row.get('kickoff_label') or row.get('date') or 'Date TBC'}"
            f" · {row.get('staff') or 'TBC'}"
            f" · {str(row.get('watch_type') or '').upper() or '—'}"
        )
        if row.get("venue"):
            lines.append(f"  Venue: {row.get('venue')}")
        if ticket_mode:
            tickets = row.get("tickets")
            parking = str(row.get("parking") or "No").strip() or "No"
            notes = str(row.get("notes") or "").strip()
            lines.append(f"  Tickets: {tickets if tickets not in (None, '') else 'TBC'}")
            lines.append(f"  Parking: {parking}")
            if notes:
                lines.append(f"  Notes: {notes}")
    return "\n".join(lines) if lines else "No fixtures in this list."


def build_ticket_request_email_html(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
    additional_requests: str = "",
) -> str:
    extra = str(additional_requests or "").strip()
    extra_block = ""
    if extra:
        extra_block = f"""
              <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0f172a;border:1px solid #1f2937;border-radius:12px;margin-top:16px;">
                <tr>
                  <td style="padding:14px 16px;">
                    <div style="font-size:11px;letter-spacing:.06em;text-transform:uppercase;color:#f5c518;">Additional requests</div>
                    <div style="font-size:14px;color:#e2e8f0;margin-top:8px;white-space:pre-wrap;">{_escape(extra)}</div>
                  </td>
                </tr>
              </table>
        """
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /></head>
<body style="margin:0;padding:0;background:#0b1220;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1220;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:#111827;border:1px solid #1f2937;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="padding:20px 24px;background:#0f172a;border-bottom:1px solid #1f2937;">
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#f5c518;font-weight:700;">Port Vale F.C. · Recruitment</div>
              <div style="font-size:22px;font-weight:700;color:#f8fafc;margin-top:6px;">Ticket request — upcoming fixtures</div>
              <div style="font-size:14px;color:#94a3b8;margin-top:4px;">{_escape(period_label)} · {len(fixtures)} live fixture{"s" if len(fixtures) != 1 else ""} needing tickets</div>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px;">
              <p style="margin:0 0 12px;color:#cbd5e1;font-size:14px;line-height:1.5;">
                Please arrange tickets for the following live scouting fixtures. Ticket quantity, parking, and any notes are listed against each game.
              </p>
              {_fixture_rows_html(fixtures, ticket_mode=True)}
              {extra_block}
            </td>
          </tr>
          <tr>
            <td style="padding:14px 24px 20px;border-top:1px solid #1f2937;color:#64748b;font-size:12px;">
              Sent from the Fixture Planner · Reply to this email if anything needs changing.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def build_ticket_request_email_text(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
    additional_requests: str = "",
) -> str:
    lines = [
        "Port Vale Recruitment — Ticket request",
        period_label,
        f"{len(fixtures)} live fixture(s) needing tickets",
        "",
        "Please arrange tickets for:",
        _fixture_rows_text(fixtures, ticket_mode=True),
    ]
    extra = str(additional_requests or "").strip()
    if extra:
        lines.extend(["", "Additional requests:", extra])
    lines.extend(["", "Sent from the Fixture Planner."])
    return "\n".join(lines)


def build_schedule_update_email_html(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
) -> str:
    live_count = sum(1 for row in fixtures if str(row.get("watch_type") or "").upper() == "LIVE")
    video_count = sum(1 for row in fixtures if str(row.get("watch_type") or "").upper() == "VIDEO")
    return f"""\
<!DOCTYPE html>
<html>
<head><meta charset="utf-8" /></head>
<body style="margin:0;padding:0;background:#0b1220;font-family:Arial,Helvetica,sans-serif;color:#e2e8f0;">
  <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="background:#0b1220;padding:24px 12px;">
    <tr>
      <td align="center">
        <table role="presentation" width="640" cellspacing="0" cellpadding="0" style="max-width:640px;background:#111827;border:1px solid #1f2937;border-radius:16px;overflow:hidden;">
          <tr>
            <td style="padding:20px 24px;background:#0f172a;border-bottom:1px solid #1f2937;">
              <div style="font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:#f5c518;font-weight:700;">Port Vale F.C. · Recruitment</div>
              <div style="font-size:22px;font-weight:700;color:#f8fafc;margin-top:6px;">Fixture schedule update</div>
              <div style="font-size:14px;color:#94a3b8;margin-top:4px;">{_escape(period_label)} · {len(fixtures)} assigned · Live {live_count} · Video {video_count}</div>
            </td>
          </tr>
          <tr>
            <td style="padding:18px 24px;">
              <p style="margin:0 0 12px;color:#cbd5e1;font-size:14px;line-height:1.5;">
                Fortnightly update of where the recruitment and coaching group are covering over the next two weeks.
              </p>
              {_fixture_rows_html(fixtures)}
            </td>
          </tr>
          <tr>
            <td style="padding:14px 24px 20px;border-top:1px solid #1f2937;color:#64748b;font-size:12px;">
              Sent from the Fixture Planner · Coaching staff &amp; recruitment team.
            </td>
          </tr>
        </table>
      </td>
    </tr>
  </table>
</body>
</html>
"""


def build_schedule_update_email_text(*, fixtures: list[dict[str, Any]], period_label: str) -> str:
    live_count = sum(1 for row in fixtures if str(row.get("watch_type") or "").upper() == "LIVE")
    video_count = sum(1 for row in fixtures if str(row.get("watch_type") or "").upper() == "VIDEO")
    return "\n".join(
        [
            "Port Vale Recruitment — Fixture schedule update",
            period_label,
            f"{len(fixtures)} assigned fixtures (Live {live_count} · Video {video_count})",
            "",
            "Where we are covering over the next two weeks:",
            _fixture_rows_text(fixtures),
            "",
            "Sent from the Fixture Planner.",
        ]
    )


def _send_multipart_email(
    *,
    to_emails: list[str],
    subject: str,
    text_body: str,
    html_body: str,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not email_configured():
        return {
            "sent": False,
            "reason": "Email not configured (set SMTP, RESEND_API_KEY, or Microsoft Graph in .env)",
        }

    result = _send_email_payload(
        to_emails=to_emails,
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        attachments=attachments,
    )
    if result.get("sent"):
        recipients = _parse_email_list(",".join(to_emails))
        logger.info("Bulk fixture email sent to %s · %s", recipients, subject)
        result["attachments"] = [
            str(row.get("filename") or "") for row in (attachments or []) if row.get("content")
        ]
    return result


def build_ticket_request_print_pdf(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
    additional_requests: str = "",
) -> bytes:
    """Light printable A4 sheet for admin (tickets / parking checklist)."""
    from fpdf import FPDF

    pdf = FPDF(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=14)
    pdf.add_page()
    pdf.set_fill_color(255, 255, 255)

    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 8, "Port Vale FC - Ticket request", ln=True)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(71, 85, 105)
    pdf.cell(
        0,
        6,
        _pdf_safe_text(f"{period_label}  |  {len(fixtures)} live fixture(s)"),
        ln=True,
    )
    pdf.ln(4)

    col_w = [62, 38, 28, 22, 40]
    headers = ["Fixture", "Kick-off", "Attendee", "Tickets", "Parking / notes"]
    pdf.set_font("Helvetica", "B", 9)
    pdf.set_fill_color(241, 245, 249)
    pdf.set_text_color(15, 23, 42)
    for width, header in zip(col_w, headers):
        pdf.cell(width, 8, header, border=1, fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", "", 9)
    for row in fixtures:
        home = _pdf_safe_text(row.get("home") or "Home")
        away = _pdf_safe_text(row.get("away") or "Away")
        league = _pdf_safe_text(row.get("league") or "")
        match = f"{home} vs {away}"
        if league:
            match = f"{match} ({league})"
        kickoff = _pdf_safe_text(row.get("kickoff_label") or row.get("date") or "TBC")
        staff = _pdf_safe_text(row.get("staff") or "TBC")
        tickets = _pdf_safe_text(
            row.get("tickets") if row.get("tickets") not in (None, "") else "TBC"
        )
        parking = _pdf_safe_text(row.get("parking") or "No")
        notes = _pdf_safe_text(row.get("notes") or "").strip()
        parking_notes = parking if not notes else f"{parking} / {notes}"

        # Estimate row height from wrapped match text.
        match_lines = pdf.multi_cell(col_w[0], 5, match, border=0, dry_run=True, output="LINES")
        line_count = max(1, len(match_lines) if isinstance(match_lines, list) else 1)
        row_h = max(10, line_count * 5 + 2)
        if pdf.get_y() + row_h > 280:
            pdf.add_page()
            pdf.set_font("Helvetica", "B", 9)
            pdf.set_fill_color(241, 245, 249)
            for width, header in zip(col_w, headers):
                pdf.cell(width, 8, header, border=1, fill=True)
            pdf.ln()
            pdf.set_font("Helvetica", "", 9)

        x0 = pdf.get_x()
        y0 = pdf.get_y()
        pdf.rect(x0, y0, sum(col_w), row_h)
        # vertical lines
        x = x0
        for width in col_w[:-1]:
            x += width
            pdf.line(x, y0, x, y0 + row_h)

        pdf.set_xy(x0 + 1, y0 + 1.5)
        pdf.multi_cell(col_w[0] - 2, 5, match, border=0)
        pdf.set_xy(x0 + col_w[0] + 1, y0 + 2.5)
        pdf.cell(col_w[1] - 2, 5, kickoff[:28])
        pdf.set_xy(x0 + col_w[0] + col_w[1] + 1, y0 + 2.5)
        pdf.cell(col_w[2] - 2, 5, staff[:18])
        pdf.set_xy(x0 + col_w[0] + col_w[1] + col_w[2] + 1, y0 + 2.5)
        pdf.cell(col_w[3] - 2, 5, tickets[:8])
        pdf.set_xy(x0 + col_w[0] + col_w[1] + col_w[2] + col_w[3] + 1, y0 + 2.5)
        pdf.cell(col_w[4] - 2, 5, parking_notes[:32])
        pdf.set_xy(x0, y0 + row_h)

    extra = _pdf_safe_text(additional_requests).strip()
    if extra:
        pdf.ln(6)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(15, 23, 42)
        pdf.cell(0, 7, "Additional requests", ln=True)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(51, 65, 85)
        pdf.multi_cell(0, 5, extra)

    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 8)
    pdf.set_text_color(100, 116, 139)
    pdf.cell(0, 5, "Generated from Fixture Planner - print and annotate as needed.", ln=True)

    buffer = BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def build_ticket_request_print_png(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
    additional_requests: str = "",
) -> bytes | None:
    """Rasterise the printable PDF (first page) to PNG for quick print/share."""
    try:
        import fitz  # PyMuPDF
    except Exception:
        logger.warning("PyMuPDF unavailable; skipping ticket request PNG attachment")
        return None

    pdf_bytes = build_ticket_request_print_pdf(
        fixtures=fixtures,
        period_label=period_label,
        additional_requests=additional_requests,
    )
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        if doc.page_count < 1:
            doc.close()
            return None
        pix = doc.load_page(0).get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        png = pix.tobytes("png")
        doc.close()
        return png
    except Exception:
        logger.exception("Failed to render ticket request PNG")
        return None


def send_ticket_request_email(
    *,
    fixtures: list[dict[str, Any]],
    period_label: str,
    additional_requests: str = "",
) -> dict[str, Any]:
    recipients = admin_team_emails()
    if not recipients:
        return {
            "sent": False,
            "reason": "No admin emails configured (set FIXTURE_ADMIN_EMAILS in .env)",
            "fixture_count": len(fixtures),
        }
    if not fixtures:
        return {"sent": False, "reason": "No upcoming LIVE fixtures needing tickets", "fixture_count": 0}

    attachments: list[dict[str, Any]] = []
    try:
        pdf_bytes = build_ticket_request_print_pdf(
            fixtures=fixtures,
            period_label=period_label,
            additional_requests=additional_requests,
        )
        attachments.append(
            {
                "filename": "ticket-request-print.pdf",
                "content": pdf_bytes,
                "maintype": "application",
                "subtype": "pdf",
            }
        )
    except Exception:
        logger.exception("Failed to build ticket request PDF")

    png_bytes = build_ticket_request_print_png(
        fixtures=fixtures,
        period_label=period_label,
        additional_requests=additional_requests,
    )
    if png_bytes:
        attachments.append(
            {
                "filename": "ticket-request-print.png",
                "content": png_bytes,
                "maintype": "image",
                "subtype": "png",
            }
        )

    result = _send_multipart_email(
        to_emails=recipients,
        subject=f"Ticket request · next two weeks · {len(fixtures)} live fixture{'s' if len(fixtures) != 1 else ''}",
        text_body=build_ticket_request_email_text(
            fixtures=fixtures,
            period_label=period_label,
            additional_requests=additional_requests,
        )
        + "\n\nA printable PDF and image are attached.",
        html_body=build_ticket_request_email_html(
            fixtures=fixtures,
            period_label=period_label,
            additional_requests=additional_requests,
        ).replace(
            "Please arrange tickets for the following live scouting fixtures.",
            "Please arrange tickets for the following live scouting fixtures. A printable PDF and image are attached for the desk.",
            1,
        ),
        attachments=attachments,
    )
    result["fixture_count"] = len(fixtures)
    result["kind"] = "ticket_request"
    return result


def send_schedule_update_email(*, fixtures: list[dict[str, Any]], period_label: str) -> dict[str, Any]:
    recipients = schedule_update_emails()
    if not recipients:
        return {
            "sent": False,
            "reason": "No schedule recipients configured (set FIXTURE_SCHEDULE_EMAILS or staff emails)",
            "fixture_count": len(fixtures),
        }
    if not fixtures:
        return {
            "sent": False,
            "reason": "No assigned fixtures in the next fortnight",
            "fixture_count": 0,
        }

    result = _send_multipart_email(
        to_emails=recipients,
        subject=f"Fixture schedule update · next fortnight ({len(fixtures)} games)",
        text_body=build_schedule_update_email_text(fixtures=fixtures, period_label=period_label),
        html_body=build_schedule_update_email_html(fixtures=fixtures, period_label=period_label),
    )
    result["fixture_count"] = len(fixtures)
    result["kind"] = "schedule_update"
    return result
