"""PORT VALE ARCHETYPES — the 3-5-2 / 3-4-3 position book.

Every position in the system gets a name, a job description, and a set of
player archetypes (Running 8, Ball-Winning 6, …). Each archetype is a weighted
blend of the Port Vale Impect profiles, and the page ranks the whole recruitment
pool against it.

The written copy and weights below are the defaults. Staff edits are saved as
overrides in DATA_ROOT, so a deploy never wipes them.
"""

from __future__ import annotations

import copy
import json
import logging
import threading
import time
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from app.paths import DATA_ROOT, STANDALONE_DIR, ensure_data_dirs

logger = logging.getLogger(__name__)

OVERRIDES_PATH = DATA_ROOT / "pv-archetypes.json"
_overrides_lock = threading.Lock()

POOL_TTL = 15 * 60
_pool_cache: tuple[float, dict[str, Any]] | None = None
_pool_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Impect PV profile names, exactly as the API spells them.
# ---------------------------------------------------------------------------

GK_SHOT = "PV - Shot Stopping Goal Keeper"
GK_BOX = "PV - Box Goalkeeper"
GK_SWEEP = "PV - SWEEPER KEEPER"
GK_BALL = "PV - Ball Playing Goal Keeper"

CB_AERIAL = "PV - AERIAL CB"
CB_PROG = "PV - BALL PROGRESSOR"
CB_CENTRAL = "PV - CENTRAL DUELER"
CB_LEFT = "PV - LEFT SIDE DUELER"
CB_RIGHT = "PV - RIGHT SIDE DUELER"

RB_DEEP = "PV - DEEP CREATOR (RB)"
RB_DEF = "PV - Defender (RB / RWB)"
RB_OFF = "PV - Offensive (RB/RWB)"

LB_DEEP = "PV - DEEP CREATOR (LB/LWB)"
LB_DEF = "PV - Defensive (LB/LWB)"
LB_OFF = "PV - Offensive (LB/LWB)"

MID_PROG = "PV - BALL PROGRESSOR - (10)"
MID_WIN = "PV - BALL WINNER (CM)"
MID_CREATE = "PV - CREATOR (CM)"
MID_GOAL = "PV - GOAL THREAT - (CM)"
MID_RUN = "PV - RUNNING THREAT (CM)"
AM_WIN = "PV #10 - BALL WINNER"

RW_CARRY = "PV - BALL CARRIER (RW)"
RW_CREATE = "PV - Wide Creator (RW)"
RW_GOAL = "PV - WIDE GOAL THREAT - (RW)"
LW_CARRY = "PV - Ball Carrier - LEFT"
LW_CREATE = "PV - Wide Creator LEFT"
LW_GOAL = "PV - Goal Threat - Left"
W_PRESS = "PV - PRESSER - (WINGER)"

ST_GOAL = "PV - GOAL THREAT"
ST_HOLD = "PV - HOLD UP - (ST)"
ST_LINK = "PV - LINK / DEEP PLAY MAKER - (ST)"
ST_PRESS = "PV - PRESSER (ST)"
ST_BEHIND = "PV - THREAT IN BEHIND (ST)"

PROFILE_LABELS: dict[str, str] = {
    GK_SHOT: "Shot stopping",
    GK_BOX: "Box control",
    GK_SWEEP: "Sweeping",
    GK_BALL: "Ball playing",
    CB_AERIAL: "Aerial",
    CB_PROG: "Ball progression",
    CB_CENTRAL: "Central duels",
    CB_LEFT: "Left-side duels",
    CB_RIGHT: "Right-side duels",
    RB_DEEP: "Deep creating",
    RB_DEF: "Defending",
    RB_OFF: "Attacking",
    LB_DEEP: "Deep creating",
    LB_DEF: "Defending",
    LB_OFF: "Attacking",
    MID_PROG: "Ball progression",
    MID_WIN: "Ball winning",
    MID_CREATE: "Creating",
    MID_GOAL: "Goal threat",
    MID_RUN: "Running threat",
    AM_WIN: "Ball winning (10)",
    RW_CARRY: "Ball carrying",
    RW_CREATE: "Wide creating",
    RW_GOAL: "Goal threat",
    LW_CARRY: "Ball carrying",
    LW_CREATE: "Wide creating",
    LW_GOAL: "Goal threat",
    W_PRESS: "Pressing",
    ST_GOAL: "Goal threat",
    ST_HOLD: "Hold-up",
    ST_LINK: "Link play",
    ST_PRESS: "Pressing",
    ST_BEHIND: "Threat in behind",
}

# Impect positions whose profile sets an archetype can read.
POSITION_PROFILES: dict[str, tuple[str, ...]] = {
    "GOALKEEPER": (GK_SHOT, GK_BOX, GK_SWEEP, GK_BALL),
    "CENTRAL_DEFENDER": (CB_AERIAL, CB_PROG, CB_CENTRAL, CB_LEFT, CB_RIGHT),
    "RIGHT_WINGBACK_DEFENDER": (RB_DEEP, RB_DEF, RB_OFF),
    "LEFT_WINGBACK_DEFENDER": (LB_DEEP, LB_DEF, LB_OFF),
    "DEFENSE_MIDFIELD": (MID_PROG, MID_WIN, MID_CREATE, MID_GOAL, MID_RUN),
    "CENTRAL_MIDFIELD": (MID_PROG, MID_WIN, MID_CREATE, MID_GOAL, MID_RUN),
    "ATTACKING_MIDFIELD": (AM_WIN, MID_PROG, MID_CREATE, MID_GOAL),
    "RIGHT_WINGER": (RW_CARRY, W_PRESS, RW_CREATE, RW_GOAL),
    "LEFT_WINGER": (LW_CARRY, W_PRESS, LW_CREATE, LW_GOAL),
    "CENTER_FORWARD": (ST_GOAL, ST_HOLD, ST_LINK, ST_PRESS, ST_BEHIND),
}

