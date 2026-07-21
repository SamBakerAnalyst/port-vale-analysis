import type { League, Player, Position, ProfileWeights, RankedPlayer } from "./types";

export const LEAGUES: League[] = [
  "National League",
  "League One",
  "League Two",
  "Scottish Prem",
  "Irish Prem",
];

export const POSITIONS: { value: Position; label: string }[] = [
  { value: "CENTRAL_DEFENDER", label: "Centre Back" },
  { value: "LEFT_WINGBACK_DEFENDER", label: "Left Back" },
  { value: "RIGHT_WINGBACK_DEFENDER", label: "Right Back" },
  { value: "DEFENSE_MIDFIELD", label: "Defensive Midfielder" },
  { value: "CENTRAL_MIDFIELD", label: "Central Midfielder" },
  { value: "ATTACKING_MIDFIELD", label: "Attacking Midfielder" },
  { value: "LEFT_WINGER", label: "Left Winger" },
  { value: "RIGHT_WINGER", label: "Right Winger" },
  { value: "CENTER_FORWARD", label: "Centre Forward" },
];

/** Impect profile names per position — will come from API later */
export const PROFILES_BY_POSITION: Record<Position, string[]> = {
  CENTRAL_DEFENDER: [
    "Aerial CB",
    "Ball Progressor",
    "Pressing CB",
    "Defensive Actions",
    "Line Breaking Passes",
  ],
  LEFT_WINGBACK_DEFENDER: [
    "Overlapping FB",
    "Crossing Quality",
    "Defensive Duels",
    "Progressive Carries",
    "Pressing Intensity",
  ],
  RIGHT_WINGBACK_DEFENDER: [
    "Overlapping FB",
    "Crossing Quality",
    "Defensive Duels",
    "Progressive Carries",
    "Pressing Intensity",
  ],
  DEFENSE_MIDFIELD: [
    "Ball Winner",
    "Press Resistance",
    "Progressive Passing",
    "Screening",
    "Recovery Runs",
  ],
  CENTRAL_MIDFIELD: [
    "Box to Box",
    "Chance Creation",
    "Ball Progressor",
    "Pressing Midfielder",
    "Final Third Entries",
  ],
  ATTACKING_MIDFIELD: [
    "Chance Creator",
    "Final Third Actions",
    "Shot Creation",
    "Progressive Passes",
    "Pressing AM",
  ],
  LEFT_WINGER: [
    "1v1 Dribbling",
    "Crossing",
    "Goal Threat",
    "Pressing Winger",
    "Progressive Carries",
  ],
  RIGHT_WINGER: [
    "1v1 Dribbling",
    "Crossing",
    "Goal Threat",
    "Pressing Winger",
    "Progressive Carries",
  ],
  CENTER_FORWARD: [
    "Aerial Striker",
    "Box Presence",
    "Link Play",
    "Pressing Forward",
    "Shot Quality",
  ],
};

function rand(min: number, max: number): number {
  return Math.round(min + Math.random() * (max - min));
}

function makeScores(profiles: string[], seed: number): Record<string, number> {
  const scores: Record<string, number> = {};
  profiles.forEach((p, i) => {
    scores[p] = rand(42, 94) + ((seed + i * 7) % 12) - 6;
    scores[p] = Math.max(35, Math.min(98, scores[p]));
  });
  return scores;
}

