"""Club context for Shadow Teams — the parts Impect cannot tell us.

Everything here is sourced (see each club's ``sources``). The data sections of the tool
come from data/shadow-teams.json (Impect); this file is ownership, structure, coaches,
recruitment philosophy and the season milestones before Impect cover starts.
Staff notes added in the tool are stored separately and never overwrite this.
"""

from __future__ import annotations

from typing import Any

SHADOW_CONTEXT: dict[str, dict[str, Any]] = {
    "lincoln": {
        "headline": "League One champions 2025/26 — a record 103 points on one of the smallest budgets in the division",
        "one_liner": (
            "Two promotions from non-league under the Cowleys, a loan-led near miss under Appleton, "
            "then a pragmatic, high-energy 4-2-3-1 under Michael Skubala that won League One with the "
            "best defence and second-best attack."
        ),
        "status_now": "Championship 2026/27 — first season in the second tier since 1961.",
        "spotlight_season": "25/26",
        "success_seasons": ["25/26"],
        "timeline": [
            {"season": "2016/17", "text": "National League champions under Danny and Nicky Cowley (plus an FA Cup quarter-final run).", "level": "NL"},
            {"season": "2017/18", "text": "EFL Trophy winners in their first season back in the Football League.", "level": "L2"},
            {"season": "2018/19", "text": "League Two champions under the Cowleys.", "level": "L2"},
            {"season": "2020/21", "text": "5th in League One under Michael Appleton; lost the play-off final 2–1 to Blackpool. Loanees Brennan Johnson (Nottingham Forest) and Morgan Rogers (Manchester City) were central.", "level": "L1"},
            {"season": "Nov 2023", "text": "Michael Skubala appointed head coach (ex-Leeds U21, ex-England futsal head coach).", "level": "L1"},
            {"season": "2025/26", "text": "League One champions — 103 points, a 29-game unbeaten run, best defence and second-best attack. Skubala named LMA League One Manager of the Year.", "level": "L1"},
        ],
        "pillars": [
            {
                "title": "Ownership & money",
                "points": [
                    "American investors now lead: Ron Fowler (ex-San Diego Padres co-owner) became chairman in February 2026 after raising his stake above 25%; Harvey Jabara's family is the other big investor. Landon Donovan is an investor and strategic adviser.",
                    "Clive Nates (involved since 2016, chairman 2018–2026) remains a significant shareholder and co-vice chairman.",
                    "Promotion was won on a budget of around £5m. Sporting director Jez George says top League One budgets are £14–15m.",
                    "The club has never paid more than £350,000 for a player.",
                ],
            },
            {
                "title": "Football structure",
                "points": [
                    "Long-serving sporting director Jez George (head of football in the Brennan Johnson era) runs recruitment with director of talent identification Joe Hutchinson.",
                    "Player trading is part of the model: develop, then sell at a profit, and sale money is not automatically reinvested in the same position.",
                    "Recruitment mixes data-led scouting, video, character checks and live viewing, including European leagues — foreign signings have to be clearly better value than domestic options.",
                ],
            },
            {
                "title": "Head coach & identity",
                "points": [
                    "Skubala studied psychology and sport science and has written books on coaching — a teacher-coach rather than a former pro.",
                    "2025/26: a consistent 4-2-3-1 (as at Leeds U21), a back four suited to a high line, an energetic midfield and enough forward depth to press for a full season. A 5-3-2 was kept for certain games.",
                    "Possession was among the lowest in the league (local coverage cites ~42%). Pragmatic: press, win it high, score more than the opposition.",
                    "Attacking full-backs (Tendayi Darikwa, Adam Reach — 17 goal involvements between them). Jack Moylan moved from the left into the No.10 role. Conor McGrandles was player of the season.",
                ],
            },
            {
                "title": "Recruitment in the title season",
                "points": [
                    "Summer 2025: polish, not overhaul — experienced leaders Sonny Bradley and Adam Reach.",
                    "January 2026: Josh Honohan (Shamrock Rovers) and Deji Elerewe (Bromley) on permanent deals, plus loans for Ryan One (Sheffield United), Alfie Lloyd (QPR) and Kamil Conteh (Bristol Rovers).",
                    "Skubala: 'Some of what we have in this squad cannot be bought… the work ethic, the leadership.'",
                ],
            },
            {
                "title": "Earlier model (2020/21)",
                "points": [
                    "Elite-academy loans as the edge: Brennan Johnson (Forest, season-long) and Morgan Rogers (Man City, January). Both later became Premier League players.",
                    "Lincoln approached Man City about Rogers during the first lockdown — targets were tracked for months before signing.",
                ],
            },
        ],
        "lessons": [
            "Budget is not destiny: they won League One on roughly a third of the top budgets by being clear on profile (energy, physicality, leadership) and keeping the group together.",
            "Commit to one shape and recruit for it: the 4-2-3-1, the high line and the press dictated the signings, not the other way round.",
            "Possession is optional: they won the league near the bottom of the possession table. Chance quality for and against is what counted.",
            "Trading is part of the model, but the core of the title side was built by retaining and improving players, then adding a few experienced leaders.",
        ],
        "sources": [
            {"label": "BBC Sport — Skubala offered new deal (May 2026)", "url": "https://www.bbc.com/sport/football/articles/c3924xn3vxpo"},
            {"label": "Lincoln City — Skubala LMA Manager of the Year", "url": "https://www.weareimps.com/news/skubala-lma-league-one-manager-year"},
            {"label": "The Linc — How Skubala transformed Lincoln", "url": "https://thelinc.co.uk/2026/06/how-did-michael-skubala-transform-lincoln-city/"},
            {"label": "The Athletic — Inside Lincoln City (Apr 2026)", "url": "https://www.nytimes.com/athletic/7167961/2026/04/06/lincoln-city-padres-donovan-championship-promotion/"},
            {"label": "BBC Sport — Fowler confirmed as chairman", "url": "https://www.bbc.com/sport/football/articles/cn40ezx9nmmo"},
            {"label": "BBC Sport — Jez George on budget", "url": "https://www.bbc.co.uk/sport/football/articles/cjwgdevyv2no"},
            {"label": "The Stacey West — Jez George on the market", "url": "https://staceywest.net/2025/06/02/jez-george-lifts-lid-on-transfer-market-challenges-facing-lincoln-city/"},
            {"label": "The72 — January 2026 window", "url": "https://the72.co.uk/2026/02/06/lincoln-city-michael-skubala-pleased-with-january-transfers/"},
            {"label": "Lincoln City — 2021 play-off final report", "url": "https://www.weareimps.com/news/2021/may/210530-play-off-final-report"},
        ],
    },
    "stockport": {
        "headline": "Non-league to two League One play-off campaigns in four years — National League and League Two titles under Dave Challinor",
        "one_liner": (
            "An owner with a seven-year plan, a director of football from the City Football Group, "
            "and a physical, aggressive, aerially dominant team that has finished top-three in every "
            "EFL season since coming up."
        ),
        "status_now": "League One 2026/27 under new head coach Jimmy McNulty (appointed June 2026 after Challinor left by mutual consent).",
        "spotlight_season": "23/24",
        "success_seasons": ["23/24", "24/25", "25/26"],
        "timeline": [
            {"season": "Jan 2020", "text": "Local businessman Mark Stott buys the club, clears the debts and sets a seven-year plan to reach the Championship.", "level": "NL"},
            {"season": "Nov 2021", "text": "Dave Challinor appointed from Hartlepool.", "level": "NL"},
            {"season": "2021/22", "text": "National League champions — back in the EFL after 11 years.", "level": "NL"},
            {"season": "2022/23", "text": "League Two play-off final, lost to Carlisle on penalties.", "level": "L2"},
            {"season": "2023/24", "text": "League Two champions: 92 points, 96 goals, a 12-game winning run that equalled the fourth-tier record.", "level": "L2"},
            {"season": "2024/25", "text": "3rd in League One; beaten in the play-offs.", "level": "L1"},
            {"season": "2025/26", "text": "3rd in League One again; lost the play-off final 4–1 to Bolton. Challinor left by mutual consent.", "level": "L1"},
            {"season": "Jun 2026", "text": "Jimmy McNulty appointed head coach (three-year deal) after taking Rochdale back into the EFL.", "level": "L1"},
        ],
        "pillars": [
            {
                "title": "Ownership & plan",
                "points": [
                    "Mark Stott ring-fenced personal money for a football project, bought the club in January 2020 and set a seven-year plan through the pyramid to the Championship.",
                    "Debts cleared, more than £1m spent on Edgeley Park, and a training base at Manchester United's former Carrington site.",
                    "Investment was disciplined: 'pay well for this division but we won't go too far… we don't want to sabotage future seasons'.",
                ],
            },
            {
                "title": "Football structure",
                "points": [
                    "Simon Wilson (ex-Manchester City head of performance analysis, City Football Group director of football services, Sunderland chief football officer) came in with Stott as director of football and later became CEO.",
                    "Philosophy: 'why wait until you are a Championship team to operate like one' — Wyscout, InStat and 21st Club data plus full-time analysis, even in the National League.",
                    "Recruitment is built on ruling players out: wide data coverage first, then video and live checks, with very few players making it to a signing.",
                ],
            },
            {
                "title": "Head coach & identity",
                "points": [
                    "Challinor: seven promotions in 16 seasons as a manager (Colwyn Bay, AFC Fylde, Hartlepool, Stockport twice).",
                    "Among the most aggressive sides out of possession in League Two 2023/24 (low PPDA, high challenge intensity), with the fewest non-penalty goals conceded.",
                    "Aerial dominance: no side in England's top four tiers scored more headed goals in 2023/24 (22). Their aerial win rate (~56%) was second only to Liverpool across the four divisions.",
                    "Front pairings built on pace and power (Isaac Olaofe 20 league goals in 2023/24), with a target man (Kyle Wootton / Paddy Madden) and an elite loanee (Louie Barry, Aston Villa).",
                ],
            },
            {
                "title": "Recruitment pattern",
                "points": [
                    "Loans from the top end: Louie Barry spent two spells on loan from Aston Villa and was described as one of the best players outside the top two tiers.",
                    "Paid to bring in proven EFL players from above or from rivals (Olaofe from Millwall). Summer 2026 continued it: Ethan Ennis (Man United), Mamadou Jobe (Cambridge), Ben Osborn (Derby), Eoghan O'Connell (Barnsley), Mikael Mandron (St Mirren).",
                ],
            },
        ],
        "lessons": [
            "Operate one level above where you are: the data, analysis and training base were Championship-standard while the team was in non-league.",
            "Recruitment is mostly saying no: wide coverage, a strict filter and few signings.",
            "Be elite at one physical thing: aerial dominance and set plays gave them goals and clean sheets in every division.",
            "Aggression without the ball and a low xG against travelled from League Two to League One. Getting over the line in the play-offs is the part they haven't cracked.",
        ],
        "sources": [
            {"label": "Training Ground Guru — Simon Wilson: Stockport's seven-year plan", "url": "https://archive.trainingground.guru/articles/simon-wilson-stockport-countys-seven-year-plan"},
            {"label": "Sky Sports — Simon Wilson on the Championship ambition", "url": "https://www.skysports.com/football/news/11095/12180728/simon-wilson-on-stockport-county-s-ambition-to-reach-the-championship"},
            {"label": "The Times — Stockport lure talent from above", "url": "https://www.thetimes.com/sport/football/article/the-journeyman-ambitious-stockport-lure-talent-from-above-in-battle-to-get-through-bottleneck-cqknzpm9c"},
            {"label": "FC Business — Simon Wilson appointed CEO", "url": "https://fcbusiness.co.uk/news/stockport-county-appoint-simon-wilson-as-chief-executive-officer/"},
            {"label": "Opta Analyst — Stockport, a club on the rise", "url": "https://theanalyst.com/articles/stockport-county-club-on-the-rise"},
            {"label": "TFA — Stockport 2023/24 defensive scout report", "url": "https://totalfootballanalysis.com/team-analysis/stockport-county-202324-defence-scout-report-tactical-analysis"},
            {"label": "BBC Sport — Bolton 4–1 Stockport, play-off final 2026", "url": "https://www.bbc.com/sport/football/live/cedpxdyje8yt"},
            {"label": "BBC Sport — Challinor leaves", "url": "https://www.bbc.com/sport/football/articles/ce3prl257ywo"},
            {"label": "BBC Sport — Jim McNulty appointed", "url": "https://www.bbc.co.uk/sport/football/articles/cn8p8j4gn6xo"},
        ],
    },
    "bradford": {
        "headline": "League Two promotion in 2024/25, then 4th in League One — built on a Valley Parade fortress",
        "one_liner": (
            "A big-crowd club that finally turned its home support into points: Graham Alexander added "
            "hardened promotion winners, turned Valley Parade into a fortress and went straight on to the "
            "League One play-offs."
        ),
        "status_now": "League One 2026/27 under Graham Alexander (second League One season).",
        "spotlight_season": "24/25",
        "success_seasons": ["24/25", "25/26"],
        "timeline": [
            {"season": "Nov 2023", "text": "Graham Alexander replaces Mark Hughes; a strong finish leaves them two points outside the play-offs.", "level": "L2"},
            {"season": "2024/25", "text": "12th on Christmas Day, then a club-record 10 straight home wins. Promoted 3rd with 78 points via Antoni Sarcevic's 96th-minute winner against Fleetwood on the final day. Alexander named League Two Manager of the Year.", "level": "L2"},
            {"season": "2025/26", "text": "4th in League One (only the top two won more games); lost the play-off semi-final 2–0 on aggregate to Bolton.", "level": "L1"},
        ],
        "pillars": [
            {
                "title": "Ownership & the crowd",
                "points": [
                    "Owner Stefan Rupp backed the push in January 2025 (\"a further influx as Stefan Rupp provided the backing\").",
                    "Ultra-competitive season-ticket pricing: under £11 a game for adults, 82p for juniors in early-bird 2024/25. More than 13,500 early-bird season tickets were sold, around 16,000 in total.",
                    "The highest average gates in League Two by a distance, and a record fourth-tier crowd of 24,033 on the final day of 2024/25.",
                    "CEO Ryan Sparks cut tickets to £5 and £10 during the run-in: 'Where can we make gains that will help us on the pitch?'",
                ],
            },
            {
                "title": "Head coach & identity",
                "points": [
                    "Alexander deliberately recruited 'hardened promotion winners' to bring belief: Aden Baldwin, Neill Byrne and Antoni Sarcevic.",
                    "Home dominance: 55 home points in 2024/25 (17 home wins, a club record).",
                    "In 2025/26 Bradford kept coming from behind ('we've found ourselves behind many times this season and come back') and pressed Bolton hard in the semi-final.",
                ],
            },
            {
                "title": "Spine",
                "points": [
                    "Ever-present goalkeeper Sam Walker (big penalty saves in the run-in), Richie Smallwood in midfield, Andy Cook as the reference striker.",
                    "Summer 2026: Walker sold to Watford, Max Power to Wigan, Jenson Metcalfe to Millwall. Arrivals include Adam Phillips and Corey O'Keeffe (Barnsley), Macaulay Gillesphey (Charlton), Callum Connolly (Stockport) and Jake Beesley (Burton).",
                ],
            },
        ],
        "lessons": [
            "Turn the crowd into points: pricing, atmosphere and a team built to attack at home produced a record home season.",
            "Recruit character for a promotion run: experienced winners in the key moments, plus January backing at the right time.",
            "The step up worked straight away — 4th in League One — with a team that kept coming from behind.",
        ],
        "sources": [
            {"label": "BBC Sport — Bradford 1–0 Fleetwood, promotion", "url": "https://www.bbc.co.uk/sport/football/live/c3r8y327199t"},
            {"label": "Telegraph & Argus — 2024/25 season review", "url": "https://www.thetelegraphandargus.co.uk/sport/25138578.bradford-city-season-review-promotion-finally-secured/"},
            {"label": "Telegraph & Argus — record crowd and season tickets", "url": "https://www.thetelegraphandargus.co.uk/sport/25039513.bantams-ceo-busy-season-ticket-sales-record-crowd/"},
            {"label": "Yorkshire Post — early-bird season tickets", "url": "https://www.yorkshirepost.co.uk/sport/football/bradford-city-early-bird-season-tickets-go-past-13000-mark-as-competitive-pricing-continues-to-pay-off-4609924"},
            {"label": "Sky Sports — Bradford 0–1 Bolton, play-off semi-final", "url": "https://www.skysports.com/football/news/13540326/bradford-0-1-bolton-agg-0-2-xavier-simons-strike-cements-wanderers-place-in-league-one-play-off-final"},
            {"label": "Yorkshire Post — Alexander on comeback credentials", "url": "https://www.yorkshirepost.co.uk/sport/football/bradford-city-boss-graham-alexander-on-why-his-sides-comeback-credentials-speak-for-themselves-in-2025-26-8544808"},
        ],
    },
}

