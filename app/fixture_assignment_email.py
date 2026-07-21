from __future__ import annotations

import logging
import os
import smtplib
import ssl
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid
from io import BytesIO
from typing import Any

import requests

logger = logging.getLogger(__name__)

SCOUT_EMAILS: dict[str, str] = {
    "Lee Darnbrough": "Lee.darnbrough@port-vale.co.uk",
    "Tommy Johnson": "Tommy.johnson@port-vale.co.uk",
    "Martin Foyle": "Martin.Foyle@port-vale.co.uk",
}

DEFAULT_FROM_EMAIL = "sam.baker@port-vale.co.uk"
DEFAULT_FROM_NAME = "Sam Baker · Port Vale Recruitment"
DEFAULT_SMTP_HOST = "smtp.office365.com"
DEFAULT_SMTP_PORT = 587

_http = requests.Session()
_http.trust_env = False


def scout_email_for(staff: str) -> str | None:
    return SCOUT_EMAILS.get(str(staff or "").strip())


def _env(name: str, default: str = "") -> str:
    return str(os.getenv(name, default) or "").strip()


def smtp_configured() -> bool:
    return bool(_env("SMTP_PASSWORD") or _env("FIXTURE_EMAIL_PASSWORD"))


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
        try:
            stamp = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            local = stamp.astimezone(ZoneInfo("Europe/London"))
            return local.strftime("%a %d %b %Y · %H:%M").replace(" 0", " ", 1)
        except ValueError:
            pass
    day = str(date_key or "").strip()[:10]
    if day:
        try:
            stamp = datetime.fromisoformat(f"{day}T12:00:00")
            return stamp.strftime("%a %d %b %Y · kick-off TBC").replace(" 0", " ", 1)
        except ValueError:
            return day
    return "Date / kick-off TBC"


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
              <p style="font-size:13px;line-height:1.5;color:#94a3b8;margin:18px 0 0;">
                Assigned by Sam Baker via the Fixture Planner. Reply to this email if you need to swap or can't cover.
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
) -> dict[str, Any]:
    to_email = scout_email_for(staff)
    if not to_email:
        return {"sent": False, "reason": f"No email configured for {staff}"}

    settings = _smtp_settings()
    if not settings["password"]:
        logger.warning("SMTP password not configured; skipped assignment email to %s", to_email)
        return {
            "sent": False,
            "reason": "SMTP password not configured (set SMTP_PASSWORD in .env)",
        }

    kickoff_label = _format_kickoff(kickoff_utc, date_key)
    venue_label = venue or (f"{home} (home)" if home else "Venue TBC")
    targets = watched_players or []

    root = MIMEMultipart("related")
    root["Subject"] = f"Scouting assignment · {home} vs {away}"
    root["From"] = formataddr((settings["from_name"], settings["from_email"]))
    root["To"] = to_email
    root["Reply-To"] = settings["from_email"]

    alt = MIMEMultipart("alternative")
    root.attach(alt)

    home_bytes = _download_image(home_badge_url)
    away_bytes = _download_image(away_badge_url)
    home_cid = make_msgid(domain="port-vale.co.uk")[1:-1] if home_bytes else None
    away_cid = make_msgid(domain="port-vale.co.uk")[1:-1] if away_bytes else None

    alt.attach(
        MIMEText(
            build_assignment_email_text(
                staff=staff,
                home=home,
                away=away,
                league=league,
                watch_type=watch_type,
                kickoff_label=kickoff_label,
                venue=venue_label,
                watched_players=targets,
            ),
            "plain",
            "utf-8",
        )
    )
    alt.attach(
        MIMEText(
            build_assignment_email_html(
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
            ),
            "html",
            "utf-8",
        )
    )

    if home_bytes and home_cid:
        image = MIMEImage(home_bytes)
        image.add_header("Content-ID", f"<{home_cid}>")
        image.add_header("Content-Disposition", "inline", filename="home-badge.png")
        root.attach(image)
    if away_bytes and away_cid:
        image = MIMEImage(away_bytes)
        image.add_header("Content-ID", f"<{away_cid}>")
        image.add_header("Content-Disposition", "inline", filename="away-badge.png")
        root.attach(image)

    context = _ssl_context()
    with smtplib.SMTP(settings["host"], settings["port"], timeout=30) as server:
        server.ehlo()
        server.starttls(context=context)
        server.ehlo()
        server.login(settings["user"], settings["password"])
        server.sendmail(settings["from_email"], [to_email], root.as_string())

    logger.info("Assignment email sent to %s for %s vs %s", to_email, home, away)
    return {"sent": True, "to": to_email}