IMPECT_POSITION_LABELS: dict[str, str] = {
    "GOALKEEPER": "Goalkeeper",
    "CENTRAL_DEFENDER": "Centre-back",
    "RIGHT_WINGBACK_DEFENDER": "Right back / wing-back",
    "LEFT_WINGBACK_DEFENDER": "Left back / wing-back",
    "DEFENSE_MIDFIELD": "Defensive midfield",
    "CENTRAL_MIDFIELD": "Central midfield",
    "ATTACKING_MIDFIELD": "Attacking midfield",
    "RIGHT_WINGER": "Right winger",
    "LEFT_WINGER": "Left winger",
    "CENTER_FORWARD": "Centre-forward",
}

MIDFIELD = ("DEFENSE_MIDFIELD", "CENTRAL_MIDFIELD")


def _arch(
    arch_id: str,
    name: str,
    tagline: str,
    description: str,
    sources: tuple[str, ...],
    weights: dict[str, float],
    traits: list[str],
    *,
    foot: str | None = None,
) -> dict[str, Any]:
    return {
        "id": arch_id,
        "name": name,
        "tagline": tagline,
        "description": description,
        "sources": list(sources),
        "weights": dict(weights),
        "traits": list(traits),
        "foot": foot,
    }


# ---------------------------------------------------------------------------
# The position book.
# ---------------------------------------------------------------------------

