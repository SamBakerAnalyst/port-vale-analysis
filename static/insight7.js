(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const els = {
    counts: $("i7Counts"),
    tabs: $("i7Tabs"),
    status: $("i7Status"),
    uploadBtn: $("i7UploadBtn"),
    dropBtn: $("i7DropBtn"),
    file: $("i7File"),
    kpis: $("i7Kpis"),
    search: $("i7Search"),
    pos: $("i7Pos"),
    league: $("i7League"),
    season: $("i7Season"),
    age: $("i7Age"),
    section: $("i7Section"),
    layout: $("i7Layout"),
    csv: $("i7Csv"),
    spot: $("i7Spot"),
    tableWrap: $("i7TableWrap"),
    head: $("i7Head"),
    rows: $("i7Rows"),
    cards: $("i7Cards"),
    empty: $("i7Empty"),
    drawer: $("i7Drawer"),
    month: $("i7Month"),
    drop: $("i7Drop"),
    dragOver: $("i7DragOver"),
    coverage: $("i7Coverage"),
    uploads: $("i7Uploads"),
  };

  const state = {
    data: null,
    tab: "players",
    sort: "league_mins",
    asc: false,
    selected: "",
    pos: "",
    spot: "",
    layout: "table",
    visible: [],
  };

  const POS_GROUPS = {
    GK: ["GK"],
    DEF: ["CB"],
    FB: ["RB", "LB", "RWB", "LWB"],
    MID: ["DM", "CM", "CAM", "AM", "CDM"],
    WIDE: ["AMR", "AML", "RM", "LM", "RW", "LW"],
    ST: ["ST", "CF"],
  };
  const POS_COLOUR = { GK: "#f59e0b", DEF: "#3d8bfd", FB: "#22d3ee", MID: "#22c55e", WIDE: "#f472b6", ST: "#ef4444" };

  const SECTIONS = [
    [/goalscor/i, "Top scorer", "#f59e0b", "goals"],
    [/minutes per/i, "Min per G+A", "#a3e635", "mpga"],
    [/assist/i, "Top assists", "#22d3ee", "assists"],
    [/youngest/i, "Youngest", "#a78bfa", "youngest"],
  ];

  const SPOTS = [
    { id: "new", label: "New this month", colour: "#f59e0b", test: (p) => p.is_new, needsHistory: true },
    { id: "expiring", label: "", colour: "#ef4444", test: (p) => contractState(p) === "expiring" },
    { id: "none", label: "No contract listed", colour: "#a78bfa", test: (p) => contractState(p) === "none" },
    { id: "u18", label: "U18 regulars", colour: "#f472b6", test: (p) => (p.age ?? 99) <= 17 && (p.league_gt ?? 0) >= 50 },
    { id: "threat", label: "Goal threats", colour: "#22c55e", test: (p) => (p.ga || 0) >= 2 },
    { id: "intl", label: "Internationals", colour: "#3d8bfd", test: (p) => Boolean(p.international) },
  ];

  const MONTH_FMT = new Intl.DateTimeFormat("en-GB", { month: "short", year: "numeric" });
  const MONTH_LONG = new Intl.DateTimeFormat("en-GB", { month: "long", year: "numeric" });

  // ------------------------------------------------------------ helpers

  function esc(value) {
    return String(value ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  const SECTION_CATS = [
    ["gt", "Game-time regulars"],
    ["young", "Young regulars (U18 / U20 / U21)"],
    ["goals", "Top scorers"],
    ["assists", "Top assists"],
    ["mpga", "Minutes per goal / assist"],
    ["youngest", "Youngest appearances"],
    ["unused", "Youngest unused subs"],
  ];

  function sectionInfo(label) {
    const gt = label.match(/achieving\s+(\d+)%/i);
    if (gt) {
      const under = label.match(/<\s*(\d+)/);
      return under
        ? { short: `U${under[1]} ${gt[1]}% GT`, colour: "#f472b6", cat: "young" }
        : { short: `${gt[1]}% GT`, colour: "#22c55e", cat: "gt" };
    }
    if (/unused/i.test(label)) return { short: "Unused subs", colour: "#94a3b8", cat: "unused" };
    for (const [re, short, colour, cat] of SECTIONS) if (re.test(label)) return { short, colour, cat };
    return { short: label.length > 16 ? `${label.slice(0, 15)}…` : label, colour: "#8b9bb0", cat: label };
  }

  function listTag(label, full) {
    const info = sectionInfo(label);
    return `<span class="i7-tag i7-list" style="--lc:${info.colour}" title="${esc(label)}">${esc(full ? label : info.short)}</span>`;
  }

  function posGroup(pos) {
    const p = String(pos || "").toUpperCase();
    for (const [group, list] of Object.entries(POS_GROUPS)) if (list.includes(p)) return group;
    return "";
  }

  function posChip(pos) {
    const colour = POS_COLOUR[posGroup(pos)] || "#8b9bb0";
    return `<span class="i7-pos" style="--pc:${colour}">${esc(pos || "–")}</span>`;
  }

  function ageChip(age) {
    if (age === null || age === undefined) return "";
    return `<span class="i7-age i7-age--${age}">${age}</span>`;
  }

  function clubParts(club) {
    const text = String(club || "").trim();
    const m = text.match(/^(.*?)\s+((?:U|Under\s?)\d{2}s?|II|B|Reserves|Academy)$/i);
    return m ? { base: m[1], tag: m[2].toUpperCase() } : { base: text, tag: "" };
  }

  function crestFor(club, size) {
    const { base } = clubParts(club);
    const words = base.replace(/[^A-Za-z0-9 ]/g, " ").split(/\s+/).filter((w) => w && !/^(fc|afc|cf)$/i.test(w));
    let initials = "";
    if (words.length === 1) initials = words[0].slice(0, 3);
    else initials = words.slice(0, 3).map((w) => w[0]).join("");
    let hash = 0;
    for (const ch of base.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
    const cls = size ? ` i7-crest--${size}` : "";
    return `<span class="i7-crest${cls}" style="--h:${hash}" title="${esc(base)}">${esc(initials.toUpperCase())}</span>`;
  }

  function clubHue(club) {
    let hash = 0;
    for (const ch of clubParts(club).base.toLowerCase()) hash = (hash * 31 + ch.charCodeAt(0)) % 360;
    return hash;
  }

  function gtColour(gt) {
    if (gt >= 90) return "#22c55e";
    if (gt >= 70) return "#a3e635";
    if (gt >= 50) return "#f59e0b";
    return "#ef4444";
  }

  function ring(gt, large) {
    const v = Math.max(0, Math.min(100, gt ?? 0));
    const r = 18;
    const c = 2 * Math.PI * r;
    return `<div class="i7-ring${large ? " i7-ring--lg" : ""}" style="--gtc:${gtColour(v)}" title="League game time">
      <svg viewBox="0 0 44 44"><circle class="bg" cx="22" cy="22" r="${r}"/><circle class="fg" cx="22" cy="22" r="${r}" stroke-dasharray="${(c * v) / 100} ${c}"/></svg>
      <span>${gt ?? "–"}${gt != null ? "%" : ""}</span>
    </div>`;
  }

  function monthLabel(ym, long) {
    if (!ym) return "";
    const [y, m] = ym.split("-").map(Number);
    return (long ? MONTH_LONG : MONTH_FMT).format(new Date(y, m - 1, 1));
  }

  function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
  }

  function fmtShortDate(iso) {
    if (!iso) return "";
    const d = new Date(`${iso}T00:00:00`);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleDateString("en-GB", { month: "short", year: "2-digit" }).replace(" ", " ’");
  }

  function fmtDateTime(iso) {
    const d = new Date(iso || "");
    if (Number.isNaN(d.getTime())) return "";
    return d.toLocaleString("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
  }

  function seasonEnd() {
    const today = new Date();
    const year = today.getMonth() >= 6 ? today.getFullYear() + 1 : today.getFullYear();
    return `${year}-06-30`;
  }

  function contractState(p) {
    if (!p.contract) return "none";
    return p.contract <= seasonEnd() ? "expiring" : "ok";
  }

  function contractChip(p) {
    const st = contractState(p);
    if (st === "none") return '<span class="i7-contract i7-contract--none">None listed</span>';
    const cls = st === "expiring" ? " i7-contract--exp" : "";
    return `<span class="i7-contract${cls}" title="${esc(fmtDate(p.contract))}">${esc(fmtShortDate(p.contract))}</span>`;
  }

  function hasHistory() {
    return (state.data?.coverage || []).some((c) => c.previous_month);
  }

  function statNum(v, kind) {
    if (v === null || v === undefined) return '<span class="i7-dim">–</span>';
    if (v === 0) return '<span class="i7-z">0</span>';
    if (kind === "g" || kind === "a") return `<span class="i7-ga i7-ga--${kind}">${v}</span>`;
    return `<span class="i7-hot">${v}</span>`;
  }

  function delta(v) {
    if (v === null || v === undefined) return '<span class="i7-dim">–</span>';
    if (v === 0) return '<span class="i7-z">0</span>';
    return v > 0 ? `<span class="i7-up">+${v}</span>` : `<span class="i7-down">${v}</span>`;
  }

  function gtCell(gt) {
    if (gt === null || gt === undefined) return '<span class="i7-dim">–</span>';
    const w = Math.max(0, Math.min(100, gt));
    return `<span class="i7-gt">${gt}%<span class="i7-gt__bar"><span style="width:${w}%;--gtc:${gtColour(gt)}"></span></span></span>`;
  }

  function nameTags(p) {
    const tags = [];
    if (p.is_new) tags.push('<span class="i7-tag i7-tag--new">New</span>');
    if (p.change && p.change.club_changed) tags.push('<span class="i7-tag i7-tag--moved">Moved</span>');
    return tags.join("");
  }

  function setStatus(msg, tone) {
    if (!msg) {
      els.status.className = "i7-toast hidden";
      els.status.innerHTML = "";
      return;
    }
    els.status.className = `i7-toast${tone ? ` ${tone}` : ""}`;
    els.status.innerHTML = `<div>${esc(msg)}</div><button type="button" aria-label="Dismiss" data-dismiss>×</button>`;
  }

  async function fetchJson(url, options) {
    const res = await fetch(url, { credentials: "same-origin", ...(options || {}) });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = data.detail || data.message || `HTTP ${res.status}`;
      throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
    }
    return data;
  }

  // ------------------------------------------------------------ load + render

  async function load() {
    try {
      state.data = await fetchJson("/api/insight7");
      hydrateFilters();
      render();
    } catch (err) {
      setStatus(`Could not load Insight7 data: ${err.message}`, "is-error");
    }
  }

  function hydrateFilters() {
    const d = state.data;
    const keepLeague = els.league.value;
    const keepSection = els.section.value;
    els.league.innerHTML =
      '<option value="">All leagues</option>' +
      d.coverage.map((c) => `<option value="${esc(c.league_key)}">${esc(c.league)}</option>`).join("");
    els.league.value = keepLeague;
    els.league.classList.toggle("hidden", d.coverage.length < 2);
    const keepSeason = els.season.value || "current";
    els.season.innerHTML =
      '<option value="current">Current bulletins</option><option value="">All seasons</option>' +
      (d.seasons || []).map((s) => `<option value="${esc(s)}">${esc(s)}</option>`).join("");
    els.season.value = keepSeason;
    els.season.classList.toggle("hidden", !d.players.some((p) => p.month < recentEdition()) && (d.seasons || []).length < 2);
    const cats = new Set(d.sections.map((s) => sectionInfo(s).cat));
    const extra = [...cats].filter((c) => !SECTION_CATS.some(([id]) => id === c));
    els.section.innerHTML =
      '<option value="">All Insight7 lists</option>' +
      SECTION_CATS.filter(([id]) => cats.has(id)).map(([id, label]) => `<option value="${id}">${esc(label)}</option>`).join("") +
      extra.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("");
    els.section.value = keepSection;
  }

  function render() {
    const d = state.data;
    if (!d) return;
    const leagues = d.coverage.length;
    const latest = d.months[d.months.length - 1];
    els.counts.textContent = d.reports.length
      ? `${leagues} league${leagues === 1 ? "" : "s"} · ${d.reports.length} bulletin${d.reports.length === 1 ? "" : "s"} · latest ${monthLabel(latest, true)}`
      : "No bulletins uploaded yet — upload your first Insight7 PDF.";
    renderKpis();
    renderPlayers();
    renderMonth();
    renderUploads();
  }

  // ------------------------------------------------------------ KPIs + spotlight

  function leaguePlayers() {
    const league = els.league.value;
    const season = els.season.value;
    const recent = recentEdition();
    return state.data.players.filter(
      (p) => (!league || p.league_key === league) && (!season || (season === "current" ? p.month >= recent : p.season === season)),
    );
  }

  function recentEdition() {
    const [y, m] = currentEdition().split("-").map(Number);
    const d = new Date(y, m - 1 - 3, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function renderKpis() {
    const d = state.data;
    if (!d.players.length) {
      els.kpis.innerHTML = "";
      return;
    }
    const list = leaguePlayers();
    const count = (id) => list.filter(SPOTS.find((s) => s.id === id).test).length;
    const scorer = [...list].sort((a, b) => (b.goals || 0) - (a.goals || 0) || (a.league_mins || 0) - (b.league_mins || 0))[0];
    const young = [...list]
      .filter((p) => (p.league_gt ?? 0) >= 50)
      .sort((a, b) => (a.age ?? 99) - (b.age ?? 99) || (b.league_mins || 0) - (a.league_mins || 0))[0];
    const history = hasHistory();
    const card = (o) => `<button type="button" class="i7-kpi-card${o.static ? " is-static" : ""}${o.spot && state.spot === o.spot ? " is-on" : ""}"
        style="--kpi:${o.colour}" ${o.spot ? `data-spot="${o.spot}"` : ""} ${o.player ? `data-player="${esc(o.player)}"` : ""}>
        <div class="i7-kpi-card__label">${esc(o.label)}</div>
        ${o.name ? `<div class="i7-kpi-card__name">${esc(o.name)}</div>` : `<div class="i7-kpi-card__value">${o.value}${o.small ? `<small>${esc(o.small)}</small>` : ""}</div>`}
        <div class="i7-kpi-card__hint">${esc(o.hint || "")}</div>
      </button>`;
    els.kpis.innerHTML = [
      card({ label: "Players tracked", value: list.length, hint: `${new Set(list.map((p) => clubParts(p.club).base)).size} clubs`, colour: "#f3f6fb", spot: "__all" }),
      card({
        label: "New this month",
        value: history ? count("new") : "–",
        hint: history ? "First time on the bulletin" : "Needs a second month",
        colour: "#f59e0b",
        spot: history ? "new" : "",
        static: !history,
      }),
      card({ label: `Contract ends ${fmtShortDate(seasonEnd())}`, value: count("expiring"), hint: "Out of contract this summer", colour: "#ef4444", spot: "expiring" }),
      card({ label: "No contract listed", value: count("none"), hint: "Scholars / unknown deal", colour: "#a78bfa", spot: "none" }),
      scorer && (scorer.goals || 0) > 0
        ? card({ label: "Top scorer", name: scorer.name, hint: `${scorer.goals} goals · ${scorer.age} · ${clubParts(scorer.club).base}`, colour: "#22c55e", player: scorer.key })
        : card({ label: "Top scorer", value: "–", colour: "#22c55e", static: true }),
      young
        ? card({ label: "Youngest regular", name: young.name, hint: `Age ${young.age} · ${young.league_gt}% game time`, colour: "#f472b6", player: young.key })
        : card({ label: "Youngest regular", value: "–", colour: "#f472b6", static: true }),
    ].join("");
  }

  function renderSpot(total, shown) {
    const list = leaguePlayers();
    const history = hasHistory();
    const buttons = SPOTS.filter((s) => !s.needsHistory || history).map((s) => {
      const label = s.id === "expiring" ? `Contract ends ${fmtShortDate(seasonEnd())}` : s.label;
      const n = list.filter(s.test).length;
      return `<button type="button" class="${state.spot === s.id ? "is-on" : ""}" style="--dot:${s.colour}" data-spot="${s.id}"><i></i>${esc(label)} <b>${n}</b></button>`;
    });
    els.spot.innerHTML = `<span class="i7-spot__label">Spotlight</span>${buttons.join("")}<span class="i7-spot__count">Showing <b>${shown}</b> of ${total}</span>`;
  }

  function toggleSpot(id) {
    state.spot = id === "__all" || state.spot === id ? "" : id;
    renderKpis();
    renderPlayers();
  }

  // ------------------------------------------------------------ players

  function sortValue(p, key) {
    if (key === "d_mins") return p.change ? p.change.league_mins : null;
    if (key === "d_ga") return p.change ? p.change.ga : null;
    const v = p[key];
    return typeof v === "string" ? v.toLowerCase() : v;
  }

  function filteredPlayers() {
    const q = els.search.value.trim().toLowerCase();
    const group = POS_GROUPS[state.pos];
    const maxAge = Number(els.age.value) || 0;
    const section = els.section.value;
    const spot = SPOTS.find((s) => s.id === state.spot);
    const list = leaguePlayers().filter((p) => {
      if (group && !group.includes(String(p.position || "").toUpperCase())) return false;
      if (maxAge && !(p.age <= maxAge)) return false;
      if (section && !(p.sections || []).some((s) => sectionInfo(s).cat === section)) return false;
      if (spot && !spot.test(p)) return false;
      if (q) {
        const hay = [p.name, p.club, p.agent, p.career_note, p.international, p.league].join(" ").toLowerCase();
        if (!hay.includes(q)) return false;
      }
      return true;
    });
    const key = state.sort;
    const dir = state.asc ? 1 : -1;
    list.sort((a, b) => {
      const va = sortValue(a, key);
      const vb = sortValue(b, key);
      const na = va === null || va === undefined || va === "";
      const nb = vb === null || vb === undefined || vb === "";
      if (na && nb) return a.name.localeCompare(b.name);
      if (na) return 1;
      if (nb) return -1;
      if (va < vb) return -dir;
      if (va > vb) return dir;
      return (b.league_mins || 0) - (a.league_mins || 0);
    });
    return list;
  }

  function columns() {
    const d = state.data;
    const history = hasHistory();
    const multiMonth = d.months.length > 1;
    const multiLeague = d.coverage.length > 1;
    const cols = [
      { key: "name", label: "Player", cell: (p) => `<div class="i7-who">${crestFor(p.club)}<div class="i7-who__txt"><div class="i7-name">${esc(p.name)}${nameTags(p)}</div>${p.international || p.agent ? `<div class="i7-name-sub">${esc([p.international, p.agent].filter(Boolean).join(" · "))}</div>` : ""}</div></div>` },
      { key: "age", label: "Age", cls: "c", cell: (p) => ageChip(p.age) },
      { key: "position", label: "Pos", cls: "c", cell: (p) => posChip(p.position) },
      {
        key: "club",
        label: "Club",
        cell: (p) => {
          const c = clubParts(p.club);
          return `<span class="i7-club">${esc(c.base)}</span>${c.tag ? `<span class="i7-club__tag">${esc(c.tag)}</span>` : ""}${multiLeague ? `<div class="i7-club-sub">${esc(p.league)} · ${esc(monthLabel(p.month))}</div>` : ""}`;
        },
      },
      { key: "contract", label: "Contract", cell: contractChip },
      { key: "league_mins", label: "Mins", cls: "num", cell: (p) => statNum(p.league_mins) },
      { key: "league_gt", label: "Game time", cls: "num", cell: (p) => gtCell(p.league_gt) },
      { key: "goals", label: "G", cls: "c num", cell: (p) => statNum(p.goals, "g") },
      { key: "assists", label: "A", cls: "c num", cell: (p) => statNum(p.assists, "a") },
      { key: "mins_per_ga", label: "Min/G+A", cls: "num", cell: (p) => (p.mins_per_ga ? `<span class="i7-hot">${p.mins_per_ga}</span>` : '<span class="i7-dim">–</span>') },
    ];
    if (history) {
      cols.push({ key: "d_mins", label: "Δ Mins", cls: "num", cell: (p) => delta(p.change ? p.change.league_mins : null) });
      cols.push({ key: "d_ga", label: "Δ G+A", cls: "num", cell: (p) => delta(p.change ? p.change.ga : null) });
    }
    cols.push({ key: "", label: "Insight7 lists", cell: (p) => (p.sections || []).map((s) => listTag(s)).join("") });
    if (multiMonth) cols.push({ key: "months_listed", label: "Months", cls: "c num", cell: (p) => statNum(p.months_listed) });
    return cols;
  }

  function renderPlayers() {
    const d = state.data;
    if (!d.reports.length) {
      els.tableWrap.classList.add("hidden");
      els.cards.classList.add("hidden");
      els.spot.innerHTML = "";
      els.empty.innerHTML =
        "<strong>No Insight7 bulletins yet</strong>Click <b>Upload PDFs</b> (or drop PDFs anywhere on this page). Upload one bulletin per league each month and players are consolidated here.";
      els.empty.classList.remove("hidden");
      els.drawer.classList.add("hidden");
      return;
    }
    const list = filteredPlayers();
    state.visible = list;
    renderSpot(leaguePlayers().length, list.length);
    for (const b of els.pos.querySelectorAll("[data-pos]")) b.classList.toggle("is-on", b.dataset.pos === state.pos);
    for (const b of els.layout.querySelectorAll("[data-layout]")) b.classList.toggle("is-on", b.dataset.layout === state.layout);

    els.empty.classList.toggle("hidden", list.length > 0);
    els.empty.innerHTML = "<strong>No players match</strong>Clear a filter or spotlight to see more.";
    const showTable = state.layout === "table" && list.length > 0;
    const showCards = state.layout === "cards" && list.length > 0;
    els.tableWrap.classList.toggle("hidden", !showTable);
    els.cards.classList.toggle("hidden", !showCards);

    if (showTable) {
      const cols = columns();
      els.head.innerHTML = `<tr>${cols
        .map((c) => {
          const cls = [c.cls || "", c.key && c.key === state.sort ? `is-sorted${state.asc ? " is-asc" : ""}` : ""].join(" ").trim();
          return `<th${c.key ? ` data-sort="${c.key}"` : ""}${cls ? ` class="${cls}"` : ""}>${esc(c.label)}</th>`;
        })
        .join("")}</tr>`;
      els.rows.innerHTML = list
        .map((p) => `<tr data-key="${esc(p.key)}" class="${p.key === state.selected ? "is-on" : ""}">${cols.map((c) => `<td${c.cls ? ` class="${c.cls}"` : ""}>${c.cell(p)}</td>`).join("")}</tr>`)
        .join("");
    }
    if (showCards) {
      els.cards.innerHTML = list.map(cardHtml).join("");
    }
    if (state.selected) renderDrawer();
  }

  function cardHtml(p) {
    const c = clubParts(p.club);
    return `<button type="button" class="i7-card-p${p.key === state.selected ? " is-on" : ""}" data-key="${esc(p.key)}" style="--h:${clubHue(p.club)}">
      <div class="i7-card-p__head">
        ${crestFor(p.club)}
        <div style="min-width:0">
          <div class="i7-card-p__name">${esc(p.name)}${nameTags(p)}</div>
          <div class="i7-card-p__meta">${esc(c.base)}${c.tag ? ` ${esc(c.tag)}` : ""}</div>
        </div>
      </div>
      <div class="i7-card-p__stats">
        ${ring(p.league_gt)}
        <div class="i7-card-p__stat"><b>${p.league_mins ?? "–"}</b><span>Mins</span></div>
        <div class="i7-card-p__stat"><b>${p.goals ?? 0}</b><span>Goals</span></div>
        <div class="i7-card-p__stat"><b>${p.assists ?? 0}</b><span>Assists</span></div>
      </div>
      <div class="i7-card-p__foot">
        <div class="i7-card-p__lists">${posChip(p.position)}&nbsp;${ageChip(p.age)}&nbsp;${(p.sections || []).slice(0, 2).map((s) => listTag(s)).join("")}</div>
        ${contractChip(p)}
      </div>
    </button>`;
  }

  function findPlayer(key) {
    const d = state.data;
    return d.players.find((p) => p.key === key) || d.dropped.find((p) => p.key === key) || null;
  }

  function latestMonthFor(leagueKey) {
    const c = state.data.coverage.find((x) => x.league_key === leagueKey);
    return c ? c.latest_month : "";
  }

  function sparkline(history) {
    const pts = history.filter((h) => h.league_mins != null);
    if (pts.length < 2) return "";
    const w = 360;
    const h = 64;
    const pad = 26;
    const max = Math.max(...pts.map((x) => x.league_mins), 1);
    const xy = pts.map((x, i) => [pad + (i * (w - pad * 2)) / (pts.length - 1), h - 16 - ((x.league_mins / max) * (h - 26))]);
    const line = xy.map(([x, y], i) => `${i ? "L" : "M"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const area = `${line} L${xy[xy.length - 1][0].toFixed(1)},${h - 16} L${xy[0][0].toFixed(1)},${h - 16} Z`;
    return `<svg class="i7-spark" viewBox="0 0 ${w} ${h}">
      <defs><linearGradient id="i7grad" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="#f59e0b" stop-opacity="0.35"/><stop offset="1" stop-color="#f59e0b" stop-opacity="0"/></linearGradient></defs>
      <path class="area" d="${area}"/><path class="line" d="${line}"/>
      ${xy.map(([x, y], i) => `<circle cx="${x}" cy="${y}" r="3"/><text x="${x}" y="${h - 3}" text-anchor="middle">${esc(monthLabel(pts[i].month))}</text>`).join("")}
    </svg>`;
  }

  function renderDrawer() {
    const p = findPlayer(state.selected);
    if (!p) {
      els.drawer.classList.add("hidden");
      return;
    }
    els.drawer.classList.remove("hidden");
    els.drawer.style.setProperty("--h", clubHue(p.club));
    const c = clubParts(p.club);
    const facts = [
      ["League", (p.leagues || [p.league]).join(", ")],
      ["Contract", p.contract ? `${fmtDate(p.contract)}${contractState(p) === "expiring" ? " · expires this season" : ""}` : "None listed"],
      ["Agent", p.agent],
      ["International", p.international],
      ["Int'l debut", p.debut ? (/^\d{4}-/.test(p.debut) ? fmtDate(p.debut) : p.debut) : ""],
      ["Career", p.career_note],
      ["First listed", monthLabel(p.first_month, true)],
    ].filter(([, v]) => v);
    const status = p.is_current ? "" : `<span class="i7-tag" style="color:#fca5a5;border-color:rgba(239,68,68,.5)">Not on the ${esc(monthLabel(latestMonthFor(p.league_key), true))} bulletin</span>`;
    const hist = p.history || [];
    els.drawer.innerHTML = `
      <div class="i7-drawer__hero">
        <button type="button" class="i7-close" data-close aria-label="Close">×</button>
        <div class="i7-drawer__top">
          ${crestFor(p.club, "lg")}
          <div>
            <h2>${esc(p.name)}</h2>
            <div class="i7-drawer__meta">${posChip(p.position)} ${ageChip(p.age)} <span>${esc(c.base)}${c.tag ? ` ${esc(c.tag)}` : ""}</span></div>
          </div>
        </div>
        <div class="i7-drawer__tags">${nameTags(p)}${status}${(p.sections || []).map((s) => listTag(s, true)).join("")}</div>
      </div>
      <div class="i7-drawer__body">
        <div class="i7-dkpis">
          <div class="i7-dkpi i7-dkpi--ring">${ring(p.league_gt, true)}</div>
          <div class="i7-dkpi"><b>${p.league_mins ?? "–"}</b><span>League mins</span></div>
          <div class="i7-dkpi"><b>${p.goals ?? 0} · ${p.assists ?? 0}</b><span>Goals · assists</span></div>
          <div class="i7-dkpi"><b>${p.mins_per_ga ?? "–"}</b><span>Min per G+A</span></div>
        </div>
        <dl class="i7-facts">${facts.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
        <h3 class="i7-h3">Month by month</h3>
        ${sparkline(hist)}
        <table class="i7-hist">
          <thead><tr><th>Month</th><th>Club</th><th class="num">Mins</th><th class="num">GT</th><th class="num">G</th><th class="num">A</th></tr></thead>
          <tbody>${[...hist]
            .reverse()
            .map(
              (h) => `<tr title="${esc((h.sections || []).join(" · "))}">
                <td>${esc(monthLabel(h.month))}</td>
                <td>${esc(clubParts(h.club).base)}</td>
                <td class="num">${h.league_mins ?? ""}</td>
                <td class="num">${h.league_gt != null ? `${h.league_gt}%` : ""}</td>
                <td class="num">${h.goals ?? ""}</td>
                <td class="num">${h.assists ?? ""}</td>
              </tr>`,
            )
            .join("")}</tbody>
        </table>
        ${hist.length < 2 ? '<p class="i7-note">The trend line appears once next month’s bulletin is uploaded.</p>' : ""}
      </div>`;
  }

  function selectPlayer(key, keep) {
    state.selected = !keep && state.selected === key ? "" : key;
    for (const el of document.querySelectorAll("#i7Rows tr, #i7Cards .i7-card-p")) el.classList.toggle("is-on", el.dataset.key === state.selected);
    if (state.selected) renderDrawer();
    else els.drawer.classList.add("hidden");
  }

  function exportCsv() {
    const list = state.visible || [];
    const cols = [
      ["Player", (p) => p.name],
      ["Age", (p) => p.age],
      ["Position", (p) => p.position],
      ["Club", (p) => p.club],
      ["League", (p) => p.league],
      ["Month", (p) => p.month],
      ["Contract", (p) => p.contract],
      ["League mins", (p) => p.league_mins],
      ["Game time %", (p) => p.league_gt],
      ["Goals", (p) => p.goals],
      ["Assists", (p) => p.assists],
      ["Mins per G+A", (p) => p.mins_per_ga],
      ["Change mins", (p) => (p.change ? p.change.league_mins : "")],
      ["Change G+A", (p) => (p.change ? p.change.ga : "")],
      ["New this month", (p) => (p.is_new ? "Yes" : "")],
      ["International", (p) => p.international],
      ["Debut", (p) => p.debut],
      ["Agent", (p) => p.agent],
      ["Career note", (p) => p.career_note],
      ["Insight7 lists", (p) => (p.sections || []).join("; ")],
      ["Months listed", (p) => p.months_listed],
    ];
    const cell = (v) => {
      const s = String(v ?? "");
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const lines = [cols.map(([h]) => h).join(",")].concat(list.map((p) => cols.map(([, f]) => cell(f(p))).join(",")));
    const blob = new Blob([`\ufeff${lines.join("\n")}`], { type: "text/csv;charset=utf-8" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `insight7-players-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    setTimeout(() => URL.revokeObjectURL(a.href), 2000);
  }

  // ------------------------------------------------------------ this month

  function mini(p, value) {
    return `<div class="i7-mini" data-key="${esc(p.key)}">
      ${crestFor(p.club, "sm")}
      <div class="i7-mini__txt"><div class="i7-mini__name">${esc(p.name)}</div><div class="i7-mini__meta">${esc([p.position, p.age, clubParts(p.club).base].filter(Boolean).join(" · "))}</div></div>
      <div class="i7-mini__val">${value}</div>
    </div>`;
  }

  function col(title, colour, players, valueFn, emptyText, limit = 8) {
    const shown = players.slice(0, limit);
    const more = players.length - shown.length;
    return `<div class="i7-col" style="--cc:${colour}"><h3>${esc(title)}<b>${players.length}</b></h3>${
      shown.length ? shown.map((p) => mini(p, valueFn(p))).join("") : `<div class="i7-col__none">${esc(emptyText)}</div>`
    }${more > 0 ? `<div class="i7-col__more">+${more} more — use the Players spotlight</div>` : ""}</div>`;
  }

  function renderMonth() {
    const d = state.data;
    if (!d.coverage.length) {
      els.month.innerHTML = '<div class="i7-empty"><strong>Nothing to compare yet</strong>Upload a bulletin to get started.</div>';
      return;
    }
    els.month.innerHTML = d.coverage
      .map((c) => {
        const current = d.players.filter((p) => p.league_key === c.league_key);
        const hasPrev = Boolean(c.previous_month);
        const added = current.filter((p) => p.is_new).sort((a, b) => (b.league_mins || 0) - (a.league_mins || 0));
        const dropped = d.dropped.filter((p) => p.league_key === c.league_key && p.month === c.previous_month);
        const risers = current.filter((p) => p.change && p.change.league_mins > 0).sort((a, b) => b.change.league_mins - a.change.league_mins);
        const ga = current
          .filter((p) => (p.ga || 0) > 0)
          .sort((a, b) => (b.ga || 0) - (a.ga || 0) || (a.mins_per_ga || 9999) - (b.mins_per_ga || 9999));
        const byMins = (a, b) => (b.league_mins || 0) - (a.league_mins || 0);
        const expiring = current.filter((p) => contractState(p) === "expiring").sort(byMins);
        const noDeal = current.filter((p) => contractState(p) === "none").sort(byMins);
        const cols = [];
        if (hasPrev) {
          cols.push(col("New additions", "#f59e0b", added, (p) => `${p.league_mins ?? "–"}′`, "No new names this month."));
          cols.push(col("Dropped off", "#64748b", dropped, (p) => `${p.league_mins ?? "–"}′`, "Nobody dropped off."));
          cols.push(col("Biggest minutes gains", "#22c55e", risers, (p) => `<span class="i7-up">+${p.change.league_mins}</span>`, "No changes yet."));
        }
        cols.push(col("Goal involvements", "#22d3ee", ga, (p) => `${p.goals || 0}G · ${p.assists || 0}A`, "No goals or assists listed."));
        cols.push(col(`Contract ends ${fmtShortDate(seasonEnd())}`, "#ef4444", expiring, (p) => `${p.league_mins ?? "–"}′`, "None expiring."));
        cols.push(col("No contract listed", "#a78bfa", noDeal, (p) => `${p.league_mins ?? "–"}′`, "All players have a contract listed."));
        const sub = hasPrev
          ? `${monthLabel(c.latest_month, true)} vs ${monthLabel(c.previous_month, true)} · ${current.length} players`
          : `${monthLabel(c.latest_month, true)} · ${current.length} players`;
        return `<section class="i7-card">
          <div class="i7-card__head"><h2>${esc(c.league)}</h2><span class="i7-card__sub">${esc(sub)}</span></div>
          ${hasPrev ? "" : '<p class="i7-card__hint">Upload next month’s bulletin for this league to unlock new additions, drop-offs and minute gains.</p>'}
          <div class="i7-cols">${cols.join("")}</div>
        </section>`;
      })
      .join("");
  }

  // ------------------------------------------------------------ uploads

  function coverageMonths() {
    const d = state.data;
    const now = new Date();
    let end = currentEdition();
    if (d.months.length && d.months[d.months.length - 1] > end) end = d.months[d.months.length - 1];
    const seasonYear = now.getMonth() >= 6 ? now.getFullYear() : now.getFullYear() - 1;
    let start = `${seasonYear}-08`;
    if (d.months.length && d.months[0] < start) start = d.months[0];
    const [ey, em] = end.split("-").map(Number);
    const floor = new Date(ey, em - 12, 1);
    const floorKey = `${floor.getFullYear()}-${String(floor.getMonth() + 1).padStart(2, "0")}`;
    if (start < floorKey) start = floorKey;
    const out = [];
    let [y, m] = start.split("-").map(Number);
    while (out.length < 24) {
      const ym = `${y}-${String(m).padStart(2, "0")}`;
      out.push(ym);
      if (ym >= end) break;
      m += 1;
      if (m > 12) {
        m = 1;
        y += 1;
      }
    }
    return out.slice(-12);
  }

  function currentEdition() {
    const d = new Date(Date.now() - 10 * 86400000);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
  }

  function renderUploads() {
    const d = state.data;
    const thisMonth = currentEdition();
    if (!d.coverage.length) {
      els.coverage.innerHTML = '<div class="i7-empty" style="border:0">No leagues yet. Each league appears here after its first bulletin is uploaded.</div>';
      els.uploads.innerHTML = '<div class="i7-empty" style="border:0">No bulletins uploaded.</div>';
      return;
    }
    const months = coverageMonths();
    els.coverage.innerHTML = `<table class="i7-grid">
      <thead><tr><th>League</th>${months.map((m) => `<th class="${m === thisMonth ? "is-current" : ""}">${esc(monthLabel(m))}</th>`).join("")}</tr></thead>
      <tbody>${d.coverage
        .map(
          (c) => `<tr><td><b>${esc(c.league)}</b></td>${months
            .map((m) => {
              const r = c.months[m];
              if (r) return `<td><a class="i7-cell i7-cell--have" href="/api/insight7/reports/${esc(r.id)}/pdf" target="_blank" rel="noopener" title="Open PDF · ${esc(r.filename)}">✓ ${r.player_count}</a></td>`;
              if (m === thisMonth) return '<td><span class="i7-cell i7-cell--due" title="This edition has not been uploaded yet">Due</span></td>';
              return '<td><span class="i7-cell i7-cell--miss">—</span></td>';
            })
            .join("")}</tr>`,
        )
        .join("")}</tbody>
    </table>`;

    els.uploads.innerHTML = `<table class="i7-grid i7-uploads-grid">
      <thead><tr><th>League</th><th>Edition</th><th>Bulletin date</th><th>Season</th><th>Players</th><th>Uploaded</th><th>File</th><th></th></tr></thead>
      <tbody>${d.reports
        .map(
          (r) => `<tr>
            <td><b>${esc(r.league)}</b></td>
            <td>${esc(monthLabel(r.month, true))}</td>
            <td>${esc(fmtDate(r.report_date))}</td>
            <td>${esc(r.season || "")}</td>
            <td><span class="i7-hot">${r.player_count}</span></td>
            <td>${esc(fmtDateTime(r.uploaded_at))}${r.uploaded_by ? ` · ${esc(r.uploaded_by)}` : ""}</td>
            <td><a class="i7-file" href="/api/insight7/reports/${esc(r.id)}/pdf" target="_blank" rel="noopener" title="${esc(r.filename)}">${esc(r.filename)}</a></td>
            <td><div class="i7-actions">
              <button type="button" class="i7-btn i7-btn--small" data-edit="${esc(r.id)}">Edit</button>
              <button type="button" class="i7-btn i7-btn--small i7-btn--danger" data-del="${esc(r.id)}">Delete</button>
            </div></td>
          </tr>`,
        )
        .join("")}</tbody>
    </table>`;
  }

  const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
  const RETRY_WAITS_MS = [4000, 12000, 25000];
  const isNetworkError = (msg) => /failed to fetch|networkerror|load failed|HTTP 5\d\d/i.test(String(msg || ""));

  async function uploadOne(file) {
    let lastError = "";
    for (let attempt = 0; attempt <= RETRY_WAITS_MS.length; attempt += 1) {
      const form = new FormData();
      form.append("files", file);
      try {
        const res = await fetchJson("/api/insight7/upload", { method: "POST", body: form });
        const r = (res.results || [])[0];
        if (!r) return { filename: file.name, ok: false, error: "No response for this file" };
        return r;
      } catch (err) {
        lastError = err.message;
        // Network drops (e.g. a server restart) are retried; real rejections are not.
        if (!isNetworkError(lastError)) break;
        if (attempt < RETRY_WAITS_MS.length) await sleep(RETRY_WAITS_MS[attempt]);
      }
    }
    return { filename: file.name, ok: false, error: lastError || "Upload failed" };
  }

  function uploadSummary(results) {
    const ok = results.filter((r) => r.ok);
    const bad = results.filter((r) => !r.ok);
    const replaced = ok.filter((r) => r.report.replaced).length;
    const lines = [
      `${ok.length} of ${results.length} bulletin${results.length === 1 ? "" : "s"} uploaded${replaced ? ` (${replaced} replaced an earlier upload)` : ""}.`,
    ];
    if (ok.length && ok.length <= 6) {
      for (const r of ok) lines.push(`✓ ${r.report.league} · ${monthLabel(r.report.month, true)} edition — ${r.report.player_count} players`);
    }
    for (const r of bad) lines.push(`✗ ${r.filename} — ${r.error}`);
    return lines.join("\n");
  }

  async function uploadFiles(fileList) {
    const files = [...fileList].filter((f) => /\.pdf$/i.test(f.name) || f.type === "application/pdf");
    if (!files.length) {
      setStatus("Only PDF files can be uploaded.", "is-error");
      return;
    }
    els.uploadBtn.disabled = true;
    const results = [];
    try {
      for (let i = 0; i < files.length; i += 1) {
        const file = files[i];
        setStatus(`Uploading ${i + 1} of ${files.length} — ${file.name}`);
        results.push(await uploadOne(file));
        if ((i + 1) % 5 === 0 && i + 1 < files.length) await load();
      }
    } finally {
      els.uploadBtn.disabled = false;
      els.file.value = "";
      await load();
    }
    const failed = files.filter((f) => results.some((r) => !r.ok && r.filename === f.name && isNetworkError(r.error)));
    state.failedFiles = failed;
    setStatus(uploadSummary(results), results.some((r) => !r.ok) ? "is-error" : "is-ok");
    if (failed.length) {
      const retry = document.createElement("button");
      retry.type = "button";
      retry.className = "i7-btn i7-btn--small";
      retry.textContent = `Retry ${failed.length} failed`;
      retry.addEventListener("click", () => uploadFiles(state.failedFiles || []));
      els.status.firstElementChild.append(document.createElement("br"), retry);
    }
  }

  async function editReport(id) {
    const r = state.data.reports.find((x) => x.id === id);
    if (!r) return;
    const league = window.prompt("League name", r.league);
    if (league === null) return;
    const month = window.prompt("Edition month (YYYY-MM)", r.month);
    if (month === null) return;
    const form = new FormData();
    form.append("league", league);
    form.append("month", month);
    try {
      await fetchJson(`/api/insight7/reports/${encodeURIComponent(id)}`, { method: "POST", body: form });
      setStatus("Bulletin updated.", "is-ok");
      await load();
    } catch (err) {
      setStatus(`Could not update: ${err.message}`, "is-error");
    }
  }

  async function deleteReport(id) {
    const r = state.data.reports.find((x) => x.id === id);
    if (!r || !window.confirm(`Delete the ${r.league} bulletin for ${monthLabel(r.month, true)}?`)) return;
    try {
      await fetchJson(`/api/insight7/reports/${encodeURIComponent(id)}`, { method: "DELETE" });
      setStatus("Bulletin deleted.", "is-ok");
      await load();
    } catch (err) {
      setStatus(`Could not delete: ${err.message}`, "is-error");
    }
  }

  // ------------------------------------------------------------ wiring

  function setTab(tab) {
    state.tab = tab;
    for (const b of els.tabs.querySelectorAll("[data-tab]")) b.classList.toggle("is-on", b.dataset.tab === tab);
    for (const v of document.querySelectorAll(".i7-view")) v.classList.toggle("hidden", v.dataset.view !== tab);
  }

  els.tabs.addEventListener("click", (e) => {
    const b = e.target.closest("[data-tab]");
    if (b) setTab(b.dataset.tab);
  });

  els.status.addEventListener("click", (e) => {
    if (e.target.closest("[data-dismiss]")) setStatus("");
  });

  els.uploadBtn.addEventListener("click", () => els.file.click());
  els.dropBtn.addEventListener("click", () => els.file.click());
  els.file.addEventListener("change", () => {
    if (els.file.files.length) uploadFiles(els.file.files);
  });

  els.search.addEventListener("input", renderPlayers);
  for (const el of [els.age, els.section]) el.addEventListener("change", renderPlayers);
  for (const el of [els.league, els.season]) {
    el.addEventListener("change", () => {
      renderKpis();
      renderPlayers();
    });
  }
  els.csv.addEventListener("click", exportCsv);

  els.pos.addEventListener("click", (e) => {
    const b = e.target.closest("[data-pos]");
    if (!b) return;
    state.pos = b.dataset.pos;
    renderPlayers();
  });

  els.layout.addEventListener("click", (e) => {
    const b = e.target.closest("[data-layout]");
    if (!b) return;
    state.layout = b.dataset.layout;
    renderPlayers();
  });

  els.kpis.addEventListener("click", (e) => {
    const b = e.target.closest(".i7-kpi-card");
    if (!b) return;
    if (b.dataset.player) selectPlayer(b.dataset.player, true);
    else if (b.dataset.spot) toggleSpot(b.dataset.spot);
  });

  els.spot.addEventListener("click", (e) => {
    const b = e.target.closest("[data-spot]");
    if (b) toggleSpot(b.dataset.spot);
  });

  els.head.addEventListener("click", (e) => {
    const th = e.target.closest("th[data-sort]");
    if (!th) return;
    const key = th.dataset.sort;
    if (state.sort === key) state.asc = !state.asc;
    else {
      state.sort = key;
      state.asc = ["name", "club", "position", "contract", "age", "mins_per_ga"].includes(key);
    }
    renderPlayers();
  });

  els.rows.addEventListener("click", (e) => {
    const tr = e.target.closest("tr[data-key]");
    if (tr) selectPlayer(tr.dataset.key);
  });

  els.cards.addEventListener("click", (e) => {
    const card = e.target.closest("[data-key]");
    if (card) selectPlayer(card.dataset.key);
  });

  els.drawer.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) selectPlayer(state.selected);
  });

  els.month.addEventListener("click", (e) => {
    const row = e.target.closest("[data-key]");
    if (!row) return;
    setTab("players");
    selectPlayer(row.dataset.key, true);
  });

  els.uploads.addEventListener("click", (e) => {
    const edit = e.target.closest("[data-edit]");
    if (edit) editReport(edit.dataset.edit);
    const del = e.target.closest("[data-del]");
    if (del) deleteReport(del.dataset.del);
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && state.selected) selectPlayer(state.selected);
  });

  let dragDepth = 0;
  window.addEventListener("dragenter", (e) => {
    if (![...(e.dataTransfer?.types || [])].includes("Files")) return;
    dragDepth += 1;
    els.dragOver.classList.remove("hidden");
  });
  window.addEventListener("dragleave", () => {
    dragDepth = Math.max(0, dragDepth - 1);
    if (!dragDepth) els.dragOver.classList.add("hidden");
  });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    dragDepth = 0;
    els.dragOver.classList.add("hidden");
    if (e.dataTransfer?.files?.length) uploadFiles(e.dataTransfer.files);
  });

  load();
})();
