#!/usr/bin/env python3
"""Compile the 2026 summer EFL / NL / Scottish Prem transfer report."""

from __future__ import annotations

import json
import re
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "efl-transfer-sources"
OUT = ROOT / "data" / "efl-transfer-report-2026.json"

LEAGUES = [
    ("league-one", "League One"),
    ("league-two", "League Two"),
    ("national-league", "National League"),
    ("scottish-prem", "Scottish Premiership"),
]

CLUBS: list[tuple[str, str, str]] = [
    # League One 2026/27
    ("league-one", "afc-wimbledon", "AFC Wimbledon"),
    ("league-one", "barnsley", "Barnsley"),
    ("league-one", "blackpool", "Blackpool"),
    ("league-one", "bradford-city", "Bradford City"),
    ("league-one", "bromley", "Bromley"),
    ("league-one", "burton-albion", "Burton Albion"),
    ("league-one", "cambridge-united", "Cambridge United"),
    ("league-one", "doncaster-rovers", "Doncaster Rovers"),
    ("league-one", "huddersfield-town", "Huddersfield Town"),
    ("league-one", "leicester-city", "Leicester City"),
    ("league-one", "leyton-orient", "Leyton Orient"),
    ("league-one", "luton-town", "Luton Town"),
    ("league-one", "mansfield-town", "Mansfield Town"),
    ("league-one", "mk-dons", "MK Dons"),
    ("league-one", "notts-county", "Notts County"),
    ("league-one", "oxford-united", "Oxford United"),
    ("league-one", "peterborough-united", "Peterborough United"),
    ("league-one", "plymouth-argyle", "Plymouth Argyle"),
    ("league-one", "reading", "Reading"),
    ("league-one", "sheffield-wednesday", "Sheffield Wednesday"),
    ("league-one", "stevenage", "Stevenage"),
    ("league-one", "stockport-county", "Stockport County"),
    ("league-one", "wigan-athletic", "Wigan Athletic"),
    ("league-one", "wycombe-wanderers", "Wycombe Wanderers"),
    # League Two 2026/27
    ("league-two", "accrington-stanley", "Accrington Stanley"),
    ("league-two", "barnet", "Barnet"),
    ("league-two", "bristol-rovers", "Bristol Rovers"),
    ("league-two", "cheltenham-town", "Cheltenham Town"),
    ("league-two", "chesterfield", "Chesterfield"),
    ("league-two", "colchester-united", "Colchester United"),
    ("league-two", "crawley-town", "Crawley Town"),
    ("league-two", "crewe-alexandra", "Crewe Alexandra"),
    ("league-two", "exeter-city", "Exeter City"),
    ("league-two", "fleetwood-town", "Fleetwood Town"),
    ("league-two", "gillingham", "Gillingham"),
    ("league-two", "grimsby-town", "Grimsby Town"),
    ("league-two", "newport-county", "Newport County"),
    ("league-two", "northampton-town", "Northampton Town"),
    ("league-two", "oldham-athletic", "Oldham Athletic"),
    ("league-two", "port-vale", "Port Vale"),
    ("league-two", "rochdale", "Rochdale"),
    ("league-two", "rotherham-united", "Rotherham United"),
    ("league-two", "salford-city", "Salford City"),
    ("league-two", "shrewsbury-town", "Shrewsbury Town"),
    ("league-two", "swindon-town", "Swindon Town"),
    ("league-two", "tranmere-rovers", "Tranmere Rovers"),
    ("league-two", "walsall", "Walsall"),
    ("league-two", "york-city", "York City"),
    # National League 2026/27
    ("national-league", "afc-fylde", "AFC Fylde"),
    ("national-league", "aldershot-town", "Aldershot Town"),
    ("national-league", "altrincham", "Altrincham"),
    ("national-league", "barrow", "Barrow"),
    ("national-league", "boreham-wood", "Boreham Wood"),
    ("national-league", "boston-united", "Boston United"),
    ("national-league", "carlisle-united", "Carlisle United"),
    ("national-league", "eastleigh", "Eastleigh"),
    ("national-league", "fc-halifax-town", "FC Halifax Town"),
    ("national-league", "forest-green-rovers", "Forest Green Rovers"),
    ("national-league", "gateshead", "Gateshead"),
    ("national-league", "harrogate-town", "Harrogate Town"),
    ("national-league", "hartlepool-united", "Hartlepool United"),
    ("national-league", "hornchurch", "Hornchurch"),
    ("national-league", "kidderminster-harriers", "Kidderminster Harriers"),
    ("national-league", "scunthorpe-united", "Scunthorpe United"),
    ("national-league", "solihull-moors", "Solihull Moors"),
    ("national-league", "southend-united", "Southend United"),
    ("national-league", "sutton-united", "Sutton United"),
    ("national-league", "tamworth", "Tamworth"),
    ("national-league", "wealdstone", "Wealdstone"),
    ("national-league", "woking", "Woking"),
    ("national-league", "worthing", "Worthing"),
    ("national-league", "yeovil-town", "Yeovil Town"),
    # Scottish Premiership 2026/27
    ("scottish-prem", "aberdeen", "Aberdeen"),
    ("scottish-prem", "celtic", "Celtic"),
    ("scottish-prem", "dundee", "Dundee"),
    ("scottish-prem", "dundee-united", "Dundee United"),
    ("scottish-prem", "falkirk", "Falkirk"),
    ("scottish-prem", "hearts", "Heart of Midlothian"),
    ("scottish-prem", "hibernian", "Hibernian"),
    ("scottish-prem", "kilmarnock", "Kilmarnock"),
    ("scottish-prem", "motherwell", "Motherwell"),
    ("scottish-prem", "rangers", "Rangers"),
    ("scottish-prem", "st-johnstone", "St Johnstone"),
    ("scottish-prem", "st-mirren", "St Mirren"),
]