DEFAULT_ROLES: list[dict[str, Any]] = [
    {
        "id": "gk",
        "number": "1",
        "short": "GK",
        "name": "Goalkeeper",
        "nickname": "The Sweeper-Keeper",
        "importance": 4,
        "importance_note": (
            "With three centre-backs and wing-backs pushed on, the space behind our line is "
            "the keeper's to defend. He is also our spare man in build-up — a 4v3 against a "
            "front three that sets every possession."
        ),
        "summary": (
            "Starts our attacks, protects the space behind a high back three, and wins the "
            "points the outfield can't. Has to be calm with the ball under pressure."
        ),
        "in_possession": [
            "Spare man in build-up — splits the back three and plays through the first line",
            "Finds the 6 or the wide centre-backs on the half-turn, not just long",
            "Accurate early distribution to wing-backs and strikers when the press breaks",
        ],
        "out_of_possession": [
            "Starts high — sweeps balls played in behind the back three",
            "Commands the six-yard box on crosses and set plays",
            "Organises the back five's height and distances",
        ],
        "requirements": [
            "Two-footed enough to play under pressure",
            "Starting position 15–20 yards off the line in settled possession",
            "Elite shot stopping — still the job before anything else",
            "Voice: organises the back five",
        ],
        "archetypes": [
            _arch(
                "gk-sweeper",
                "Sweeper Keeper",
                "Defends the space behind a high line",
                "Proactive, starts high, reads balls in behind before they arrive. The ideal "
                "keeper for an aggressive back three.",
                ("GOALKEEPER",),
                {GK_SWEEP: 5, GK_BALL: 3, GK_SHOT: 2},
                ["Starting position", "Reads through-balls", "Comfortable 1v1 off his line"],
            ),
            _arch(
                "gk-ball",
                "Ball-Playing Keeper",
                "Our spare man in build-up",
                "Plays like an eleventh outfielder — breaks the first press line with passes "
                "into the 6 and the wide centre-backs.",
                ("GOALKEEPER",),
                {GK_BALL: 6, GK_SWEEP: 2, GK_SHOT: 2},
                ["Press-resistant", "Line-breaking passes", "Both feet"],
            ),
            _arch(
                "gk-shot",
                "Shot Stopper",
                "Wins points on his own",
                "Pure goal prevention. Saves more than the xG says he should and makes the "
                "big save at big moments.",
                ("GOALKEEPER",),
                {GK_SHOT: 7, GK_BOX: 3},
                ["Reflexes", "Set position", "Saves above expected"],
            ),
            _arch(
                "gk-box",
                "Box Commander",
                "Owns the six-yard box",
                "Dominant on crosses and set plays — takes pressure off the back three when "
                "teams go direct.",
                ("GOALKEEPER",),
                {GK_BOX: 6, GK_SHOT: 4},
                ["Claims crosses", "Set-play presence", "Organiser"],
            ),
        ],
    },
    {
        "id": "rcb",
        "number": "2",
        "short": "RCB",
        "name": "Right Centre-Back",
        "nickname": "The Right Stopper",
        "importance": 4,
        "importance_note": (
            "When the right wing-back is high he defends the channel on his own. He is also "
            "our second build-up player — if he can step in with the ball, we overload "
            "midfield."
        ),
        "summary": (
            "Defends the right channel when the wing-back is high, steps in with the ball to "
            "create an extra midfielder, and wins duels on his side."
        ),
        "in_possession": [
            "Splits wide in build-up and carries into midfield when space opens",
            "Breaks lines with passes into the 8 and the right-sided striker",
            "Supports the wing-back with underlaps in the final third",
        ],
        "out_of_possession": [
            "Defends the right channel 1v1 when the wing-back is caught high",
            "Steps out aggressively onto their left-sided 10 / winger",
            "Covers across behind the central centre-back",
        ],
        "requirements": [
            "Comfortable defending wide areas — mobility over pure size",
            "Wins duels on the right side",
            "Can carry the ball 20 yards into midfield",
            "Right-footed preferred",
        ],
        "archetypes": [
            _arch(
                "rcb-stepping",
                "Stepping Centre-Back",
                "Carries into midfield, creates the overload",
                "A centre-back who travels with the ball. Steps into the space in front of him "
                "and gives us a 4v3 in midfield.",
                ("CENTRAL_DEFENDER",),
                {CB_PROG: 5, CB_RIGHT: 4, CB_CENTRAL: 1},
                ["Carries forward", "Line-breaking passes", "Duels on the right"],
                foot="R",
            ),
            _arch(
                "rcb-stopper",
                "Front-Foot Stopper",
                "Aggressive, wins it on the right",
                "Defends forwards, steps out onto the 10 and wins the ball back before it "
                "reaches our box.",
                ("CENTRAL_DEFENDER",),
                {CB_RIGHT: 6, CB_CENTRAL: 2, CB_AERIAL: 2},
                ["Aggressive", "Wins duels high", "Recovers fast"],
                foot="R",
            ),
            _arch(
                "rcb-fullback",
                "Converted Full-Back",
                "Defends wide spaces like a full-back",
                "A full-back who tucks in. Mobile in the channel, comfortable wide, and "
                "naturally overlaps when we have the ball.",
                ("RIGHT_WINGBACK_DEFENDER",),
                {RB_DEF: 6, RB_DEEP: 4},
                ["Mobility", "Wide 1v1 defending", "Overlaps"],
            ),
        ],
    },
    {
        "id": "ccb",
        "number": "5",
        "short": "CCB",
        "name": "Central Centre-Back",
        "nickname": "The Commander",
        "importance": 5,
        "importance_note": (
            "The spine of the back three. Every cross, every long ball and every set play "
            "against us goes through him. He also holds the line's height."
        ),
        "summary": (
            "Organises the line, attacks every ball in our box, and gives the side "
            "centre-backs the freedom to step out."
        ),
        "in_possession": [
            "Calm deepest outfield option — switches play side to side",
            "Breaks the first line with passes into the 6",
            "Rest defence: stays connected while the wide centre-backs advance",
        ],
        "out_of_possession": [
            "Dominates the box — first contact on crosses and set plays",
            "Covers behind the side centre-backs when they step out",
            "Leads and holds the line's height",
        ],
        "requirements": [
            "Dominant in the air in both boxes",
            "Leader and organiser — sets the line",
            "Wins central duels against a lone striker",
            "Comfortable receiving under pressure from the keeper",
        ],
        "archetypes": [
            _arch(
                "ccb-commander",
                "Aerial Commander",
                "Owns the box",
                "Wins every header in our box, organises the back five, and is a set-play "
                "threat at the other end.",
                ("CENTRAL_DEFENDER",),
                {CB_AERIAL: 5, CB_CENTRAL: 4, CB_PROG: 1},
                ["Aerial dominance", "Leader", "Set-play threat"],
            ),
            _arch(
                "ccb-libero",
                "Ball-Playing Libero",
                "Our quarterback from the back",
                "Starts every attack. Switches play, breaks lines, and is still sound enough "
                "defensively to hold the middle.",
                ("CENTRAL_DEFENDER",),
                {CB_PROG: 6, CB_CENTRAL: 3, CB_AERIAL: 1},
                ["Switches play", "Line-breaking passes", "Calm under pressure"],
            ),
            _arch(
                "ccb-stopper",
                "Central Stopper",
                "Wins his battle with the 9",
                "Physical, aggressive and relentless against a lone striker. Wins the ball "
                "in front of him and in the air.",
                ("CENTRAL_DEFENDER",),
                {CB_CENTRAL: 6, CB_AERIAL: 4},
                ["Ground duels", "Aerial duels", "Physical"],
            ),
        ],
    },
    {
        "id": "lcb",
        "number": "6",
        "short": "LCB",
        "name": "Left Centre-Back",
        "nickname": "The Left-Footed Builder",
        "importance": 4,
        "importance_note": (
            "A left-footer opens the pitch. He can play down the line to the wing-back and "
            "switch the game without turning back inside — half a second we never get back "
            "with a right-footer."
        ),
        "summary": (
            "Builds on the left with his natural foot, defends the left channel when the "
            "wing-back is high, and wins duels on his side."
        ),
        "in_possession": [
            "Left foot opens the angle to the wing-back and the left striker",
            "Carries into midfield to create the overload",
            "Switches play to the right wing-back",
        ],
        "out_of_possession": [
            "Defends the left channel 1v1 when the wing-back is caught high",
            "Steps out onto their right-sided 10 / winger",
            "Covers across behind the central centre-back",
        ],
        "requirements": [
            "Left-footed — strongly preferred",
            "Wins duels on the left side",
            "Comfortable defending wide areas",
            "Breaks lines with the left foot",
        ],
        "archetypes": [
            _arch(
                "lcb-builder",
                "Left-Footed Builder",
                "Opens the pitch with his left foot",
                "Ball-playing left centre-back. Plays down the line, switches the game, and "
                "carries into midfield.",
                ("CENTRAL_DEFENDER",),
                {CB_PROG: 5, CB_LEFT: 4, CB_CENTRAL: 1},
                ["Left foot", "Line-breaking passes", "Carries forward"],
                foot="L",
            ),
            _arch(
                "lcb-destroyer",
                "Left-Side Destroyer",
                "Wins every duel on the left",
                "Aggressive, front-foot defender who wins the ball on his side and in the air.",
                ("CENTRAL_DEFENDER",),
                {CB_LEFT: 6, CB_AERIAL: 2, CB_CENTRAL: 2},
                ["Aggressive", "Duels", "Aerial"],
                foot="L",
            ),
            _arch(
                "lcb-fullback",
                "Converted Left-Back",
                "Mobility and a natural left foot",
                "A left-back who tucks in. Defends wide spaces naturally and is comfortable "
                "on the ball under pressure.",
                ("LEFT_WINGBACK_DEFENDER",),
                {LB_DEF: 6, LB_DEEP: 4},
                ["Mobility", "Wide 1v1 defending", "Left foot"],
            ),
        ],
    },
    {
        "id": "rwb",
        "number": "7",
        "short": "RWB",
        "name": "Right Wing-Back",
        "nickname": "The Right Engine",
        "importance": 5,
        "importance_note": (
            "In a back three the wing-backs are our only natural width. They decide whether "
            "we attack with five or defend with five — the most physically demanding job in "
            "the system."
        ),
        "summary": (
            "Owns the whole right touchline. Gives us width in attack, delivers into the box, "
            "and recovers to make a back five without the ball."
        ),
        "in_possession": [
            "Holds width high and wide — pins their full-back",
            "Delivers early crosses and cut-backs for two strikers",
            "Arrives at the back post when the ball is on the left",
        ],
        "out_of_possession": [
            "Recovers to form a back five",
            "Jumps to press their full-back when we press high",
            "Wins 1v1s against their winger",
        ],
        "requirements": [
            "Elite repeat-sprint engine — up and down for 90 minutes",
            "Quality delivery from wide",
            "Defends 1v1 against a winger",
            "Right-footed preferred",
        ],
        "archetypes": [
            _arch(
                "rwb-flyer",
                "Attacking Wing-Back",
                "A winger who defends",
                "Lives in the final third. Beats his man, gets to the byline, and delivers.",
                ("RIGHT_WINGBACK_DEFENDER",),
                {RB_OFF: 7, RB_DEEP: 3},
                ["Delivery", "1v1 attacking", "Final-third volume"],
            ),
            _arch(
                "rwb-engine",
                "Two-Way Wing-Back",
                "Box to box on the touchline",
                "Equally good at both ends. Gives us balance when the opposite wing-back is "
                "more attacking.",
                ("RIGHT_WINGBACK_DEFENDER",),
                {RB_OFF: 4, RB_DEF: 4, RB_DEEP: 2},
                ["Engine", "Balance", "Recovery runs"],
            ),
            _arch(
                "rwb-lock",
                "Defensive Wing-Back",
                "Locks down the right side",
                "Defends first. Solid against wingers and turns a back three into a back five "
                "without thinking.",
                ("RIGHT_WINGBACK_DEFENDER",),
                {RB_DEF: 7, RB_OFF: 3},
                ["1v1 defending", "Positioning", "Discipline"],
            ),
            _arch(
                "rwb-winger",
                "Converted Winger",
                "Maximum threat from wide",
                "A right winger moved back a line. Elite carrying and creating, with the "
                "engine to get back.",
                ("RIGHT_WINGER",),
                {RW_CREATE: 4, RW_CARRY: 3, W_PRESS: 3},
                ["Ball carrying", "Creating", "Pressing"],
            ),
        ],
    },
    {
        "id": "lwb",
        "number": "3",
        "short": "LWB",
        "name": "Left Wing-Back",
        "nickname": "The Left Engine",
        "importance": 5,
        "importance_note": (
            "Our only natural width on the left. A left-footed wing-back who can deliver "
            "takes us from a crossing team to a chance-creating team."
        ),
        "summary": (
            "Owns the whole left touchline. Gives us width in attack, delivers into the box, "
            "and recovers to make a back five without the ball."
        ),
        "in_possession": [
            "Holds width high and wide — pins their full-back",
            "Delivers early crosses and cut-backs for two strikers",
            "Arrives at the back post when the ball is on the right",
        ],
        "out_of_possession": [
            "Recovers to form a back five",
            "Jumps to press their full-back when we press high",
            "Wins 1v1s against their winger",
        ],
        "requirements": [
            "Elite repeat-sprint engine — up and down for 90 minutes",
            "Quality delivery with the left foot",
            "Defends 1v1 against a winger",
            "Left-footed strongly preferred",
        ],
        "archetypes": [
            _arch(
                "lwb-flyer",
                "Attacking Wing-Back",
                "A winger who defends",
                "Lives in the final third. Beats his man, gets to the byline, and delivers.",
                ("LEFT_WINGBACK_DEFENDER",),
                {LB_OFF: 7, LB_DEEP: 3},
                ["Delivery", "1v1 attacking", "Final-third volume"],
                foot="L",
            ),
            _arch(
                "lwb-engine",
                "Two-Way Wing-Back",
                "Box to box on the touchline",
                "Equally good at both ends. Gives us balance when the opposite wing-back is "
                "more attacking.",
                ("LEFT_WINGBACK_DEFENDER",),
                {LB_OFF: 4, LB_DEF: 4, LB_DEEP: 2},
                ["Engine", "Balance", "Recovery runs"],
                foot="L",
            ),
            _arch(
                "lwb-lock",
                "Defensive Wing-Back",
                "Locks down the left side",
                "Defends first. Solid against wingers and turns a back three into a back five "
                "without thinking.",
                ("LEFT_WINGBACK_DEFENDER",),
                {LB_DEF: 7, LB_OFF: 3},
                ["1v1 defending", "Positioning", "Discipline"],
                foot="L",
            ),
            _arch(
                "lwb-winger",
                "Converted Winger",
                "Maximum threat from wide",
                "A left winger moved back a line. Elite carrying and creating, with the "
                "engine to get back.",
                ("LEFT_WINGER",),
                {LW_CREATE: 4, LW_CARRY: 3, W_PRESS: 3},
                ["Ball carrying", "Creating", "Pressing"],
            ),
        ],
    },
    {
        "id": "six",
        "number": "4",
        "short": "6",
        "name": "Number 6",
        "nickname": "The Screen",
        "importance": 5,
        "importance_note": (
            "The link between the back three and everything in front of it. Protects the "
            "back three in transition and turns defence into attack — if the 6 can't play "
            "forward, nothing moves."
        ),
        "summary": (
            "Screens the back three, wins the second balls, and is the first pass forward "
            "in build-up."
        ),
        "in_possession": [
            "Shows for the ball in front of the back three — first pass forward",
            "Plays on the half-turn and switches play",
            "Stays behind the ball as rest defence",
        ],
        "out_of_possession": [
            "Screens the middle in front of the back three",
            "Wins second balls and stops counter-attacks early",
            "Steps up onto their 10 when we press",
        ],
        "requirements": [
            "Positional discipline — never caught upfield",
            "Ball winner: tackles, interceptions, second balls",
            "Press-resistant — plays out of tight spaces",
            "Breaks lines with passing",
        ],
        "archetypes": [
            _arch(
                "six-winner",
                "Ball-Winning 6",
                "Destroyer in front of the back three",
                "Wins the ball back, stops transitions, and gives it simply. Our insurance "
                "policy.",
                MIDFIELD,
                {MID_WIN: 8, MID_PROG: 2},
                ["Tackles", "Interceptions", "Second balls"],
            ),
            _arch(
                "six-regista",
                "Deep-Lying Playmaker",
                "Dictates tempo from deep",
                "The quarterback. Receives on the half-turn, breaks lines, switches play. "
                "Needs runners around him.",
                MIDFIELD,
                {MID_PROG: 5, MID_CREATE: 3, MID_WIN: 2},
                ["Line-breaking passes", "Press-resistant", "Tempo"],
            ),
            _arch(
                "six-anchor",
                "Two-Way Anchor",
                "Wins it and plays it",
                "Balanced 6 — wins his duels and progresses the ball. Fits any midfield pairing.",
                MIDFIELD,
                {MID_WIN: 5, MID_PROG: 5},
                ["Balance", "Duels", "Progression"],
            ),
        ],
    },
    {
        "id": "eight",
        "number": "8",
        "short": "8",
        "name": "Number 8",
        "nickname": "The Engine Room",
        "importance": 4,
        "importance_note": (
            "In a 3-5-2 the two 8s cover the width the wingers would. They press, run "
            "beyond the strikers, and decide whether we dominate the middle. In a 3-4-3 the "
            "8 is the box-to-box partner to the 6."
        ),
        "summary": (
            "Covers ground in both directions — presses, arrives in the box, and links the "
            "6 to the front line."
        ),
        "in_possession": [
            "Runs beyond the strikers into the channels",
            "Arrives late in the box for cut-backs",
            "Receives between the lines and plays forward",
        ],
        "out_of_possession": [
            "Jumps to press their 6 / centre-backs",
            "Shuffles across to cover the wing-back's channel",
            "Wins second balls off our strikers' flick-ons",
        ],
        "requirements": [
            "High work rate — high distance and sprint counts",
            "Contributes goals or assists from midfield",
            "Presses with intensity",
            "Secure in possession",
        ],
        "archetypes": [
            _arch(
                "eight-running",
                "Running 8",
                "Box to box, beyond the strikers",
                "Endless running both ways. Breaks into the box, gets beyond the front two, "
                "and gets back.",
                MIDFIELD,
                {MID_RUN: 6, MID_WIN: 2, MID_GOAL: 2},
                ["Runs in behind", "Engine", "Box arrivals"],
            ),
            _arch(
                "eight-destructive",
                "Destructive 8",
                "Wins it high and keeps winning it",
                "Aggressive presser who wins the ball in the opposition half and starts "
                "attacks from there.",
                MIDFIELD,
                {MID_WIN: 7, MID_RUN: 3},
                ["Counter-press", "Duels", "Intensity"],
            ),
            _arch(
                "eight-creative",
                "Creative 8",
                "Unlocks the block",
                "Finds the strikers between the lines and creates chances from the half-spaces.",
                MIDFIELD,
                {MID_CREATE: 6, MID_PROG: 4},
                ["Final pass", "Receives between lines", "Vision"],
            ),
            _arch(
                "eight-goal",
                "Arriving 8",
                "Goals from midfield",
                "Times his runs into the box and finishes. The difference between a front "
                "two and a front three.",
                MIDFIELD,
                {MID_GOAL: 6, MID_RUN: 4},
                ["Box arrivals", "Finishing", "Timing"],
            ),
        ],
    },
    {
        "id": "rif",
        "number": "11",
        "short": "RIF",
        "name": "Right Inside Forward",
        "nickname": "The Right Ten",
        "importance": 4,
        "importance_note": (
            "In the 3-4-3 the wing-back holds the width, so the inside forward plays in the "
            "right half-space. He is the main source of chances and goals beside the 9."
        ),
        "summary": (
            "Lives in the right half-space between their full-back and centre-back — "
            "receives, turns, and creates or scores."
        ),
        "in_possession": [
            "Receives in the half-space between the lines",
            "Combines with the wing-back outside him",
            "Attacks the box at the back post / arrives for cut-backs",
        ],
        "out_of_possession": [
            "Presses their left centre-back and screens the pass into their full-back",
            "Tucks in to make a front-three press",
            "Counter-presses straight after losing it",
        ],
        "requirements": [
            "Receives on the half-turn in tight spaces",
            "Goal threat — 8+ goals a season",
            "Beats a man / carries the ball",
            "Presses from the front",
        ],
        "archetypes": [
            _arch(
                "rif-goal",
                "Goal-Threat Inside Forward",
                "Cuts in and scores",
                "Gets into the box and finishes. The second striker of the front three.",
                ("RIGHT_WINGER",),
                {RW_GOAL: 6, RW_CARRY: 4},
                ["Finishing", "Box movement", "Ball carrying"],
            ),
            _arch(
                "rif-creator",
                "Half-Space Creator",
                "The final ball",
                "Drifts inside, receives between the lines, and puts the 9 through.",
                ("RIGHT_WINGER",),
                {RW_CREATE: 6, RW_CARRY: 4},
                ["Final pass", "Receives between lines", "Vision"],
            ),
            _arch(
                "rif-presser",
                "Pressing Forward",
                "Leads the press from the right",
                "Relentless off the ball and dangerous on it — wins it high and attacks "
                "straight away.",
                ("RIGHT_WINGER",),
                {W_PRESS: 6, RW_GOAL: 4},
                ["Pressing", "Transition", "Work rate"],
            ),
            _arch(
                "rif-ten",
                "Pocket 10",
                "A true 10 playing off the right",
                "An attacking midfielder who lives between the lines and links play with the "
                "9 and the 8.",
                ("ATTACKING_MIDFIELD",),
                {MID_CREATE: 5, MID_PROG: 3, MID_GOAL: 2},
                ["Between the lines", "Final pass", "Combination play"],
            ),
        ],
    },
    {
        "id": "lif",
        "number": "10",
        "short": "LIF",
        "name": "Left Inside Forward",
        "nickname": "The Left Ten",
        "importance": 4,
        "importance_note": (
            "In the 3-4-3 the wing-back holds the width, so the inside forward plays in the "
            "left half-space. He is the main source of chances and goals beside the 9."
        ),
        "summary": (
            "Lives in the left half-space between their full-back and centre-back — receives, "
            "turns, and creates or scores."
        ),
        "in_possession": [
            "Receives in the half-space between the lines",
            "Combines with the wing-back outside him",
            "Attacks the box at the back post / arrives for cut-backs",
        ],
        "out_of_possession": [
            "Presses their right centre-back and screens the pass into their full-back",
            "Tucks in to make a front-three press",
            "Counter-presses straight after losing it",
        ],
        "requirements": [
            "Receives on the half-turn in tight spaces",
            "Goal threat — 8+ goals a season",
            "Beats a man / carries the ball",
            "Presses from the front",
        ],
        "archetypes": [
            _arch(
                "lif-goal",
                "Goal-Threat Inside Forward",
                "Cuts in and scores",
                "Gets into the box and finishes. The second striker of the front three.",
                ("LEFT_WINGER",),
                {LW_GOAL: 6, LW_CARRY: 4},
                ["Finishing", "Box movement", "Ball carrying"],
            ),
            _arch(
                "lif-creator",
                "Half-Space Creator",
                "The final ball",
                "Drifts inside, receives between the lines, and puts the 9 through.",
                ("LEFT_WINGER",),
                {LW_CREATE: 6, LW_CARRY: 4},
                ["Final pass", "Receives between lines", "Vision"],
            ),
            _arch(
                "lif-presser",
                "Pressing Forward",
                "Leads the press from the left",
                "Relentless off the ball and dangerous on it — wins it high and attacks "
                "straight away.",
                ("LEFT_WINGER",),
                {W_PRESS: 6, LW_GOAL: 4},
                ["Pressing", "Transition", "Work rate"],
            ),
            _arch(
                "lif-ten",
                "Pocket 10",
                "A true 10 playing off the left",
                "An attacking midfielder who lives between the lines and links play with the "
                "9 and the 8.",
                ("ATTACKING_MIDFIELD",),
                {MID_CREATE: 5, MID_PROG: 3, MID_GOAL: 2},
                ["Between the lines", "Final pass", "Combination play"],
            ),
        ],
    },
    {
        "id": "nine",
        "number": "9",
        "short": "9",
        "name": "Striker",
        "nickname": "The Spearhead",
        "importance": 5,
        "importance_note": (
            "Goals win promotion. In a 3-5-2 we want a complementary pair (one runs, one "
            "holds); in a 3-4-3 the lone 9 has to do both and press from the front."
        ),
        "summary": (
            "Scores goals, leads the press, and gives the team an outlet — together with his "
            "strike partner in the 3-5-2."
        ),
        "in_possession": [
            "Scores — penalty-box movement and finishing",
            "Pins the centre-backs and stretches the line",
            "Holds it up / links play so the 8s and wing-backs can arrive",
        ],
        "out_of_possession": [
            "Leads the press — curves runs to show them where we want",
            "Screens the pass into their 6",
            "Defends set plays",
        ],
        "requirements": [
            "Goal threat — 15+ goal potential",
            "Complements his partner (3-5-2): runner + holder",
            "Presses with intensity",
            "Penalty-box instinct",
        ],
        "archetypes": [
            _arch(
                "nine-poacher",
                "Penalty-Box Poacher",
                "Lives for the box",
                "Pure finisher. Movement across the near post, first to the rebound — all "
                "about goals.",
                ("CENTER_FORWARD",),
                {ST_GOAL: 8, ST_BEHIND: 2},
                ["Finishing", "Box movement", "Instinct"],
            ),
            _arch(
                "nine-runner",
                "Runner in Behind",
                "Stretches the line",
                "Pace and timing in behind. Turns the opposition back line and opens space for "
                "everyone else.",
                ("CENTER_FORWARD",),
                {ST_BEHIND: 6, ST_GOAL: 4},
                ["Runs in behind", "Pace", "Finishing"],
            ),
            _arch(
                "nine-target",
                "Target Man",
                "The outlet",
                "Holds it up, wins the first ball and brings the 8s and wing-backs into play. "
                "Perfect partner for a runner.",
                ("CENTER_FORWARD",),
                {ST_HOLD: 6, ST_GOAL: 4},
                ["Hold-up", "Aerial", "Brings others in"],
            ),
            _arch(
                "nine-presser",
                "Pressing Forward",
                "First defender",
                "Sets the press, forces mistakes high up the pitch, and turns them into chances.",
                ("CENTER_FORWARD",),
                {ST_PRESS: 6, ST_GOAL: 2, ST_BEHIND: 2},
                ["Pressing", "Work rate", "Transition"],
            ),
            _arch(
                "nine-link",
                "Link Forward",
                "Drops in and plays",
                "A false 9 / deep playmaker. Drops off, connects play, and creates for the "
                "runners around him.",
                ("CENTER_FORWARD",),
                {ST_LINK: 6, ST_GOAL: 2, ST_HOLD: 2},
                ["Link play", "Vision", "Drops deep"],
            ),
        ],
    },
]