# Play-off outcomes Impect's league table cannot show.
PLAYOFF_OUTCOMES: dict[tuple[str, str], str] = {
    ("lincoln", "20/21"): "5th — lost play-off final to Blackpool",
    ("stockport", "22/23"): "4th — lost play-off final to Carlisle on penalties",
    ("stockport", "23/24"): "Champions",
    ("stockport", "24/25"): "3rd — lost in the play-offs",
    ("stockport", "25/26"): "3rd — lost play-off final to Bolton",
    ("bradford", "24/25"): "3rd — automatic promotion",
    ("bradford", "25/26"): "4th — lost play-off semi-final to Bolton",
    ("lincoln", "25/26"): "Champions — promoted to the Championship",
    ("vale", "24/25"): "2nd — automatic promotion",
}

TEMPLATE_INTRO = (
    "Three clubs took three different routes. Stockport and Bradford came up through League Two and were "
    "competitive in League One straight away. Lincoln turned a mid-table League One side into champions "
    "on one of the smallest budgets in the division. Their shapes and possession levels differ (Stockport "
    "kept the ball in League Two, Lincoln won League One with the least of it), but every success season "
    "shares the same core. They won chance quality at both ends, took more shots than most, won their "
    "duels, and won the ball back in ways that took out defenders. Off the pitch, each kept around two "
    "thirds of the previous season's minutes and added a handful of signings who became regulars."
)