SKIP_ROLES = {
    "head coach",
    "manager",
    "first team manager",
    "interim manager",
}

ALIASES = {
    "afc wimbledon": "afc-wimbledon",
    "wimbledon": "afc-wimbledon",
    "barnsley": "barnsley",
    "blackpool": "blackpool",
    "bradford": "bradford-city",
    "bradford city": "bradford-city",
    "bromley": "bromley",
    "burton": "burton-albion",
    "burton albion": "burton-albion",
    "cambridge": "cambridge-united",
    "cambridge utd": "cambridge-united",
    "cambridge united": "cambridge-united",
    "doncaster": "doncaster-rovers",
    "doncaster rovers": "doncaster-rovers",
    "huddersfield": "huddersfield-town",
    "huddersfield town": "huddersfield-town",
    "leicester": "leicester-city",
    "leicester city": "leicester-city",
    "leyton orient": "leyton-orient",
    "orient": "leyton-orient",
    "luton": "luton-town",
    "luton town": "luton-town",
    "mansfield": "mansfield-town",
    "mansfield town": "mansfield-town",
    "mk dons": "mk-dons",
    "milton keynes dons": "mk-dons",
    "notts county": "notts-county",
    "notts co": "notts-county",
    "oxford": "oxford-united",
    "oxford utd": "oxford-united",
    "oxford united": "oxford-united",
    "peterborough": "peterborough-united",
    "peterborough united": "peterborough-united",
    "plymouth": "plymouth-argyle",
    "plymouth argyle": "plymouth-argyle",
    "reading": "reading",
    "sheff wed": "sheffield-wednesday",
    "sheff wednesday": "sheffield-wednesday",
    "sheffield wed": "sheffield-wednesday",
    "sheffield wednesday": "sheffield-wednesday",
    "stevenage": "stevenage",
    "stockport": "stockport-county",
    "stockport county": "stockport-county",
    "wigan": "wigan-athletic",
    "wigan athletic": "wigan-athletic",
    "wycombe": "wycombe-wanderers",
    "wycombe wanderers": "wycombe-wanderers",
    "accrington": "accrington-stanley",
    "accrington stanley": "accrington-stanley",
    "barnet": "barnet",
    "bristol rovers": "bristol-rovers",
    "cheltenham": "cheltenham-town",
    "cheltenham town": "cheltenham-town",
    "chesterfield": "chesterfield",
    "colchester": "colchester-united",
    "colchester united": "colchester-united",
    "crawley": "crawley-town",
    "crawley town": "crawley-town",
    "crewe": "crewe-alexandra",
    "crewe alexandra": "crewe-alexandra",
    "exeter": "exeter-city",
    "exeter city": "exeter-city",
    "fleetwood": "fleetwood-town",
    "fleetwood town": "fleetwood-town",
    "gillingham": "gillingham",
    "grimsby": "grimsby-town",
    "grimsby town": "grimsby-town",
    "newport": "newport-county",
    "newport county": "newport-county",
    "northampton": "northampton-town",
    "northampton town": "northampton-town",
    "oldham": "oldham-athletic",
    "oldham athletic": "oldham-athletic",
    "port vale": "port-vale",
    "rochdale": "rochdale",
    "rotherham": "rotherham-united",
    "rotherham united": "rotherham-united",
    "salford": "salford-city",
    "salford city": "salford-city",
    "shrewsbury": "shrewsbury-town",
    "shrewsbury town": "shrewsbury-town",
    "swindon": "swindon-town",
    "swindon town": "swindon-town",
    "tranmere": "tranmere-rovers",
    "tranmere rovers": "tranmere-rovers",
    "walsall": "walsall",
    "york": "york-city",
    "york city": "york-city",
    "afc fylde": "afc-fylde",
    "fylde": "afc-fylde",
    "aldershot": "aldershot-town",
    "aldershot town": "aldershot-town",
    "altrincham": "altrincham",
    "barrow": "barrow",
    "boreham wood": "boreham-wood",
    "boston": "boston-united",
    "boston united": "boston-united",
    "carlisle": "carlisle-united",
    "carlisle united": "carlisle-united",
    "eastleigh": "eastleigh",
    "halifax": "fc-halifax-town",
    "fc halifax": "fc-halifax-town",
    "fc halifax town": "fc-halifax-town",
    "forest green": "forest-green-rovers",
    "forest green rovers": "forest-green-rovers",
    "gateshead": "gateshead",
    "harrogate": "harrogate-town",
    "harrogate town": "harrogate-town",
    "hartlepool": "hartlepool-united",
    "hartlepool united": "hartlepool-united",
    "hartlepool town": "hartlepool-united",
    "hornchurch": "hornchurch",
    "kidderminster": "kidderminster-harriers",
    "kidderminster harriers": "kidderminster-harriers",
    "scunthorpe": "scunthorpe-united",
    "scunthorpe united": "scunthorpe-united",
    "solihull": "solihull-moors",
    "solihull moors": "solihull-moors",
    "southend": "southend-united",
    "southend united": "southend-united",
    "sutton": "sutton-united",
    "sutton united": "sutton-united",
    "tamworth": "tamworth",
    "wealdstone": "wealdstone",
    "woking": "woking",
    "worthing": "worthing",
    "yeovil": "yeovil-town",
    "yeovil town": "yeovil-town",
    "aberdeen": "aberdeen",
    "celtic": "celtic",
    "dundee": "dundee",
    "dundee utd": "dundee-united",
    "dundee united": "dundee-united",
    "falkirk": "falkirk",
    "hearts": "hearts",
    "heart of midlothian": "hearts",
    "hibernian": "hibernian",
    "hibs": "hibernian",
    "kilmarnock": "kilmarnock",
    "motherwell": "motherwell",
    "rangers": "rangers",
    "st johnstone": "st-johnstone",
    "st. johnstone": "st-johnstone",
    "st mirren": "st-mirren",
    "st. mirren": "st-mirren",
}