# Vertical pitch — x across (0 = left touchline), y up the pitch (0 = our goal line).
FORMATIONS: list[dict[str, Any]] = [
    {
        "id": "352",
        "label": "3-5-2",
        "note": "Two strikers, two 8s, wing-backs give all the width.",
        "slots": [
            {"slot": "gk", "role": "gk", "x": 50, "y": 13},
            {"slot": "lcb", "role": "lcb", "x": 22, "y": 29},
            {"slot": "ccb", "role": "ccb", "x": 50, "y": 26},
            {"slot": "rcb", "role": "rcb", "x": 78, "y": 29},
            {"slot": "lwb", "role": "lwb", "x": 15, "y": 57},
            {"slot": "six", "role": "six", "x": 50, "y": 45},
            {"slot": "rwb", "role": "rwb", "x": 85, "y": 57},
            {"slot": "l8", "role": "eight", "x": 33, "y": 66},
            {"slot": "r8", "role": "eight", "x": 67, "y": 66},
            {"slot": "l9", "role": "nine", "x": 35, "y": 88},
            {"slot": "r9", "role": "nine", "x": 65, "y": 88},
        ],
    },
    {
        "id": "343",
        "label": "3-4-3",
        "note": "A 6 + 8 pivot, two inside forwards in the half-spaces, a lone 9.",
        "slots": [
            {"slot": "gk", "role": "gk", "x": 50, "y": 13},
            {"slot": "lcb", "role": "lcb", "x": 22, "y": 29},
            {"slot": "ccb", "role": "ccb", "x": 50, "y": 26},
            {"slot": "rcb", "role": "rcb", "x": 78, "y": 29},
            {"slot": "lwb", "role": "lwb", "x": 15, "y": 58},
            {"slot": "six", "role": "six", "x": 37, "y": 47},
            {"slot": "eight", "role": "eight", "x": 63, "y": 53},
            {"slot": "rwb", "role": "rwb", "x": 85, "y": 58},
            {"slot": "lif", "role": "lif", "x": 27, "y": 77},
            {"slot": "rif", "role": "rif", "x": 73, "y": 77},
            {"slot": "nine", "role": "nine", "x": 50, "y": 89},
        ],
    },
]

