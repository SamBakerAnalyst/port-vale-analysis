/* Shared recruitment age groups — Watch list, PV Archetypes, Who To Scout. */
(() => {
  "use strict";

  const GROUPS = [
    { id: "emerging", label: "Emerging talent", short: "Emerging", range: "23 & under", min: null, max: 23 },
    { id: "prime", label: "Prime players", short: "Prime", range: "24–29", min: 24, max: 29 },
    { id: "experienced", label: "Experienced players", short: "Experienced", range: "30+", min: 30, max: null },
  ];

  function toAge(value) {
    if (value == null || value === "") return null;
    const n = Number(value);
    return Number.isFinite(n) && n > 0 ? Math.floor(n) : null;
  }

  function groupFor(value) {
    const age = toAge(value);
    if (age == null) return null;
    return (
      GROUPS.find((g) => (g.min == null || age >= g.min) && (g.max == null || age <= g.max)) || null
    );
  }

  function byId(id) {
    return GROUPS.find((g) => g.id === id) || null;
  }

  /** "all" (or empty) passes everyone; a group id needs a known age inside that group. */
  function matches(value, id) {
    if (!id || id === "all") return true;
    return groupFor(value)?.id === id;
  }

  function badgeHtml(value, { compact = false } = {}) {
    const group = groupFor(value);
    if (!group) return "";
    const text = compact ? group.short : group.label;
    return `<span class="age-group age-group--${group.id}" title="${group.label} (${group.range})">${text}</span>`;
  }

  window.PVAgeGroups = { GROUPS, toAge, groupFor, byId, matches, badgeHtml };
})();