CLUB_BY_ID = {cid: {"id": cid, "name": name, "league": league} for league, cid, name in CLUBS}
NAME_BY_ID = {cid: name for _, cid, name in CLUBS}

DEAL_RE = re.compile(
    r"^(?:\d{1,2}[:.]\d{2}:?\s*)?([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ0-9'.\- ]+?)\s*[\[(]\s*([^\]\)]+?)\s*[\])]\s*(.*)$"
)
BRACKET_SPLIT = re.compile(r"\s+(?:-|–|—|v)\s+", re.I)
WIKI_ROW = re.compile(
    r"^\|\s*(\d{1,2}\s+\w+\s+2026)?\s*\|\s*([^|]*)\|\s*([^|]+)\|\s*([^|]+)\|\s*([^|]+)\|"
)
SCOT_ITEM = re.compile(
    r"([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'.\- ]+?)(?:,\s*([^;(]+?))?(?:\s*\(([^)]*)\))?"
)

STAFF_NAMES = {
    "wouter vrancken",
    "derek mcinnes",
    "danny rohl",
    "danny röhl",
    "alfred johansson",
    "jens berthal askou",
    "jens berthel askou",
    "scott lindsey",
    "stuart maynard",
}


FIRST_NAME_CANON = {
    "alexander": "alexander",
    "alex": "alexander",
    "andrew": "andrew",
    "andy": "andrew",
    "benjamin": "benjamin",
    "ben": "benjamin",
    "christopher": "christopher",
    "chris": "christopher",
    "daniel": "daniel",
    "dan": "daniel",
    "danny": "daniel",
    "james": "james",
    "jamie": "james",
    "jim": "james",
    "jimmy": "james",
    "joseph": "joseph",
    "joe": "joseph",
    "josef": "joseph",
    "jonathan": "jonathan",
    "jon": "jonathan",
    "johnny": "jonathan",
    "matthew": "matthew",
    "matt": "matthew",
    "matty": "matthew",
    "mattie": "matthew",
    "michael": "michael",
    "mike": "michael",
    "mick": "michael",
    "nicholas": "nicholas",
    "nick": "nicholas",
    "nicky": "nicholas",
    "oliver": "oliver",
    "olly": "oliver",
    "ollie": "oliver",
    "oli": "oliver",
    "ismael": "ismael",
    "ismeal": "ismael",
    "ruari": "ruari",
    "ruiri": "ruari",
    "shumaira": "shumaira",
    "shim": "shumaira",
    "richard": "richard",
    "rich": "richard",
    "rick": "richard",
    "ricky": "richard",
    "robert": "robert",
    "rob": "robert",
    "bobby": "robert",
    "samuel": "samuel",
    "sam": "samuel",
    "thomas": "thomas",
    "tom": "thomas",
    "tommy": "thomas",
    "timothy": "timothy",
    "tim": "timothy",
    "william": "william",
    "will": "william",
    "billy": "william",
    "joshua": "joshua",
    "josh": "joshua",
}


def _fold_accents(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char))


def _norm(value: str) -> str:
    text = _fold_accents(value or "").strip().lower()
    text = text.replace("&", "and")
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\b(afc|fc|a\.f\.c\.)$", "", text).strip()
    text = text.replace(".", " ")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def resolve_club(raw: str) -> str | None:
    key = _norm(raw)
    if not key or key in {"unattached", "free agent", "released", "retired"}:
        return None
    if key in ALIASES:
        return ALIASES[key]
    # Prefer the more specific United/City token before a bare namesake.
    if "dundee united" in key:
        return "dundee-united"
    if key == "dundee":
        return "dundee"
    if "queens park rangers" in key or key == "qpr":
        return None
    if key == "rangers":
        return "rangers"
    return ALIASES.get(key)


def is_unattached(raw: str) -> bool:
    return _norm(raw) in {"unattached", "free agent", "released", ""}