# Squad plots: who each role is compared against, and the two axes it opens on.
ROLE_PLOTS: dict[str, dict[str, Any]] = {
    "gk": {"population": ["GOALKEEPER"], "x": GK_SHOT, "y": GK_BALL},
    "rcb": {"population": ["CENTRAL_DEFENDER"], "x": CB_RIGHT, "y": CB_PROG},
    "ccb": {"population": ["CENTRAL_DEFENDER"], "x": CB_AERIAL, "y": CB_PROG},
    "lcb": {"population": ["CENTRAL_DEFENDER"], "x": CB_LEFT, "y": CB_PROG},
    "rwb": {"population": ["RIGHT_WINGBACK_DEFENDER"], "x": RB_DEF, "y": RB_OFF},
    "lwb": {"population": ["LEFT_WINGBACK_DEFENDER"], "x": LB_DEF, "y": LB_OFF},
    "six": {"population": list(MIDFIELD), "x": MID_WIN, "y": MID_PROG},
    "eight": {"population": list(MIDFIELD), "x": MID_RUN, "y": MID_CREATE},
    "rif": {"population": ["RIGHT_WINGER"], "x": RW_GOAL, "y": RW_CREATE},
    "lif": {"population": ["LEFT_WINGER"], "x": LW_GOAL, "y": LW_CREATE},
    "nine": {"population": ["CENTER_FORWARD"], "x": ST_BEHIND, "y": ST_HOLD},
}

