/* Shared club cell for Who to Scout and the Watch list.

   The server decides the sentence (app/transfer_status.present_scout_club).
   A current loan is the playing club plus "on loan from {parent}". A parent
   or U21 row uses that same sentence. This file only paints it.
*/
(function (root) {
  "use strict";

  function clubCell(player, { esc, exportMode = false, cellClass = "col-club" } = {}) {
    const encode = typeof esc === "function" ? esc : (value) => String(value ?? "");
    const display = player?.transfer?.display;
    const dataClub = player?.club || "—";
    const classAttr = cellClass ? ` class="${encode(cellClass)}"` : "";
    if (!display?.line) {
      return `<td${classAttr} title="${encode(player?.club || "")}">${encode(dataClub)}</td>`;
    }
    const held = display.held_club || dataClub;
    const separator = exportMode ? " &middot; " : "";
    const heldClass = display.struck ? "club-was" : "club-held";
    const inner =
      `<span class="${heldClass}">${encode(held)}</span>${separator}` +
      `<span class="${encode(display.line_class || "")}">${encode(display.line)}</span>`;
    return `<td${classAttr} title="${encode(display.title || "")}">${inner}</td>`;
  }

  function rowCss(player) {
    const css = player?.transfer?.display?.css;
    return css ? String(css) : "";
  }

  root.ScoutClubDisplay = { clubCell, rowCss };
})(typeof window !== "undefined" ? window : globalThis);