def classify_fee(fee: str, *, force_loan: bool = False) -> tuple[str, str]:
    text = re.sub(r"\s+", " ", (fee or "").strip())
    low = text.lower()
    if force_loan or re.search(r"\bloan\b", low):
        kind = "loan"
    elif "retired" in low:
        kind = "retired"
    elif "released" in low:
        kind = "released"
    elif re.search(r"end of loan|loan (spell )?ended|returned to|return from loan", low):
        kind = "loan-ended"
    elif "free" in low or low in {"", "free transfer"}:
        kind = "free"
    elif "undisclosed" in low or "undiscosed" in low:
        kind = "undisclosed"
    elif "£" in text or "compensation" in low:
        kind = "fee"
    else:
        kind = "undisclosed" if not text else "other"
    label = text or ("Loan" if kind == "loan" else "Undisclosed")
    if kind == "loan" and "loan" not in label.lower():
        label = "Loan" if not text else f"{text} · Loan"
    if kind == "free" and not text:
        label = "Free"
    return kind, label


def clean_player(name: str) -> str:
    text = re.sub(r",\s*external$", "", name.strip(), flags=re.I)
    text = re.sub(r"\s+", " ", text)
    text = text.replace("Humph reys", "Humphreys")
    fixes = {
        "admir bristic": "Admir Bristric",
        "jaze kabria": "Jaze Kabia",
        "jake beedley": "Jake Beesley",
        "nicholas michalski": "Nick Michalski",
    }
    fixed = fixes.get(_norm(text))
    if fixed:
        return fixed
    if _norm(text) in STAFF_NAMES:
        return ""
    return text


CLUB_DISPLAY = {
    "man city": "Manchester City",
    "manchester city": "Manchester City",
    "hull": "Hull City",
    "hull city": "Hull City",
    "qpr": "Queens Park Rangers",
    "queens park rangers": "Queens Park Rangers",
    "wolves": "Wolves",
    "wolverhampton": "Wolves",
    "wolverhampton wanderers": "Wolves",
    "spurs": "Tottenham",
    "tottenham": "Tottenham",
    "tottenham hotspur": "Tottenham",
    "man utd": "Manchester United",
    "man united": "Manchester United",
    "manchester united": "Manchester United",
    "nottingham forest": "Nottingham Forest",
    "notts forest": "Nottingham Forest",
    "forest": "Nottingham Forest",
}


def clean_club_token(raw: str) -> str:
    text = re.sub(r"\s+", " ", (raw or "").strip())
    text = text.replace("Botlon", "Bolton")
    mapped = CLUB_DISPLAY.get(_norm(text))
    return mapped or text


def _player_key(name: str) -> str:
    return re.sub(r"[^a-z]", "", _norm(name))


def _name_parts(name: str) -> list[str]:
    return [part for part in re.split(r"[\s-]+", _norm(name)) if part]


def same_player(left: str, right: str) -> bool:
    """True when two BBC/preview spellings are the same incoming."""
    if not left or not right:
        return False
    left_key, right_key = _player_key(left), _player_key(right)
    if left_key == right_key:
        return True
    if len(left_key) > 6 and len(right_key) > 6 and (left_key in right_key or right_key in left_key):
        return True
    left_parts, right_parts = _name_parts(left), _name_parts(right)
    if len(left_parts) < 2 or len(right_parts) < 2:
        return False
    if left_parts[-1] != right_parts[-1]:
        return False
    first_left, first_right = left_parts[0], right_parts[0]
    if FIRST_NAME_CANON.get(first_left, first_left) == FIRST_NAME_CANON.get(first_right, first_right):
        return True
    if min(len(first_left), len(first_right)) >= 3 and (
        first_left.startswith(first_right) or first_right.startswith(first_left)
    ):
        return True
    if _first_name_distance(first_left, first_right) <= 2:
        return True
    return False