EDITABLE_ROLE_FIELDS = (
    "name",
    "nickname",
    "importance",
    "importance_note",
    "summary",
    "in_possession",
    "out_of_possession",
    "requirements",
)
EDITABLE_ARCH_FIELDS = ("name", "tagline", "description", "traits", "weights")


# ---------------------------------------------------------------------------
# Overrides (staff edits)
# ---------------------------------------------------------------------------


def _load_overrides() -> dict[str, Any]:
    try:
        if not OVERRIDES_PATH.exists():
            return {}
        raw = json.loads(OVERRIDES_PATH.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:  # noqa: BLE001
        logger.exception("Could not read archetype overrides")
        return {}


def _clean_text(value: Any, limit: int = 1200) -> str:
    return str(value or "").strip()[:limit]


def _clean_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_clean_text(item, 300) for item in value if _clean_text(item, 300)][:12]


def _clean_weights(value: Any, allowed: set[str]) -> dict[str, float]:
    if not isinstance(value, dict):
        return {}
    weights: dict[str, float] = {}
    for key, raw in value.items():
        if key not in allowed:
            continue
        try:
            number = float(raw)
        except (TypeError, ValueError):
            continue
        weights[key] = max(0.0, min(10.0, round(number, 1)))
    return weights


def archetype_profiles(arch: dict[str, Any]) -> list[str]:
    """Profiles every source position shares — the only ones a weight can use."""
    sets = [set(POSITION_PROFILES.get(src, ())) for src in arch.get("sources") or []]
    if not sets:
        return []
    shared = set.intersection(*sets)
    first = POSITION_PROFILES.get(arch["sources"][0], ())
    return [name for name in first if name in shared]