const MOCK_PLAYERS: Omit<Player, "profileScores">[] = [
  { id: "1", name: "James Morrison", age: 24, heightCm: 188, foot: "R", league: "League One", club: "Bolton", minutes: 2140 },
  { id: "2", name: "Callum Walsh", age: 22, heightCm: 192, foot: "L", league: "League Two", club: "Wrexham", minutes: 1890 },
  { id: "3", name: "Ryan O'Sullivan", age: 26, heightCm: 185, foot: "L", league: "Irish Prem", club: "Shamrock Rovers", minutes: 2310 },
  { id: "4", name: "Finlay MacLeod", age: 23, heightCm: 190, foot: "R", league: "Scottish Prem", club: "Motherwell", minutes: 1560 },
  { id: "5", name: "Tom Bradley", age: 28, heightCm: 186, foot: "R", league: "National League", club: "Chesterfield", minutes: 2680 },
  { id: "6", name: "Marcus Hughes", age: 21, heightCm: 194, foot: "R", league: "League One", club: "Peterborough", minutes: 980 },
  { id: "7", name: "Declan Byrne", age: 25, heightCm: 183, foot: "L", league: "Irish Prem", club: "St Patrick's", minutes: 2010 },
  { id: "8", name: "Ewan Campbell", age: 27, heightCm: 187, foot: "R", league: "Scottish Prem", club: "St Mirren", minutes: 2440 },
  { id: "9", name: "Kyle Simmons", age: 23, heightCm: 191, foot: "Both", league: "League Two", club: "Stockport", minutes: 1720 },
  { id: "10", name: "Ben Okonkwo", age: 24, heightCm: 189, foot: "R", league: "National League", club: "Bromley", minutes: 2190 },
  { id: "11", name: "Liam Fraser", age: 22, heightCm: 184, foot: "L", league: "League One", club: "Barnsley", minutes: 1340 },
  { id: "12", name: "Connor Reid", age: 29, heightCm: 188, foot: "R", league: "Scottish Prem", club: "Livingston", minutes: 2890 },
  { id: "13", name: "Sean Murphy", age: 20, heightCm: 193, foot: "R", league: "Irish Prem", club: "Derry City", minutes: 760 },
  { id: "14", name: "Harry Dunn", age: 26, heightCm: 186, foot: "R", league: "League Two", club: "Notts County", minutes: 2280 },
  { id: "15", name: "Adam Kowalski", age: 25, heightCm: 190, foot: "L", league: "National League", club: "York City", minutes: 1950 },
  { id: "16", name: "Jack O'Connor", age: 23, heightCm: 182, foot: "L", league: "League One", club: "Blackpool", minutes: 1670 },
  { id: "17", name: "Ross McAllister", age: 24, heightCm: 189, foot: "R", league: "Scottish Prem", club: "Ross County", minutes: 1430 },
  { id: "18", name: "Niall Brennan", age: 27, heightCm: 187, foot: "R", league: "Irish Prem", club: "Bohemians", minutes: 2520 },
  { id: "19", name: "Ethan Clarke", age: 21, heightCm: 195, foot: "R", league: "League Two", club: "Bradford", minutes: 1120 },
  { id: "20", name: "Michael O'Brien", age: 30, heightCm: 185, foot: "R", league: "National League", club: "Southend", minutes: 3010 },
  { id: "21", name: "Josh Taylor", age: 22, heightCm: 188, foot: "R", league: "League One", club: "Charlton", minutes: 1840 },
  { id: "22", name: "Craig Anderson", age: 26, heightCm: 191, foot: "L", league: "Scottish Prem", club: "Kilmarnock", minutes: 2090 },
  { id: "23", name: "Darragh Keane", age: 23, heightCm: 186, foot: "L", league: "Irish Prem", club: "Shelbourne", minutes: 1780 },
  { id: "24", name: "Luke Patterson", age: 25, heightCm: 184, foot: "R", league: "League Two", club: "Crewe", minutes: 2360 },
];

export function getPlayersForPosition(position: Position): Player[] {
  const profiles = PROFILES_BY_POSITION[position];
  return MOCK_PLAYERS.map((p, i) => ({
    ...p,
    profileScores: makeScores(profiles, i * 13 + position.length),
  }));
}

export function computeOverall(
  profileScores: Record<string, number>,
  weights: ProfileWeights,
  profiles: string[],
): number {
  let weightedSum = 0;
  let totalWeight = 0;

  for (const profile of profiles) {
    const w = weights[profile] ?? 0;
    if (w <= 0) continue;
    weightedSum += (profileScores[profile] ?? 0) * w;
    totalWeight += w;
  }

  if (totalWeight === 0) return 0;
  return weightedSum / totalWeight;
}

export function rankPlayers(
  players: Player[],
  weights: ProfileWeights,
  profiles: string[],
): RankedPlayer[] {
  const withOverall = players.map((p) => ({
    ...p,
    overall: computeOverall(p.profileScores, weights, profiles),
    rank: 0,
  }));

  withOverall.sort((a, b) => b.overall - a.overall);
  return withOverall.map((p, i) => ({ ...p, rank: i + 1 }));
}

export function defaultWeights(profiles: string[]): ProfileWeights {
  return Object.fromEntries(profiles.map((p) => [p, 50]));
}

export function filterByLeagues(players: Player[], leagues: League[]): Player[] {
  if (leagues.length === 0) return [];
  return players.filter((p) => leagues.includes(p.league));
}
