export type League =
  | "National League"
  | "League One"
  | "League Two"
  | "Scottish Prem"
  | "Irish Prem";

export type Position =
  | "CENTRAL_DEFENDER"
  | "LEFT_WINGBACK_DEFENDER"
  | "RIGHT_WINGBACK_DEFENDER"
  | "DEFENSE_MIDFIELD"
  | "CENTRAL_MIDFIELD"
  | "ATTACKING_MIDFIELD"
  | "LEFT_WINGER"
  | "RIGHT_WINGER"
  | "CENTER_FORWARD";

export interface PositionOption {
  value: Position;
  label: string;
}

export interface Player {
  id: string;
  name: string;
  age: number;
  heightCm: number;
  foot: "L" | "R" | "Both";
  league: League;
  club: string;
  minutes: number;
  profileScores: Record<string, number>;
}

export interface ProfileWeights {
  [profileName: string]: number;
}

export interface RankedPlayer extends Player {
  overall: number;
  rank: number;
}