def apply_overrides(roles: list[dict[str, Any]], overrides: dict[str, Any]) -> list[dict[str, Any]]:
    merged = copy.deepcopy(roles)
    role_edits = overrides.get("roles") if isinstance(overrides.get("roles"), dict) else {}
    arch_edits = overrides.get("archetypes") if isinstance(overrides.get("archetypes"), dict) else {}
    for role in merged:
        edit = role_edits.get(role["id"]) or {}
        for field in EDITABLE_ROLE_FIELDS:
            if field not in edit:
                continue
            if field in {"in_possession", "out_of_possession", "requirements"}:
                role[field] = _clean_list(edit[field])
            elif field == "importance":
                try:
                    role[field] = max(1, min(5, int(edit[field])))
                except (TypeError, ValueError):
                    pass
            else:
                role[field] = _clean_text(edit[field]) or role[field]
        for arch in role["archetypes"]:
            a_edit = arch_edits.get(arch["id"]) or {}
            for field in EDITABLE_ARCH_FIELDS:
                if field not in a_edit:
                    continue
                if field == "weights":
                    weights = _clean_weights(a_edit[field], set(archetype_profiles(arch)))
                    if any(v > 0 for v in weights.values()):
                        arch["weights"] = weights
                elif field == "traits":
                    arch[field] = _clean_list(a_edit[field])
                else:
                    arch[field] = _clean_text(a_edit[field]) or arch[field]
    return merged


def current_roles() -> list[dict[str, Any]]:
    roles = apply_overrides(DEFAULT_ROLES, _load_overrides())
    for role in roles:
        plot = ROLE_PLOTS.get(role["id"])
        if plot:
            population = plot["population"]
            role["plot"] = {
                **plot,
                "profiles": [
                    {"apiName": name, "label": PROFILE_LABELS.get(name, name)}
                    for name in POSITION_PROFILES.get(population[0], ())
                ],
                # Only archetypes rated from the same positions can be an axis.
                "archetypes": [
                    a["id"] for a in role["archetypes"] if set(a["sources"]) <= set(population)
                ],
            }
        for arch in role["archetypes"]:
            arch["profiles"] = [
                {"apiName": name, "label": PROFILE_LABELS.get(name, name)}
                for name in archetype_profiles(arch)
            ]
            arch["sourceLabels"] = [IMPECT_POSITION_LABELS.get(s, s) for s in arch["sources"]]
    return roles


def save_overrides(body: dict[str, Any], *, username: str) -> dict[str, Any]:
    known_roles = {role["id"]: role for role in DEFAULT_ROLES}
    known_archs = {arch["id"]: arch for role in DEFAULT_ROLES for arch in role["archetypes"]}

    roles_in = body.get("roles") if isinstance(body.get("roles"), dict) else {}
    archs_in = body.get("archetypes") if isinstance(body.get("archetypes"), dict) else {}

    with _overrides_lock:
        current = _load_overrides()
        role_store = current.get("roles") if isinstance(current.get("roles"), dict) else {}
        arch_store = current.get("archetypes") if isinstance(current.get("archetypes"), dict) else {}
        for role_id, edit in roles_in.items():
            if role_id not in known_roles or not isinstance(edit, dict):
                continue
            entry = role_store.setdefault(role_id, {})
            for field in EDITABLE_ROLE_FIELDS:
                if field in edit:
                    entry[field] = edit[field]
        for arch_id, edit in archs_in.items():
            if arch_id not in known_archs or not isinstance(edit, dict):
                continue
            entry = arch_store.setdefault(arch_id, {})
            for field in EDITABLE_ARCH_FIELDS:
                if field in edit:
                    entry[field] = edit[field]
        for reset_id in body.get("reset_archetypes") or []:
            arch_store.pop(str(reset_id), None)
        payload = {
            "roles": role_store,
            "archetypes": arch_store,
            "saved_at": datetime.now(UTC).isoformat(),
            "saved_by": username,
        }
        ensure_data_dirs()
        temp = OVERRIDES_PATH.with_suffix(".json.tmp")
        temp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        temp.replace(OVERRIDES_PATH)
    return payload


