import { useMemo, useState } from "react";
import {
  LEAGUES,
  POSITIONS,
  PROFILES_BY_POSITION,
  defaultWeights,
  filterByLeagues,
  getPlayersForPosition,
  rankPlayers,
} from "./data/mock";
import type { League, Position } from "./types";
import "./App.css";

function formatHeight(cm: number): string {
  const feet = Math.floor(cm / 30.48);
  const inches = Math.round((cm / 2.54) % 12);
  return `${feet}'${inches}" (${cm}cm)`;
}

function formatMixPercent(weights: Record<string, number>, profiles: string[], profile: string): number {
  const total = profiles.reduce((sum, p) => sum + Math.max(0, weights[p] ?? 0), 0);
  const w = weights[profile] ?? 0;
  if (w <= 0 || total <= 0) return 0;
  return Math.round((w / total) * 100);
}

export default function App() {
  const [position, setPosition] = useState<Position>("CENTRAL_DEFENDER");
  const [selectedLeagues, setSelectedLeagues] = useState<League[]>([...LEAGUES]);
  const profiles = PROFILES_BY_POSITION[position];

  const [weights, setWeights] = useState<Record<string, number>>(() =>
    defaultWeights(PROFILES_BY_POSITION["CENTRAL_DEFENDER"]),
  );

  const handlePositionChange = (next: Position) => {
    setPosition(next);
    setWeights(defaultWeights(PROFILES_BY_POSITION[next]));
  };

  const toggleLeague = (league: League) => {
    setSelectedLeagues((prev) =>
      prev.includes(league) ? prev.filter((l) => l !== league) : [...prev, league],
    );
  };

  const ranked = useMemo(() => {
    const players = filterByLeagues(getPlayersForPosition(position), selectedLeagues);
    return rankPlayers(players, weights, profiles);
  }, [position, selectedLeagues, weights, profiles]);

  const resetWeights = () => setWeights(defaultWeights(profiles));

  return (
    <div className="app">
      <header className="header">
        <div className="header__brand">
          <span className="header__logo">Impect</span>
          <span className="header__title">Scouting Long Lists</span>
        </div>
        <p className="header__subtitle">
          Profile-weighted player search · National League · L1 · L2 · Scot Prem · Irish Prem
        </p>
      </header>

      <section className="controls">
        <div className="control-group">
          <label htmlFor="position">Position</label>
          <select
            id="position"
            value={position}
            onChange={(e) => handlePositionChange(e.target.value as Position)}
          >
            {POSITIONS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </div>

        <div className="control-group control-group--leagues">
          <span className="control-label">Leagues</span>
          <div className="league-chips">
            {LEAGUES.map((league) => (
              <button
                key={league}
                type="button"
                className={`chip ${selectedLeagues.includes(league) ? "chip--active" : ""}`}
                onClick={() => toggleLeague(league)}
              >
                {league}
              </button>
            ))}
          </div>
        </div>

        <div className="control-group control-group--meta">
          <span className="result-count">
            {ranked.length} player{ranked.length !== 1 ? "s" : ""}
          </span>
          <button type="button" className="btn-reset" onClick={resetWeights}>
            Reset weights
          </button>
        </div>
      </section>

      <section className="weights-panel">
        <div className="weights-panel__header">
          <h2>Profile weights</h2>
          <p>0–100 importance per profile — % of mix shows its share of the overall score</p>
        </div>
        <div className="weights-grid">
          {profiles.map((profile) => {
            const w = weights[profile] ?? 0;
            const active = w > 0;
            return (
              <div
                key={profile}
                className={`weight-card ${active ? "weight-card--active" : "weight-card--muted"}`}
              >
                <span className="weight-card__name">{profile}</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  step={1}
                  value={w}
                  onChange={(e) =>
                    setWeights((prev) => ({ ...prev, [profile]: Number(e.target.value) }))
                  }
                  className="weight-slider"
                  aria-label={`Weight for ${profile}`}
                />
                <div className="weight-card__values">
                  <span className="weight-card__value">{w}</span>
                  <span className="weight-card__mix">
                    {formatMixPercent(weights, profiles, profile)}% of mix
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      </section>

      <section className="table-wrap">
        <table className="player-table">
          <thead>
            <tr>
              <th className="col-rank">Rank</th>
              <th className="col-name">Name</th>
              <th className="col-num">Age</th>
              <th className="col-height">Height</th>
              <th className="col-foot">Foot</th>
              <th className="col-league">League</th>
              <th className="col-club">Club</th>
              {profiles.map((profile) => (
                <th
                  key={profile}
                  className={`col-profile ${(weights[profile] ?? 0) > 0 ? "col-profile--weighted" : ""}`}
                >
                  {profile}
                </th>
              ))}
              <th className="col-overall">Overall</th>
            </tr>
          </thead>
          <tbody>
            {ranked.length === 0 ? (
              <tr>
                <td colSpan={7 + profiles.length + 1} className="empty-row">
                  Select at least one league to see players.
                </td>
              </tr>
            ) : (
              ranked.map((player) => (
                <tr key={player.id}>
                  <td className="col-rank">
                    <span className="rank-badge">{player.rank}</span>
                  </td>
                  <td className="col-name">{player.name}</td>
                  <td className="col-num">{player.age}</td>
                  <td className="col-height">{formatHeight(player.heightCm)}</td>
                  <td className="col-foot">{player.foot}</td>
                  <td className="col-league">{player.league}</td>
                  <td className="col-club">{player.club}</td>
                  {profiles.map((profile) => (
                    <td key={profile} className="col-profile score-cell">
                      {player.profileScores[profile]?.toFixed(0) ?? "—"}
                    </td>
                  ))}
                  <td className="col-overall">
                    <strong>{player.overall.toFixed(1)}</strong>
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </section>

      <footer className="footer">
        Mock data for now — Impect API connection coming next.
      </footer>
    </div>
  );
}