def _first_name_distance(left: str, right: str) -> int:
    if left == right:
        return 0
    if abs(len(left) - len(right)) > 2:
        return 99
    previous = list(range(len(right) + 1))
    for index, left_char in enumerate(left, start=1):
        current = [index]
        for other_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    previous[other_index] + 1,
                    current[other_index - 1] + 1,
                    previous[other_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _prefer_name(new: str, old: str) -> str:
    if len(_player_key(new)) > len(_player_key(old)):
        return new
    if len(_player_key(new)) < len(_player_key(old)):
        return old
    if any(ord(char) > 127 for char in new) and not any(ord(char) > 127 for char in old):
        return new
    return old


def _merge_move(row: dict, player: str, other: str, kind: str, fee: str) -> None:
    row["player"] = _prefer_name(player, row.get("player") or "")
    if len(other or "") > len(row.get("other") or ""):
        row["other"] = other
    if fee and (not row.get("fee") or len(fee) > len(str(row.get("fee") or ""))):
        row["fee"] = fee
    if kind and (not row.get("kind") or row.get("kind") == "undisclosed"):
        row["kind"] = kind


def add_move(
    bucket: dict[str, list[dict]],
    club_id: str,
    player: str,
    other: str,
    kind: str,
    fee: str,
    bucket_name: str,
) -> None:
    player = clean_player(player)
    if not player or club_id not in CLUB_BY_ID:
        return
    other = clean_club_token(other)
    fee = fee[:1].upper() + fee[1:] if fee else fee
    role = _norm(other)
    if role in SKIP_ROLES:
        return
    for row in bucket[club_id]:
        if not same_player(row["player"], player):
            continue
        if (
            row.get("kind") == kind
            or _norm(row.get("other") or "") == _norm(other)
            or bucket_name == "signed"
        ):
            _merge_move(row, player, other, kind, fee)
            return
        _merge_move(row, player, other, kind, fee)
        return
    bucket[club_id].append(
        {
            "player": player,
            "other": other,
            "kind": kind,
            "fee": fee,
        }
    )


def dedupe_rows(rows: list[dict]) -> list[dict]:
    kept: list[dict] = []
    for row in rows:
        incoming = dict(row)
        incoming["other"] = clean_club_token(str(incoming.get("other") or ""))
        match = next((item for item in kept if same_player(item.get("player") or "", incoming.get("player") or "")), None)
        if match is None:
            kept.append(incoming)
            continue
        _merge_move(
            match,
            str(incoming.get("player") or ""),
            str(incoming.get("other") or ""),
            str(incoming.get("kind") or ""),
            str(incoming.get("fee") or ""),
        )
    drop: set[int] = set()
    by_last: dict[str, list[dict]] = defaultdict(list)
    for row in kept:
        parts = _name_parts(str(row.get("player") or ""))
        if len(parts) >= 2:
            by_last[parts[-1]].append(row)
    for group in by_last.values():
        if len(group) != 2:
            continue
        first_a = _name_parts(group[0]["player"])[0]
        first_b = _name_parts(group[1]["player"])[0]
        if first_a[:2] != first_b[:2]:
            continue
        _merge_move(
            group[0],
            group[1]["player"],
            str(group[1].get("other") or ""),
            str(group[1].get("kind") or ""),
            str(group[1].get("fee") or ""),
        )
        drop.add(id(group[1]))
    return [row for row in kept if id(row) not in drop]


def parse_bbc_deals(text: str, signed: dict, released: dict, left: dict) -> None:
    current_date = ""
    skip_dates = False
    skip_section = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        heading = re.match(r"^##\s+(\d{1,2}\s+\w+)", line)
        if heading:
            current_date = heading.group(1)
            skip_dates = bool(re.search(r"\b(January|February|March|April)\b", current_date, re.I))
            if re.search(r"\b(May|June|July|August|September)\b", current_date, re.I):
                skip_dates = False
            skip_section = False
            continue
        section = line.lower()
        if section in {
            "women's super league",
            "womens super league",
            "wsl",
            "wsl 2",
            "women's championship",
        }:
            skip_section = True
            continue
        if section in {
            "premier league",
            "english football league",
            "scottish premiership",
            "international",
        }:
            skip_section = False
            continue
        if skip_dates or skip_section:
            continue
        match = DEAL_RE.match(line)
        if not match:
            continue
        player, route, fee_raw = match.groups()
        player = clean_player(player)
        if not player:
            continue
        parts = BRACKET_SPLIT.split(route, maxsplit=1)
        if len(parts) != 2:
            continue
        src_raw, dst_raw = clean_club_token(parts[0]), clean_club_token(parts[1])
        kind, fee = classify_fee(fee_raw)
        src_id = resolve_club(src_raw)
        dst_id = resolve_club(dst_raw)
        src_name = NAME_BY_ID.get(src_id, src_raw)
        dst_name = NAME_BY_ID.get(dst_id, dst_raw)
        if dst_id:
            add_move(signed, dst_id, player, src_name, kind, fee, "signed")
        if src_id and is_unattached(dst_raw):
            add_move(released, src_id, player, "Released", "released", "Released", "released")
        elif src_id:
            add_move(left, src_id, player, dst_name, kind, fee, "left")


def parse_preview_players(blob: str) -> list[tuple[str, str, str, str]]:
    items: list[tuple[str, str, str, str]] = []
    if not blob or blob.lower().startswith("none"):
        return items
    # Split on commas that start a new player (capital letter), not fee commas.
    chunks = re.split(r",\s*(?=[A-Z])", blob)
    for chunk in chunks:
        chunk = chunk.strip(" .;")
        if not chunk or len(chunk) < 3:
            continue
        low = chunk.lower()
        if "head coach" in low or chunk.lower().startswith("bristol rovers loanee"):
            # Cheltenham preview wrote a sentence, not a list.
            name_match = re.search(r"([A-Z][a-z]+(?:\s+[A-Z][a-z'’-]+)+)", chunk)
            if "isaac hutchinson" in low and name_match:
                items.append(("Isaac Hutchinson", "Loan ended", "loan-ended", "Loan ended"))
            continue
        name = chunk
        other = ""
        fee_txt = ""
        paren = re.search(r"^(.*?)\s*\((.*)\)\s*$", chunk)
        if paren:
            name = paren.group(1).strip(" -")
            inside = paren.group(2).strip()
            bits = [b.strip() for b in inside.split(",") if b.strip()]
            if bits:
                other = bits[0]
                fee_txt = ", ".join(bits[1:]) if len(bits) > 1 else bits[0]
        else:
            # "Vito Mannone" / "Jude Arthurs (Bromley, free transfer)"
            dash = re.match(r"^(.*?)\s+-\s+(.*)$", chunk)
            if dash:
                name, other = dash.group(1).strip(), dash.group(2).strip()
        name = clean_player(name)
        if not name or _norm(name) in SKIP_ROLES or "among a number" in _norm(name):
            continue
        kind, fee = classify_fee(fee_txt or other)
        if "released" in low or (not other and not fee_txt):
            kind, fee, other = "released", "Released", "Released"
        elif "retired" in low:
            kind, fee, other = "retired", "Retired", "Retired"
        elif re.search(r"end of loan|loan spell ended|returned", low):
            kind, fee = "loan-ended", "Loan ended"
        items.append((name, other or fee, kind, fee))
    return items


def parse_season_preview(text: str, signed: dict, released: dict, left: dict) -> None:
    club_id: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            title = heading.group(1).strip()
            club_id = resolve_club(title)
            continue
        if not club_id:
            continue
        ins = re.match(r"^Key ins:\s*(.+)$", line, re.I)
        outs = re.match(r"^Key outs:\s*(.+)$", line, re.I)
        if ins:
            for name, other, kind, fee in parse_preview_players(ins.group(1)):
                if kind in {"retired"}:
                    continue
                add_move(signed, club_id, name, other, kind, fee, "signed")
        elif outs:
            for name, other, kind, fee in parse_preview_players(outs.group(1)):
                if kind in {"released", "retired"}:
                    add_move(released, club_id, name, other, kind, fee, "released")
                elif kind == "loan-ended":
                    add_move(left, club_id, name, other, kind, fee, "left")
                else:
                    dest_id = resolve_club(other)
                    dest_name = NAME_BY_ID.get(dest_id, other)
                    add_move(left, club_id, name, dest_name, kind, fee, "left")


def parse_scottish_items(blob: str) -> list[tuple[str, str, str, str]]:
    items = []
    for chunk in re.split(r";\s*", blob):
        chunk = chunk.strip(" .")
        if not chunk:
            continue
        match = re.match(
            r"^(?P<name>[A-Za-zÀ-ÿ][A-Za-zÀ-ÿ'.\- ]+?)(?:,\s*(?P<pos>[^;(]+?))?(?:\s*\((?P<inside>[^)]*)\))?$",
            chunk,
        )
        if not match:
            continue
        name = clean_player(match.group("name"))
        inside = (match.group("inside") or "").strip()
        if not name:
            continue
        pos = _norm(match.group("pos") or "")
        if pos in SKIP_ROLES or "coach" in pos or pos == "manager":
            continue
        other = ""
        fee_txt = ""
        if inside:
            bits = [b.strip() for b in inside.split(",") if b.strip()]
            other = bits[0] if bits else ""
            fee_txt = ", ".join(bits[1:]) if len(bits) > 1 else ""
        kind, fee = classify_fee(fee_txt or inside)
        if not inside:
            kind, fee, other = "released", "Released", "Released"
        elif "retired" in inside.lower():
            kind, fee, other = "retired", "Retired", "Retired"
        items.append((name, other or fee, kind, fee))
    return items


def parse_scottish_ins_outs(text: str, signed: dict, released: dict, left: dict) -> None:
    order = [
        "aberdeen",
        "celtic",
        "dundee",
        "dundee-united",
        "falkirk",
        "hearts",
        "hibernian",
        "kilmarnock",
        "motherwell",
        "rangers",
        "st-johnstone",
        "st-mirren",
    ]
    blocks: list[dict[str, str]] = []
    current: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        keyed = re.match(r"^(In|Loan in|Out|Loan ended|Loan out):\s*(.*)$", line, re.I)
        if not keyed:
            continue
        label = keyed.group(1).lower()
        if label == "in" and current:
            blocks.append(current)
            current = {}
        current[label] = keyed.group(2)
    if current:
        blocks.append(current)
    for club_id, block in zip(order, blocks):
        for name, other, kind, fee in parse_scottish_items(block.get("in") or ""):
            add_move(signed, club_id, name, other, kind, fee, "signed")
        for name, other, kind, fee in parse_scottish_items(block.get("loan in") or ""):
            add_move(signed, club_id, name, other, "loan", fee if "loan" in fee.lower() else "Loan", "signed")
        for name, other, kind, fee in parse_scottish_items(block.get("out") or ""):
            if kind in {"released", "retired"}:
                add_move(released, club_id, name, other, kind, fee, "released")
            else:
                dest_id = resolve_club(other)
                dest_name = NAME_BY_ID.get(dest_id, other)
                add_move(left, club_id, name, dest_name, kind, fee, "left")
        for name, other, kind, fee in parse_scottish_items(block.get("loan ended") or ""):
            add_move(left, club_id, name, other, "loan-ended", "Loan ended", "left")
        for name, other, kind, fee in parse_scottish_items(block.get("loan out") or ""):
            dest_id = resolve_club(other)
            dest_name = NAME_BY_ID.get(dest_id, other)
            add_move(left, club_id, name, dest_name, "loan", "Loan", "left")


RETAINED_STOP_TITLES = {
    "jamie ward",
    "callum moseley",
    "related news",
    "headline",
    "never miss a story",
    "hot daily news right into your inbox",
    "more interesting news",
    "cookie policy",
}

RETAINED_RELEASE_HEAD = re.compile(r"^(released|release|retired)\s*:?\s*$", re.I)
RETAINED_LEAVE_HEAD = re.compile(
    r"^(ongoing|under contract|returning|returned|additional year|offered|"
    r"transfer listed|invited|new contract|signed professional|available for|"
    r"loan deal|out of contract|tbc|\*full|\* club|\*club)",
    re.I,
)


def split_retained_names(blob: str) -> list[tuple[str, str]]:
    text = re.sub(r"\s+", " ", (blob or "").strip(" .;"))
    low = text.lower()
    if not text or low in {"tbc", "tbc."}:
        return []
    if low.startswith(("club confirm", "full list", "*full list", "* club")):
        return []
    if re.search(r"\b(the club|would like|confirmed that|following the)\b", low):
        return []
    parts = re.split(r",|\s+&\s+| and ", text)
    rows: list[tuple[str, str]] = []
    for part in parts:
        chunk = part.strip(" .;")
        if not chunk or len(chunk) < 3:
            continue
        kind = "retired" if re.search(r"\bretir", chunk, re.I) else "released"
        name = re.sub(r"\s*\([^)]*\)\s*$", "", chunk).strip()
        name = clean_player(name)
        if not name or _norm(name) in SKIP_ROLES:
            continue
        rows.append((name, kind))
    return rows


def parse_retained_lists(text: str, released: dict) -> None:
    club_id: str | None = None
    in_released = False
    pending: list[str] = []

    def flush() -> None:
        nonlocal pending
        if club_id and pending:
            for name, kind in split_retained_names(" ".join(pending)):
                label = "Retired" if kind == "retired" else "Released"
                add_move(released, club_id, name, label, kind, label, "released")
        pending = []

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.upper() == "ADVERTISEMENT":
            continue
        heading = re.match(r"^##\s+(.+)$", line)
        if heading:
            flush()
            title = heading.group(1).strip()
            if _norm(title) in RETAINED_STOP_TITLES:
                club_id = None
                in_released = False
                continue
            club_id = resolve_club(title)
            in_released = False
            continue
        if not club_id:
            continue
        if RETAINED_RELEASE_HEAD.match(line):
            flush()
            in_released = True
            continue
        if RETAINED_LEAVE_HEAD.match(line):
            flush()
            in_released = False
            continue
        if in_released:
            pending.append(line)
    flush()


def attach_release_destinations(released: dict, left: dict) -> None:
    """A free move after a retained-list release stays under Released."""
    for club_id, rows in released.items():
        keep: list[dict] = []
        for out in left.get(club_id, []):
            match = next(
                (
                    row
                    for row in rows
                    if _player_key(row["player"]) == _player_key(out["player"])
                    or (
                        len(_player_key(out["player"])) > 6
                        and (
                            _player_key(out["player"]) in _player_key(row["player"])
                            or _player_key(row["player"]) in _player_key(out["player"])
                        )
                    )
                ),
                None,
            )
            if match and out.get("kind") in {"free", "released", "retired", "other"}:
                dest = (out.get("other") or "").strip()
                if dest and dest.lower() not in {"released", "retired", "free"}:
                    match["other"] = dest
                continue
            keep.append(out)
        left[club_id] = keep


def parse_spfl(text: str, signed: dict) -> None:
    club_id: str | None = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        maybe = resolve_club(line)
        if maybe and "," not in line and len(line.split()) <= 4:
            club_id = maybe
            continue
        if not club_id:
            continue
        for chunk in line.split("),"):
            chunk = chunk.strip().rstrip(")")
            if not chunk:
                continue
            match = re.match(r"^(.+?)\s*\((.+)$", chunk + (")" if "(" in chunk and ")" not in chunk else ""))
            if not match:
                name = clean_player(chunk)
                if name:
                    add_move(signed, club_id, name, "", "undisclosed", "Undisclosed", "signed")
                continue
            name = clean_player(match.group(1))
            inside = match.group(2).rstrip(")")
            bits = [b.strip() for b in inside.split(",") if b.strip()]
            other = bits[0] if bits else ""
            fee_txt = ", ".join(bits[1:]) if len(bits) > 1 else ""
            kind, fee = classify_fee(fee_txt or inside, force_loan="loan" in inside.lower())
            add_move(signed, club_id, name, other, kind, fee, "signed")


def parse_wikipedia_loans(text: str, signed: dict, left: dict) -> None:
    in_loans = False
    for raw in text.splitlines():
        line = raw.strip()
        if line == "## Loans":
            in_loans = True
            continue
        if line.startswith("## ") and line != "## Loans":
            in_loans = False
            continue
        if not in_loans or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 5 or cells[0] in {"Start date", "---"}:
            continue
        start, _end, player, src, dst = cells[0], cells[1], cells[2], cells[3], cells[4]
        if re.search(r"\b(February|March|April)\s+2026\b", start):
            continue
        player = clean_player(player)
        src_id, dst_id = resolve_club(src), resolve_club(dst)
        if dst_id:
            add_move(signed, dst_id, player, NAME_BY_ID.get(src_id, src), "loan", "Loan", "signed")
        if src_id:
            add_move(left, src_id, player, NAME_BY_ID.get(dst_id, dst), "loan", "Loan", "left")


def sort_rows(rows: list[dict]) -> list[dict]:
    rank = {"fee": 0, "undisclosed": 1, "free": 2, "loan": 3, "other": 4, "released": 5, "retired": 6, "loan-ended": 7}
    return sorted(rows, key=lambda r: (rank.get(r.get("kind") or "", 9), r["player"].lower()))


def build() -> dict:
    signed: dict[str, list[dict]] = defaultdict(list)
    released: dict[str, list[dict]] = defaultdict(list)
    left: dict[str, list[dict]] = defaultdict(list)

    for name in (
        "bbc-deadline-2026.txt",
        "bbc-august-2026.txt",
        "bbc-july-2026.txt",
        "bbc-june-2026.txt",
        "bbc-feb-may-2026.txt",
        "bbc-done-deals.txt",
        "transfer-extras.txt",
    ):
        path = SRC / name
        if path.is_file():
            parse_bbc_deals(path.read_text(encoding="utf-8"), signed, released, left)

    for name in ("bbc-league-one-preview.txt", "bbc-league-two-preview.txt"):
        path = SRC / name
        if path.is_file():
            parse_season_preview(path.read_text(encoding="utf-8"), signed, released, left)

    scot = SRC / "bbc-scottish-prem-ins-outs.txt"
    if scot.is_file():
        parse_scottish_ins_outs(scot.read_text(encoding="utf-8"), signed, released, left)

    spfl = SRC / "spfl-summer-2026.txt"
    if spfl.is_file():
        parse_spfl(spfl.read_text(encoding="utf-8"), signed)

    wiki = SRC / "wikipedia-summer-2026.txt"
    if wiki.is_file():
        parse_wikipedia_loans(wiki.read_text(encoding="utf-8"), signed, left)

    for name in (
        "lowdown-championship-retained.txt",
        "lowdown-league-one-retained.txt",
        "lowdown-league-two-retained.txt",
        "lowdown-national-league-retained.txt",
        "lowdown-national-league-north-retained.txt",
        "lowdown-national-league-south-retained.txt",
        "retained-list-extras.txt",
    ):
        path = SRC / name
        if path.is_file():
            parse_retained_lists(path.read_text(encoding="utf-8"), released)

    attach_release_destinations(released, left)

    leagues = []
    for league_id, league_name in LEAGUES:
        teams = []
        for _league, club_id, club_name in CLUBS:
            if _league != league_id:
                continue
            ins = sort_rows(dedupe_rows(signed.get(club_id, [])))
            rel = sort_rows(dedupe_rows(released.get(club_id, [])))
            outs = sort_rows(dedupe_rows(left.get(club_id, [])))
            teams.append(
                {
                    "id": club_id,
                    "name": club_name,
                    "signed": ins,
                    "released": rel,
                    "left": outs,
                    "signed_count": len(ins),
                    "released_count": len(rel),
                    "left_count": len(outs),
                }
            )
        teams.sort(key=lambda t: t["name"])
        leagues.append(
            {
                "id": league_id,
                "name": league_name,
                "teams": teams,
                "signed_count": sum(t["signed_count"] for t in teams),
                "released_count": sum(t["released_count"] for t in teams),
            }
        )

    return {
        "title": "EFL Transfer Report",
        "season": "2026/27",
        "window": "Summer 2026 (15 June – 1/3 September)",
        "updated": "2026-09-08",
        "sources": [
            "BBC Sport done-deal lists (June–deadline day 2026)",
            "BBC League One and League Two 2026-27 club-by-club previews (key ins / released)",
            "BBC Scottish Premiership ins and outs — summer 2026",
            "Football Lowdown retained lists (Championship, League One, League Two, National League)",
            "SPFL confirmed Premiership arrivals",
            "Wikipedia summer 2026 loan table (EFL-touching deals)",
            "Confirmed extras the BBC / retained-list scrape missed",
        ],
        "notes": [
            "Released = club retained-list releases/retirements. A later free signing still counts as released.",
            "Signed = confirmed arrivals (permanent and loan) during the summer window.",
            "Transferred = sold or free to another club without a retained-list release. End of loan = returned to the parent club.",
            "National League retained lists cover last season’s NL / NL North / NL South clubs.",
            "January 2026 deadline-day deals are excluded.",
        ],
        "leagues": leagues,
    }


def main() -> None:
    payload = build()
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    teams = [t for league in payload["leagues"] for t in league["teams"]]
    print(f"Wrote {OUT} — {len(teams)} teams")
    for league in payload["leagues"]:
        print(f"  {league['name']}: {league['signed_count']} signed / {league['released_count']} released")
    vale = next(t for t in teams if t["id"] == "port-vale")
    print("Port Vale signed:", ", ".join(r["player"] for r in vale["signed"]) or "—")
    print("Port Vale released:", ", ".join(r["player"] for r in vale["released"]) or "—")
    print("Port Vale left:", ", ".join(r["player"] for r in vale["left"]) or "—")


if __name__ == "__main__":
    main()