# ---------------------------------------------------------------------------
# Player pool
# ---------------------------------------------------------------------------

POOL_FIELDS = ("playerId", "name", "age", "foot", "club", "league", "season", "minutes", "position")


def _slim_row(row: dict[str, Any]) -> dict[str, Any] | None:
    position = str(row.get("position") or "")
    wanted = POSITION_PROFILES.get(position)
    if not wanted:
        return None
    raw_scores = row.get("profileScores") or {}
    scores = {}
    for name in wanted:
        value = raw_scores.get(name)
        if value is None:
            continue
        try:
            scores[name] = round(float(value), 1)
        except (TypeError, ValueError):
            continue
    if not scores:
        return None
    out = {key: row.get(key) for key in POOL_FIELDS}
    out["scores"] = scores
    transfer = row.get("transfer")
    if isinstance(transfer, dict) and transfer.get("status"):
        out["transfer"] = {
            "status": transfer.get("status"),
            "to": transfer.get("to") or transfer.get("club") or "",
            "from": transfer.get("from") or "",
        }
    return out


def build_pool(*, force: bool = False) -> dict[str, Any]:
    global _pool_cache
    from app import transfer_status
    from app.who_to_scout import _load_standouts_raw_payload

    now = time.time()
    if not force and _pool_cache and now - _pool_cache[0] < POOL_TTL:
        return _pool_cache[1]

    with _pool_lock:
        if not force and _pool_cache and now - _pool_cache[0] < POOL_TTL:
            return _pool_cache[1]
        raw = _load_standouts_raw_payload(period="season")
        if raw.get("building"):
            return {
                "building": True,
                "players": [],
                "message": raw.get("message")
                or "The recruitment pool is rebuilding — try again in a few minutes.",
            }
        rows = [dict(row) for row in raw.get("players") or []]
        try:
            transfer_status.annotate_all(rows)
        except Exception:  # noqa: BLE001 - flags are a bonus, never a blocker
            logger.warning("Transfer flags unavailable for archetype pool")
        players = [slim for slim in (_slim_row(row) for row in rows) if slim]
        leagues = sorted({str(p.get("league") or "") for p in players if p.get("league")})
        payload = {
            "building": False,
            "players": players,
            "player_count": len(players),
            "leagues": leagues,
            "season_label": raw.get("season_label") or raw.get("period_label") or "",
            "generated_at": raw.get("generated_at"),
        }
        _pool_cache = (time.time(), payload)
        return payload


# ---------------------------------------------------------------------------
# Ranking (mirrors static/pv-archetypes.js so tests pin the maths)
# ---------------------------------------------------------------------------


def archetype_fit(scores: dict[str, float], weights: dict[str, float]) -> float | None:
    total = 0.0
    weight_sum = 0.0
    for name, weight in weights.items():
        if weight <= 0:
            continue
        value = scores.get(name)
        if value is None:
            return None
        total += float(value) * weight
        weight_sum += weight
    if weight_sum <= 0:
        return None
    return round(total / weight_sum, 1)


def rank_archetype(
    arch: dict[str, Any],
    players: list[dict[str, Any]],
    *,
    min_minutes: float = 0,
    max_age: int | None = None,
    leagues: set[str] | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    sources = set(arch.get("sources") or [])
    best: dict[Any, dict[str, Any]] = {}
    for player in players:
        if player.get("position") not in sources:
            continue
        if float(player.get("minutes") or 0) < min_minutes:
            continue
        age = player.get("age")
        if max_age is not None and age is not None and int(age) > max_age:
            continue
        if leagues and player.get("league") not in leagues:
            continue
        fit = archetype_fit(player.get("scores") or {}, arch.get("weights") or {})
        if fit is None:
            continue
        key = player.get("playerId") or player.get("name")
        if key in best and best[key]["fit"] >= fit:
            continue
        best[key] = {**player, "fit": fit}
    return sorted(best.values(), key=lambda row: -row["fit"])[:limit]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class ArchetypeSaveBody(BaseModel):
    roles: dict[str, Any] = Field(default_factory=dict)
    archetypes: dict[str, Any] = Field(default_factory=dict)
    reset_archetypes: list[str] = Field(default_factory=list)


def _can_edit(request: Request) -> bool:
    from app.auth import current_role

    return current_role(request) == "admin"


def register_pv_archetypes_routes(app: FastAPI) -> None:
    @app.get("/pv-archetypes")
    def pv_archetypes_page() -> FileResponse:
        return FileResponse(STANDALONE_DIR / "pv-archetypes.html")

    @app.get("/api/pv-archetypes/config")
    def pv_archetypes_config(request: Request) -> JSONResponse:
        overrides = _load_overrides()
        return JSONResponse(
            {
                "roles": current_roles(),
                "formations": FORMATIONS,
                "profile_labels": PROFILE_LABELS,
                "can_edit": _can_edit(request),
                "saved_at": overrides.get("saved_at"),
                "saved_by": overrides.get("saved_by"),
            },
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/pv-archetypes/pool")
    def pv_archetypes_pool() -> dict[str, Any]:
        return build_pool()

    @app.post("/api/pv-archetypes/config")
    def pv_archetypes_save(request: Request, body: ArchetypeSaveBody) -> dict[str, Any]:
        if not _can_edit(request):
            raise HTTPException(status_code=403, detail="Only admin accounts can edit the position book.")
        username = str(request.session.get("username") or "admin") if "session" in request.scope else "admin"
        saved = save_overrides(body.model_dump(), username=username)
        return {"ok": True, "saved_at": saved["saved_at"], "roles": current_roles()}
