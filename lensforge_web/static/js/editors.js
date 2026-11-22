// Merit Function Editor, Multi-Configuration Editor, Python Shell and Undo History (bottom and left docks),
// as lensforge_qt/mfe.py, mce.py, script_console.py and the Qt undo view.
import { App, run, call, status, statusError, onState, docks, cmd } from "./core.js";
import * as engine from "./engine.js";
import { el, esc, btn, select, numInput, check, dialog, message, prompt, popupMenu, iconImg, later, popupBlocked, keepInView } from "./ui.js";

// ================================================================== a searchable menu for a Type cell
/** The list under a Type cell being edited: every operand with its description, grouped; typing filters it
 *  (name first, then description). groups: [{group, items: [[name, description]]}]; onpick(name). */
class OperandMenu {
  constructor(input, td, groups, onpick) {
    Object.assign(this, { input, td, groups, onpick });
    this.filtered = false;
    this.hi = -1;
    this.busy = false;     // a finger or the mouse is on the list (the input's blur must not commit then)
    this.list = el("div", { class: "combo-list", role: "listbox", "aria-label": "Operands" });
    this.list.addEventListener("pointerdown", (e) => {
      this.busy = true;
      if (e.pointerType === "mouse") e.preventDefault();   // keep the focus (and the typing) in the cell
    });
    this.list.addEventListener("click", (e) => {
      const row = e.target.closest(".combo-item");
      if (row) this.onpick(row.dataset.name);
      else this.input.focus({ preventScroll: true });
      this.busy = false;
    });
    input.addEventListener("input", () => { this.filtered = true; this.fill(); });
    input.ownerDocument.body.append(this.list);
    this.fill();
  }

  /** The rows to show: all of them grouped, or (after typing) the matches, best first. */
  entries() {
    const all = this.groups.flatMap((g) => g.items.map(([k, d]) => ({ k, d, g: g.group })));
    const q = this.input.value.trim().toUpperCase();
    if (!this.filtered || !q) return { rows: all, grouped: true };
    const rank = ({ k, d }) => (k.startsWith(q) ? 0 : k.includes(q) ? 1 : d.toUpperCase().includes(q) ? 2 : 3);
    return { rows: all.filter((x) => rank(x) < 3).sort((a, b) => rank(a) - rank(b)), grouped: false };
  }

  fill() {
    const { rows, grouped } = this.entries();
    this.rows = rows;
    const cur = this.input.value.trim().toUpperCase();
    this.hi = grouped ? rows.findIndex((x) => x.k === cur) : rows.length ? 0 : -1;
    const out = [];
    let g = null;
    rows.forEach((x, i) => {
      if (grouped && x.g !== g) { g = x.g; out.push(el("div", { class: "combo-group" }, g)); }
      out.push(el("div", { class: "combo-item" + (i === this.hi ? " hi" : ""), role: "option", "data-name": x.k, "data-i": i, title: `${x.k}: ${x.d}` },
        el("b", {}, x.k), el("span", {}, x.d)));
    });
    if (!rows.length) out.push(el("div", { class: "combo-none" }, "No operand matches; Enter keeps what you typed"));
    this.list.replaceChildren(...out);
    this.place();
    this.list.querySelector(".combo-item.hi")?.scrollIntoView({ block: grouped ? "center" : "nearest" });
  }

  place() {
    const v = this.td.ownerDocument.defaultView;
    const r = this.td.getBoundingClientRect();
    const vh = v.visualViewport ? v.visualViewport.height : v.innerHeight;   // the on-screen keyboard shrinks it
    const w = Math.min(520, v.innerWidth - 8);
    const below = vh - r.bottom - 6, above = r.top - 6;
    const up = below < 200 && above > below;
    const h = Math.max(120, Math.min(340, up ? above : below));
    Object.assign(this.list.style, { left: Math.max(4, Math.min(r.left, v.innerWidth - w - 4)) + "px", width: w + "px", maxHeight: h + "px",
      top: up ? "" : r.bottom + 1 + "px", bottom: up ? v.innerHeight - r.top + 1 + "px" : "" });
  }

  /** Arrow keys move the highlight; Enter / Tab take it. Returns true if the key was used. */
  key(e) {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      if (!this.rows.length) return true;
      this.hi = Math.max(0, Math.min(this.rows.length - 1, this.hi + (e.key === "ArrowDown" ? 1 : -1)));
      if (e.key === "ArrowUp" && this.hi < 0) this.hi = 0;
      this.list.querySelectorAll(".combo-item").forEach((d) => d.classList.toggle("hi", +d.dataset.i === this.hi));
      this.list.querySelector(".combo-item.hi")?.scrollIntoView({ block: "nearest" });
      return true;
    }
    return false;
  }

  /** What Enter / Tab put in the cell: the highlighted operand, or the typed text if nothing matches. */
  choice() { return this.hi >= 0 && this.rows[this.hi] ? this.rows[this.hi].k : this.input.value; }
  close() { this.list.remove(); }
}

// ================================================================== a small spreadsheet widget
/** cols: [{title, width, tip, align}]; getRows() -> [{head, cells: [{t, e, cls, tip, editable, menu, wide}]}];
 *  menu: [{group, items: [[name, description]]}] makes the cell a Type cell with a searchable operand list;
 *  onEdit(row, col, text); onContext(row, col, event, sheet) */
class Sheet {
  constructor({ cols, getRows, onEdit, onContext, scope, headTip }) {
    Object.assign(this, { cols, getRows, onEdit, onContext, scope, headTip });
    this.cur = { row: 0, col: 0 };
    this.anchor = null;
    this.sel = null;   // {r0, r1, c0, c1}
    this.editing = null;
    this.element = el("div", { class: "editor-sheet", tabindex: 0 });
    this.element.addEventListener("focusin", () => { App.focusScope = scope; });
    this.element.addEventListener("keydown", (e) => this.key(e));
    this.element.addEventListener("pointerdown", (e) => this.pointer(e));
    // Safari can drop the focus a click gave the sheet (the cell is redrawn under the mouse): take it back
    this.element.addEventListener("click", () => {
      const doc = this.element.ownerDocument;
      if (!this.editing && !this.element.contains(doc.activeElement)) this.element.focus({ preventScroll: true });
    });
    if (scope) App.sheets[scope] = this.element;
    this.element.addEventListener("dblclick", (e) => { const td = e.target.closest("td[data-c]"); if (td) this.edit(+td.dataset.r, +td.dataset.c); });
    this.element.addEventListener("contextmenu", (e) => {
      const td = e.target.closest("td[data-c], th[data-c]");
      e.preventDefault();
      if (this.onContext) this.onContext(td ? +(td.dataset.r ?? -1) : -1, td ? +td.dataset.c : -1, e, this);
    });
  }

  rows() { return this.getRows(); }
  selectedRows() {
    if (this.sel) { const out = []; for (let r = this.sel.r0; r <= this.sel.r1; r++) out.push(r); return out; }
    return this.rows().length ? [this.cur.row] : [];
  }
  selectedCells() {
    const out = [];
    const s = this.sel || { r0: this.cur.row, r1: this.cur.row, c0: this.cur.col, c1: this.cur.col };
    for (let r = s.r0; r <= s.r1; r++) for (let c = s.c0; c <= s.c1; c++) out.push([r, c]);
    return out;
  }
  setCurrent(row, col) { this.cur = { row, col }; this.sel = null; this.anchor = { row, col }; this.render(); }

  render() {
    if (this.editing) return;   // redrawn when the edit ends (a redraw would drop the cell being typed in)
    const rows = this.rows();
    if (this.cur.row >= rows.length) this.cur.row = Math.max(0, rows.length - 1);
    const head = el("tr", {}, el("th", { style: { width: "36px" } }, ""), ...this.cols.map((c, i) =>
      el("th", { style: { width: (c.width || 90) + "px" }, title: c.tip || "", "data-c": i, class: c.headCls || "" }, c.title)));
    const body = el("tbody");
    rows.forEach((r, i) => {
      const tr = el("tr");
      tr.append(el("td", { class: "rowhead", title: r.headTip || "" }, r.head ?? String(i + 1)));
      r.cells.forEach((c, k) => {
        const cls = [c.cls || ""];
        if (this.cols[k].align === "right") cls.push("num");
        if (this.cols[k].align === "center") cls.push("center");
        if (this.cur.row === i && this.cur.col === k) cls.push("cur");
        const s = this.sel;
        const inSel = s && i >= s.r0 && i <= s.r1 && k >= s.c0 && k <= s.c1;
        if (c.menu && c.editable) cls.push("combo");
        const td = el("td", { class: cls.join(" "), "data-r": i, "data-c": k, title: c.tip || "" }, c.t ?? "");
        if (inSel) td.style.boxShadow = "inset 0 0 0 999px rgba(61,132,198,.16)";
        tr.append(td);
      });
      body.append(tr);
    });
    const t = el("table", { class: "sheet" }, el("thead", {}, head), body);
    const sc = [this.element.scrollLeft, this.element.scrollTop];
    this.element.replaceChildren(t);
    this.element.scrollLeft = sc[0];
    this.element.scrollTop = sc[1];
  }

  pointer(e) {
    const td = e.target.closest("td[data-c]");
    if (!td || (this.editing && this.editing.td.contains(e.target))) return;
    if (this.editing) this.commit();
    const row = +td.dataset.r, col = +td.dataset.c;
    // a Type cell opens its operand menu on a tap of its arrow, or of the cell when it is already selected
    if (td.classList.contains("combo") && !e.shiftKey && e.button === 0) {
      const onArrow = e.clientX > td.getBoundingClientRect().right - 20;
      if (onArrow || (this.cur.row === row && this.cur.col === col && !this.sel)) {
        e.preventDefault();
        this.edit(row, col, undefined, e.pointerType === "touch");
        return;
      }
    }
    // touch screens: a tap on the cell that is already selected edits it (opens the on-screen keyboard)
    if (e.pointerType === "touch" && !e.shiftKey && !this.sel && this.cur.row === row && this.cur.col === col) {
      const c = this.rows()[row]?.cells[col];
      if (c && c.editable) { e.preventDefault(); this.edit(row, col, undefined, true); return; }
    }
    if (e.shiftKey && this.anchor) {
      this.sel = { r0: Math.min(this.anchor.row, row), r1: Math.max(this.anchor.row, row), c0: Math.min(this.anchor.col, col), c1: Math.max(this.anchor.col, col) };
      this.cur = { row, col };
    } else if (e.button === 2 && this.sel && row >= this.sel.r0 && row <= this.sel.r1) {
      this.cur = { row, col };
    } else this.setCurrent(row, col);
    this.render();
    this.element.focus({ preventScroll: true });
  }

  move(dr, dc, extend) {
    const n = this.rows().length;
    if (!n) return;
    const row = Math.max(0, Math.min(this.cur.row + dr, n - 1)), col = Math.max(0, Math.min(this.cur.col + dc, this.cols.length - 1));
    if (extend) {
      if (!this.anchor) this.anchor = { ...this.cur };
      this.sel = { r0: Math.min(this.anchor.row, row), r1: Math.max(this.anchor.row, row), c0: Math.min(this.anchor.col, col), c1: Math.max(this.anchor.col, col) };
      this.cur = { row, col };
      this.render();
    } else this.setCurrent(row, col);
    this.element.querySelector("td.cur")?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }

  key(e) {
    if (this.editing) return;
    const plainKey = !e.ctrlKey && !e.metaKey && !e.altKey;
    const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] };
    if (moves[e.key] && !e.ctrlKey && !e.metaKey) { e.preventDefault(); this.move(...moves[e.key], e.shiftKey); return; }
    if (e.key === "Tab" && !e.ctrlKey) { e.preventDefault(); this.move(0, e.shiftKey ? -1 : 1); return; }
    if ((e.key === "Enter" || e.key === "F2") && plainKey) { e.preventDefault(); this.edit(this.cur.row, this.cur.col); return; }
    if (e.key.length === 1 && plainKey && !e.isComposing) { e.preventDefault(); this.edit(this.cur.row, this.cur.col, e.key); }
  }

  edit(row, col, initial, touch = false) {
    if (this.editing) {   // e.g. the double-click that follows a tap on a Type cell, which already opened it
      if (this.editing.row === row && this.editing.col === col) return;
      this.commit();
    }
    const r = this.rows()[row];
    if (!r) return;
    const c = r.cells[col];
    if (!c || !c.editable) return;
    this.setCurrent(row, col);
    const td = this.element.querySelector(`td[data-r="${row}"][data-c="${col}"]`);
    td.classList.add("editing");
    td.textContent = "";
    const input = el("input", { type: "text", value: initial ?? c.e ?? c.t, spellcheck: false, autocomplete: "off" });
    // opened by a finger: no on-screen keyboard over the list (a hardware keyboard still types and filters)
    if (c.menu && touch) input.setAttribute("inputmode", "none");
    td.append(input);
    this.editing = { td, input, row, col, original: c.e ?? c.t, menu: null };
    const menu = c.menu ? new OperandMenu(input, td, c.menu, (name) => { input.value = name; this.commit(); this.element.focus({ preventScroll: true }); }) : null;
    this.editing.menu = menu;
    if (menu && initial !== undefined) { menu.filtered = true; menu.fill(); }
    input.addEventListener("keydown", (e) => {
      if (menu && menu.key(e)) { e.preventDefault(); return; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); this.cancel(); this.element.focus(); }
      else if (e.key === "Enter") { e.preventDefault(); if (menu) input.value = menu.choice(); this.commit(); this.move(1, 0); this.element.focus(); }
      else if (e.key === "Tab") { e.preventDefault(); if (menu && menu.filtered) input.value = menu.choice(); this.commit(); this.move(0, e.shiftKey ? -1 : 1); this.element.focus(); }
    });
    input.addEventListener("blur", () => later(input, () => {
      if (!this.editing || this.editing.input !== input) return;
      if (menu && menu.busy) return;   // a tap on the list: its click picks (or refocuses)
      this.commit();
    }, 100));
    if (menu) {
      // a press outside the cell and its list ends the edit (the list kept it open while being scrolled)
      const outside = (e) => {
        if (!this.editing || this.editing.input !== input) { input.ownerDocument.removeEventListener("pointerdown", outside, true); return; }
        if (menu.list.contains(e.target) || e.target === input) return;
        menu.busy = false;
        input.ownerDocument.removeEventListener("pointerdown", outside, true);
        this.commit();
      };
      input.ownerDocument.addEventListener("pointerdown", outside, true);
    }
    input.focus({ preventScroll: true });
    if (initial === undefined) input.select();
  }

  endMenu(e) { if (e && e.menu) { e.menu.close(); e.menu = null; } }

  cancel() { this.endMenu(this.editing); this.editing = null; this.render(); }

  commit() {
    if (!this.editing) return;
    const e = this.editing;
    this.editing = null;
    this.endMenu(e);
    const v = e.input.value;
    this.render();
    if (String(v) !== String(e.original)) this.onEdit(e.row, e.col, v);
  }
}

function toolbarButton(label, tip, fn, shortcut) {
  return el("button", { type: "button", title: shortcut ? `${label} (${shortcut})\n${tip}` : `${label}\n${tip}`, onclick: fn }, label);
}

/** "Open in New Tab" / "Return to Main Tab": moves the editor's dock panel to its own browser tab and back. */
function popButton(getPanel) {
  const tipOut = "Move this editor into its own browser tab (or window), e.g. to keep it beside the lens on a second " +
    "screen. It stays connected to this page: every change shows in both at once. Closing the tab puts it back.";
  const b = toolbarButton("↗ Open in New Tab", tipOut, () => {
    const p = getPanel();
    if (!p) return;
    if (p.floating && p.floating.popout) p.area.dock(p);
    else p.area.popOut(p);
  });
  b.classList.add("pop-toggle");
  const set = (on) => {
    b.textContent = on ? "↙ Return to Main Tab" : "↗ Open in New Tab";
    b.title = on ? "Return to Main Tab\nPut this editor back into the main LensForge tab and close its own tab." : "Open in New Tab\n" + tipOut;
  };
  return { element: b, set };
}

// ================================================================== Merit Function Editor
const MFE_W = [70, 260, 46, 90, 70, 110, 80, 160];
let mfe = null;
let meritValues = { revision: -1, rows: [], value: null };
let meritBusy = false, meritPending = false;

export function showMFE() {
  if (!mfe) {
    const sheet = new Sheet({
      scope: "mfe",
      cols: App.state.mfe.columns.map((t, i) => ({ title: t, width: MFE_W[i], tip: App.state.mfe.column_tips[i],
        align: [3, 4, 5, 6].includes(i) ? "right" : i === 2 ? "center" : "left" })),
      getRows: () => mfeRows(),
      onEdit: (r, c, text) => run("mfe_set", { r, c, text }),
      onContext: (r, c, e) => popupMenu([
        { label: "Insert Row", shortcut: "Insert", action: () => mfeInsert() },
        { label: "Delete Rows", shortcut: "Shift+Del", action: () => mfeDelete() },
        { label: "Add Row", shortcut: "Ctrl+Shift+A", action: () => mfeAdd() }, null,
        { label: "Operands...", action: () => operandList() }, { label: "Help", action: () => cmd("__help:" + App.help.root) }], e.clientX, e.clientY),
    });
    const label = el("div", { class: "editor-foot" }, "Merit function: -");
    const bar = el("div", { class: "editor-bar" },
      toolbarButton("Add Row", "Add a blank row at the end.", () => mfeAdd(), "Ctrl+Shift+A"),
      toolbarButton("Insert Row", "Insert a blank row above the selected row.", () => mfeInsert(), "Insert"),
      toolbarButton("Delete Rows", "Delete the selected rows.", () => mfeDelete(), "Shift+Del"), el("span", { class: "sep" }),
      toolbarButton("Wizard...", "Write a default merit function: RMS or PTV spot, wavefront, angular or MTF, with pupil sampling, weighting and thickness boundary options.", () => meritWizard()),
      toolbarButton("Operands...", "List every operand with its description and insert one.", () => operandList()),
      toolbarButton("Clear", "Remove every row (undoable).", () => run("mfe_clear")), el("span", { class: "sep" }),
      toolbarButton("Help", "Merit Function Editor help: columns, weights, ray coordinates, every operand and a worked example (F1).", () => cmd("__help:" + App.help.root)));
    const pop = popButton(() => mfe.panel);
    bar.append(el("span", { class: "grow" }), pop.element);
    const element = el("div", { class: "pane" }, bar, sheet.element, label);
    mfe = { sheet, label, element, panel: null, pop };
    onState(() => { if (mfe.panel && mfe.panel.area.has("mfe")) mfe.sheet.render(); });
  }
  if (!docks.bottom.has("mfe")) mfe.panel = docks.bottom.add({ id: "mfe", title: "Merit Function Editor", element: mfe.element, helpId: App.help.root,
    onshow: () => mfe.sheet.render(), onpop: (on) => mfe.pop.set(on) });
  else docks.bottom.show(mfe.panel);
  mfe.sheet.render();
  showMerit();
}

function mfeRows() {
  const rows = App.state.mfe.rows;
  const vals = meritValues.revision === App.state.revision ? meritValues.rows : [];
  return rows.map((r, i) => {
    const base = r.type === "BLNK" ? "blank" : r.w < 0 ? "negw" : "";
    const dim = r.w === 0 ? " weight0" : "";
    const v = vals[i] || ["", ""];
    return { cells: [
      { t: r.type, editable: true, cls: base + dim, tip: r.tip, menu: App.operandMenu || [] },
      { t: r.params, editable: true, cls: base + dim, tip: r.tip },
      { t: r.bound, editable: true, cls: base + dim, tip: "=, > or <" },
      { t: r.target, e: r.target_e, editable: true, cls: base + dim },
      { t: r.weight, e: r.weight_e, editable: true, cls: base + dim },
      { t: v[0], cls: (base || "value") + dim }, { t: r.w > 0 ? v[1] : "", cls: (base || "value") + dim },
      { t: r.comment, editable: true, cls: base }] };
  });
}

export async function mfeAdd() { const r = await run("mfe_add"); if (r !== undefined && mfe) mfe.sheet.setCurrent(r, 0); }
export async function mfeInsert() { const r = mfe ? mfe.sheet.cur.row : 0; const n = App.state.mfe.rows.length; const x = await run("mfe_insert", { r: Math.min(r, n) }); if (x !== undefined && mfe) mfe.sheet.setCurrent(x, 0); }
export async function mfeDelete() { if (mfe) await run("mfe_delete", { rows: mfe.sheet.selectedRows() }); }

/** Merit value for the status bar and the editor's Value / % Contrib columns (background, after each change). */
export async function showMerit() {
  const s = App.state;
  if (!s.mfe.rows.length) {
    meritValues = { revision: s.revision, rows: [], value: null };
    document.getElementById("status-merit").textContent = "";
    if (mfe) mfe.label.textContent = "Merit function: -";
    return;
  }
  if (meritBusy) { meritPending = true; return; }
  meritBusy = true;
  const out = await engine.callRaw("mfe_evaluate", {}, { priority: engine.PRIORITY.background, key: "merit" });
  meritBusy = false;
  if (!out.superseded && out.result) {
    meritValues = out.result;
    const v = out.result.value;
    document.getElementById("status-merit").textContent = v === null ? "" : `MF ${(+v).toPrecision(6)}`;
    if (mfe) {
      mfe.label.textContent = v === null ? "Merit function: (error)" : `Merit function: ${(+v).toPrecision(10)}` + (out.result.error ? `    (${out.result.error})` : "");
      if (docks.bottom.has("mfe")) mfe.sheet.render();
    }
  }
  if (meritPending || (out.result && out.result.revision !== App.state.revision)) { meritPending = false; showMerit(); }
}
onState((s, old) => { if (!old || s.revision !== old.revision) showMerit(); });

const WIZ_BOUNDS = [["glass_min", "Min centre", 2], ["glass_max", "Max centre", 20], ["glass_edge", "Min edge", 1], ["glass_max_edge", "Max edge", 30],
  ["air_min", "Min centre", 0.5], ["air_max", "Max centre", 1000], ["air_edge", "Min edge", 0.5], ["air_max_edge", "Max edge", 1000]];

/** The Merit Function Wizard (lensforge.optimize.apply_default_merit), as MeritWizard in lensforge_qt/mfe.py.
 *  Opens with the options saved with the lens (merit_function.wizard); Reset restores the defaults. */
async function meritWizard() {
  const info = await run("wizard_info");
  if (!info) return;
  await dialog({ title: "Merit Function Wizard", width: 940, help: () => wizardHelp(info.help) }, (win, done, bar) => {
    const lastSurf = Math.max(1, info.n_surfaces - 3);
    const optimization = select([["rms", "RMS"], ["ptv", "PTV (peak to valley)"]], "rms");
    optimization.title = "RMS: root-mean-square error over the pupil (the usual choice).\nPTV: the largest error (spot) or max - min (wavefront).";
    const kind = select(info.criteria.map(([k, lab]) => [k, k === "mtf" ? "MTF (1 - average MTF)" : lab]), "spot");
    kind.title = "What is minimised: transverse ray error (spot), OPD (wavefront), image-space ray angle (angular, for afocal systems) or 1 - MTF.\nX / Y use only that component; X + Y uses both separately.";
    const ref = select([["centroid", "Centroid"], ["chief", "Chief ray"], ["unreferenced", "Unreferenced"]], "centroid");
    ref.title = "What the errors are measured from: the centroid of the rays (tilt removed for wavefront), the chief ray, or nothing (spot: the image-surface origin; wavefront: OPD as traced).";
    const freq = numInput(30, { min: 0.1, max: 10000, step: 1 });
    const pupil = select([["gaussian", "Gaussian quadrature"], ["rectangular", "Rectangular array"]], "gaussian");
    pupil.title = "Gaussian quadrature: few rays on rings and arms, very accurate for smooth aberrations.\nRectangular array: a grid x grid array of rays, better for vignetted or odd-shaped pupils.";
    const rings = numInput(3, { min: 1, max: 20, step: 1 }), arms = numInput(6, { min: 4, max: 36, step: 1 });
    const grid = numInput(6, { min: 2, max: 40, step: 1 });
    const obsc = numInput(0, { min: 0, max: 0.99, step: 0.05 });
    obsc.title = "Leave out rays inside this fraction of the pupil radius (central obscuration).";
    const fieldW = select([["system", "Field weights"], ["equal", "Equal"]], "system");
    fieldW.title = "Field weights: each field's row is weighted by its weight in the Fields dialog. Equal: every field gets weight 1.";
    const waveW = select([["system", "Wavelength weights"], ["equal", "Equal"]], "system");
    waveW.title = "Wavelength weights: rays count by their wavelength's weight in the Wavelengths dialog. Equal: every wavelength counts the same.";
    const weight = numInput(1, { min: 0.0001, max: 1e6, step: 0.1 });
    weight.title = "Scales the weight of every image-quality row.";
    const sym = select([["auto", "Automatic (from the lens)"], ["yes", "Yes: trace half the pupil"], ["no", "No: trace the whole pupil"]], "auto");
    sym.title = "Assume the lens is symmetric about the y-z plane, so only half the pupil is traced. Automatic checks the lens at every evaluation.";
    const vig = check("Delete vignetted rays", true, null, "Ticked: rays stopped by surface apertures are left out.\nCleared: every ray is traced ignoring apertures.");
    const lab = (t) => el("label", {}, t);
    const freqLab = lab(`MTF frequency (cycles/${info.units || "mm"})`), ringsLab = lab("Rings"), armsLab = lab("Arms"), gridLab = lab("Grid");
    const g1 = el("fieldset", {}, el("legend", {}, "Image quality"), el("div", { class: "form" },
      lab("Optimisation type"), optimization, lab("Criterion"), kind, lab("Reference"), ref, freqLab, freq));
    const prev = el("div", { class: "pupil-preview wizard-pupil" });
    const g2 = el("fieldset", {}, el("legend", {}, "Pupil integration"), el("div", { class: "row", style: { alignItems: "flex-start" } },
      el("div", { class: "form grow", style: { flex: "1 1 200px" } }, lab("Method"), pupil, ringsLab, rings, armsLab, arms, gridLab, grid, lab("Obscuration"), obsc), prev));
    const g3 = el("fieldset", {}, el("legend", {}, "Weighting and rays"), el("div", { class: "form" },
      lab("Fields"), fieldW, lab("Wavelengths"), waveW, lab("Overall weight"), weight, lab("Assume axial symmetry"), sym, el("span"), vig));
    const bounds = {};
    const bgrid = el("div", { class: "form", style: { gridTemplateColumns: "max-content 1fr max-content 1fr" } },
      el("b", {}, "Glass"), el("span"), el("b", {}, "Air"), el("span"));
    for (let k = 0; k < 4; k++) {
      for (const [name, label, val] of [WIZ_BOUNDS[k], WIZ_BOUNDS[k + 4]]) {
        const n = numInput(val, { min: 0, max: 1e5, step: 0.1 });
        n.disabled = true;
        const c = check(label, false, (on) => { n.disabled = !on; });
        bounds[name] = [c.input, n];
        bgrid.append(c, n);
      }
    }
    const bfirst = numInput(1, { min: 1, max: lastSurf, step: 1 }), blast = numInput(lastSurf, { min: 1, max: lastSurf, step: 1 });
    bfirst.disabled = blast.disabled = true;
    const bsurf = check("Only surfaces", false, (on) => { bfirst.disabled = blast.disabled = !on; });
    const bweight = numInput(1, { min: 0.0001, max: 1e6, step: 0.1 });
    const g4 = el("fieldset", {}, el("legend", {}, "Thickness boundaries"), bgrid,
      el("div", { class: "row", style: { marginTop: "6px" } }, bsurf, bfirst, el("span", {}, "to"), blast),
      el("div", { class: "form", style: { marginTop: "6px" } }, lab("Boundary weight"), bweight));
    const all = check(info.configs > 1 ? `All ${info.configs} configurations (a CONF row heads each group)` : "All configurations", true);
    all.input.disabled = info.configs <= 1;
    const startRow = numInput(info.n_rows + 1, { min: 1, max: info.n_rows + 1, step: 1 });
    startRow.disabled = true;
    const keep = check("Keep my other operands (above the default rows)", true);
    const start = check("Start at row", false, (on) => { startRow.disabled = !on; keep.input.disabled = on; },
      "Keep the rows above this one as they are and replace this row and everything below it by the default rows.");
    const g5 = el("fieldset", {}, el("legend", {}, "Rows"), el("div", { class: "form" },
      lab("Configurations"), all, el("span"), el("div", { class: "row" }, start, startRow), el("span"), keep));
    // two columns as in the Qt dialog; one column on narrow screens (app.css .wizard-cols)
    win.body.append(el("div", { class: "wizard-cols" }, el("div", {}, g1, g2, g3), el("div", {}, g4, g5)));
    const view = win.element.ownerDocument.defaultView;
    const fit = () => {   // on a small screen the body scrolls inside the window
      if (!win.element.isConnected) { view.removeEventListener("resize", fit); return; }
      keepInView(win.element);
    };
    setTimeout(fit, 0);
    view.addEventListener("resize", fit);

    const update = () => {
      const mtf = kind.value === "mtf", gq = pupil.value === "gaussian";
      for (const w of [optimization, ref, pupil, obsc, waveW, sym, vig.input]) w.disabled = mtf;
      freq.disabled = !mtf; freqLab.style.opacity = mtf ? "" : "0.5";
      rings.disabled = arms.disabled = !gq || mtf; ringsLab.style.opacity = armsLab.style.opacity = gq && !mtf ? "" : "0.5";
      grid.disabled = gq || mtf; gridLab.style.opacity = !gq && !mtf ? "" : "0.5";
    };
    let drawSeq = 0;
    const drawPupil = async () => {
      const seq = ++drawSeq;
      const p = await run("wizard_pupil", { pupil: pupil.value, rings: +rings.value || 1, arms: +arms.value || 4, grid: +grid.value || 2,
        obscuration: Math.min(0.99, Math.max(0, +obsc.value || 0)), symmetric: { auto: null, yes: true, no: false }[sym.value] }, { quiet: true });
      if (!p || seq !== drawSeq) return;
      prev.innerHTML = pupilSvg(p, pupil.value === "gaussian", +obsc.value || 0);
      prev.title = "Where the merit function's rays cross the entrance pupil, for each field and wavelength.\nDot area is proportional to the ray's weight." +
        (p.symmetric ? "\nHollow dots: the mirrored half, not traced for a symmetric lens." : "");
      prev.style.opacity = kind.value === "mtf" ? "0.4" : "";
    };
    kind.addEventListener("change", () => { update(); drawPupil(); });
    pupil.addEventListener("change", () => { update(); drawPupil(); });
    sym.addEventListener("change", drawPupil);
    for (const i of [rings, arms, grid, obsc]) i.addEventListener("input", drawPupil);

    const options = () => {
      const kw = { kind: kind.value };
      if (kw.kind === "mtf") kw.frequency = +freq.value;
      else {
        Object.assign(kw, { optimization: optimization.value, reference: ref.value, pupil: pupil.value, obscuration: +obsc.value,
          wavelength_weighting: waveW.value, symmetric: { auto: null, yes: true, no: false }[sym.value], delete_vignetted: vig.input.checked });
        if (kw.pupil === "gaussian") Object.assign(kw, { rings: +rings.value, arms: +arms.value }); else kw.grid = +grid.value;
      }
      Object.assign(kw, { field_weighting: fieldW.value, weight: +weight.value });
      for (const [name, [c, n]] of Object.entries(bounds)) if (c.checked) kw[name] = +n.value;
      if (bsurf.input.checked) kw.boundary_surfaces = [+bfirst.value, +blast.value];
      kw.boundary_weight = +bweight.value;
      if (!all.input.disabled && !all.input.checked) kw.configs = [];
      if (start.input.checked) kw.start_at = +startRow.value - 1;
      return kw;
    };
    const setOptions = (o) => {
      kind.value = o.kind ?? "spot"; optimization.value = o.optimization ?? "rms"; ref.value = o.reference ?? "centroid";
      pupil.value = o.pupil ?? "gaussian"; fieldW.value = o.field_weighting ?? "system"; waveW.value = o.wavelength_weighting ?? "system";
      sym.value = o.symmetric === true ? "yes" : o.symmetric === false ? "no" : "auto";
      rings.value = o.rings ?? 3; arms.value = o.arms ?? 6; grid.value = o.grid ?? 6; obsc.value = o.obscuration ?? 0;
      freq.value = o.frequency ?? 30; weight.value = o.weight ?? 1; vig.input.checked = o.delete_vignetted ?? true;
      for (const [name, , val] of WIZ_BOUNDS) {
        const [c, n] = bounds[name], v = o[name];
        c.checked = v !== undefined && v !== null; n.disabled = !c.checked; n.value = c.checked ? v : val;
      }
      const bs = o.boundary_surfaces;
      bsurf.input.checked = !!bs; bfirst.disabled = blast.disabled = !bs;
      bfirst.value = bs ? bs[0] : 1; blast.value = bs ? bs[1] : lastSurf;
      bweight.value = o.boundary_weight ?? 1;
      if (!all.input.disabled) all.input.checked = !(Array.isArray(o.configs) && o.configs.length === 0);
      const st = o.start_at;
      start.input.checked = st !== undefined && st !== null; startRow.disabled = !start.input.checked;
      startRow.value = start.input.checked ? st + 1 : info.n_rows + 1;
      keep.input.checked = o.keep ?? true; keep.input.disabled = start.input.checked;
      update();
      drawPupil();
    };
    setOptions(info.wizard || {});
    bar.append(btn("Help", () => wizardHelp(info.help), { title: "Help on every wizard option (F1)." }),
      btn("Reset", () => setOptions({}), { title: "Put every option back to its default." }), el("span", { class: "grow" }),
      btn("Cancel", () => done(null)), btn("OK", async () => {
        await run("mfe_wizard", { kw: options(), keep: keep.input.checked });
        done(true);
      }, { primary: true }));
    win.element.addEventListener("keydown", (e) => { if (e.key === "F1") { e.preventDefault(); e.stopPropagation(); wizardHelp(info.help); } });
  });
}

/** SVG of the wizard's pupil sampling (MeritPupilPreview in lensforge_qt/mfe.py): the pupil, the obscuration,
 *  Gaussian-quadrature rings, and each ray with an area proportional to its weight (hollow: the mirrored half). */
function pupilSvg(p, gq, obsc) {
  const R = 80, cx = 90, cy = 85, n = p.x.length;
  const base = Math.max(1.6, Math.min(5, 0.9 * R / Math.sqrt(Math.max(n, 1))));
  const wmax = Math.max(...p.w, 1e-300);
  let s = `<svg viewBox="0 0 180 212" width="180" height="212"><defs><pattern id="wiz-hatch" width="5" height="5" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
    `<line x1="0" y1="0" x2="0" y2="5" stroke="#999"/></pattern></defs><circle cx="${cx}" cy="${cy}" r="${R}" fill="#fff" stroke="#999"/>`;
  if (obsc > 0) s += `<circle cx="${cx}" cy="${cy}" r="${(obsc * R).toFixed(1)}" fill="url(#wiz-hatch)" stroke="#999"/>`;
  s += `<path d="M${cx - R} ${cy}h${2 * R}M${cx} ${cy - R}v${2 * R}" stroke="#bbb" stroke-dasharray="2 2" fill="none"/>`;
  if (gq) for (const r of new Set(p.x.map((x, i) => Math.hypot(x, p.y[i]).toFixed(5))))
    s += `<circle cx="${cx}" cy="${cy}" r="${(r * R).toFixed(1)}" fill="none" stroke="#bbb" stroke-dasharray="2 2"/>`;
  p.x.forEach((x, i) => {
    const d = (base * Math.sqrt(p.w[i] / wmax)).toFixed(2), X = cx + x * R, Y = (cy - p.y[i] * R).toFixed(1);
    s += `<circle cx="${X.toFixed(1)}" cy="${Y}" r="${d}" fill="#1f5f99"/>`;
    if (p.symmetric && Math.abs(x) > 1e-9) s += `<circle cx="${(cx - x * R).toFixed(1)}" cy="${Y}" r="${d}" fill="none" stroke="#1f5f99"/>`;
  });
  const [l1, l2] = p.error ? [p.error, ""] : [`${n} rays per field`, "and wavelength" + (p.symmetric ? " (half pupil)" : "")];
  s += `<text x="${cx}" y="186" text-anchor="middle" font-size="12" fill="currentColor">${esc(l1)}</text>` +
    `<text x="${cx}" y="202" text-anchor="middle" font-size="12" fill="currentColor">${esc(l2)}</text>`;
  return s + "</svg>";
}

/** The wizard's help page, on top of the (modal) wizard; also in Help > Merit Function Editor. */
function wizardHelp(key) {
  const page = (App.help.topics || []).find((t) => t.key === key);
  message("Merit Function Wizard Help", `<div style="max-height:65vh;overflow:auto">${page ? page.html : "Help page not found."}</div>`, { width: 720 });
}

async function operandList() {
  const ops = await run("operands");
  if (!ops) return;
  const t = await dialog({ title: "Optimisation Operands", width: 680, height: 540, resizable: true }, (win, done, bar) => {
    const filter = el("input", { type: "text", placeholder: "Filter (name or description)" });
    const list = el("div", { class: "list mono" });
    let sel = null;
    const fill = () => {
      const f = filter.value.toLowerCase();
      list.replaceChildren(...ops.filter(([k, d]) => !f || (k + " " + d).toLowerCase().includes(f)).map(([k, d]) => {
        const row = el("div", { class: k === sel ? "sel" : "", title: d }, `${k.padEnd(6)} ${d}`);
        row.addEventListener("click", () => { sel = k; fill(); });
        row.addEventListener("dblclick", () => done(k));
        return row;
      }));
    };
    filter.addEventListener("input", fill);
    win.body.append(filter, list);
    bar.append(btn("Cancel", () => done(null)), btn("Insert", () => sel && done(sel), { primary: true }));
    fill();
  });
  if (t) {
    const r = mfe ? Math.min(mfe.sheet.cur.row, App.state.mfe.rows.length) : 0;
    const x = await run("mfe_insert_operand", { r, t });
    if (x !== undefined && mfe) mfe.sheet.setCurrent(x, 1);
  }
}

// ================================================================== Multi-Configuration Editor
let mce = null;
export function showMCE() {
  if (!mce) {
    const sheet = new Sheet({
      scope: "mce",
      cols: [], getRows: () => mceRows(),
      onEdit: (i, c, text) => run("mce_set", { i, c, text }),
      onContext: (r, c, e) => {
        const k = c >= 3 ? c - 2 : null;
        if (r < 0 && k) {   // header
          return popupMenu([{ label: `Make Config ${k} Current`, action: () => run("switch_config", { k }) },
            { label: "Rename...", action: () => mceRename(k) }, { label: "Insert Config After", action: () => run("mce_add_config", { k }) },
            { label: "Delete Config", action: () => run("mce_delete_config", { k }) }], e.clientX, e.clientY);
        }
        popupMenu([{ label: "Insert Operand", shortcut: "Insert", action: () => mceInsert() },
          { label: "Delete Operands", shortcut: "Shift+Del", action: () => mceDelete() },
          { label: "Toggle Variable", shortcut: "Ctrl+Shift+V", action: () => mceToggleVar() },
          { label: "Make Current", action: () => mceMakeCurrent() }], e.clientX, e.clientY);
      },
    });
    sheet.element.addEventListener("dblclick", (e) => {
      const th = e.target.closest("th[data-c]");
      if (th && +th.dataset.c >= 3) run("switch_config", { k: +th.dataset.c - 2 });
    });
    const label = el("div", { class: "editor-foot plain" });
    const bar = el("div", { class: "editor-bar" },
      toolbarButton("Insert Operand", "Insert a THIC row above the selected row (all configurations take the lens's current value; change the type, Ref and values afterwards).", () => mceInsert(), "Insert"),
      toolbarButton("Delete Operands", "Delete the selected rows; the lens keeps its current values.", () => mceDelete(), "Shift+Del"), el("span", { class: "sep" }),
      toolbarButton("Add Config", "Add a configuration after the selected one, copying its values.", () => run("mce_add_config", { k: mceConfig() })),
      toolbarButton("Delete Config", "Delete the selected configuration.", () => run("mce_delete_config", { k: mceConfig() })),
      toolbarButton("Rename Config...", "Name the selected configuration (e.g. short, mid, long).", () => mceRename(mceConfig())), el("span", { class: "sep" }),
      toolbarButton("Make Current", "Show the selected configuration in the Lens Data Editor and the analyses (or double-click its header).", () => mceMakeCurrent()),
      toolbarButton("Toggle Variable", "Make the selected cells optimisation variables, or fixed again.", () => mceToggleVar(), "Ctrl+Shift+V"), el("span", { class: "sep" }),
      toolbarButton("Help", "How multi-configuration works: operands, switching, analyses and optimisation.", () => cmd("__help:Tools > Multi-Configuration Editor")));
    const pop = popButton(() => mce.panel);
    bar.append(el("span", { class: "grow" }), pop.element);
    const element = el("div", { class: "pane" }, bar, sheet.element, label);
    mce = { sheet, label, element, panel: null, pop };
    onState(() => { if (docks.bottom.has("mce")) renderMCE(); });
  }
  if (!docks.bottom.has("mce")) mce.panel = docks.bottom.add({ id: "mce", title: "Multi-Configuration Editor", element: mce.element, helpId: "Tools > Multi-Configuration Editor",
    onshow: () => renderMCE(), onpop: (on) => mce.pop.set(on) });
  else docks.bottom.show(mce.panel);
  renderMCE();
}

function renderMCE() {
  const m = App.state.mce;
  const cols = [{ title: "Type", width: 70, tip: "Operand: what the row sets (see Help)" },
    { title: "Ref", width: 50, tip: "Surface, field or wavelength the operand refers to" },
    { title: "Param", width: 80, tip: "Parameter name, for PARM rows only" }];
  for (let k = 1; k <= m.n; k++) {
    const name = m.names[k - 1];
    cols.push({ title: `${k === m.current ? "* " : ""}Config ${k}${name ? ": " + name : ""}`, width: 110, align: "right",
      tip: `${m.labels[k - 1]}${k === m.current ? " (current)" : ""}. Double-click to make it current; right-click to rename, insert or delete configurations.` });
  }
  mce.sheet.cols = cols;
  mce.label.textContent = m.label;
  mce.label.classList.toggle("error-text", m.bad > 0);
  mce.sheet.render();
}

function mceRows() {
  const m = App.state.mce;
  return m.rows.map((r) => ({ cells: [
    { t: r.type, editable: true, cls: r.error ? "mcerr" : "", tip: r.tip + (r.error ? "\n⚠ " + r.error : ""), menu: m.operand_menu },
    { t: r.ref, editable: r.has_ref, cls: r.has_ref ? "" : "na", tip: r.ref_tip },
    { t: r.param, editable: r.has_param, cls: r.has_param ? "" : "na", tip: r.tip },
    ...r.cells.map((c, k) => ({ t: c.t + (c.var ? "  V" : ""), e: c.t, editable: !r.fixed, cls: c.var ? "mcvar" : (k + 1 === m.current ? "current-config" : ""),
      tip: r.tip + `\n${m.labels[k]}${k + 1 === m.current ? " (current)" : ""}` + (c.var ? "\nVariable (Ctrl+Shift+V toggles)" : "") })),
  ] }));
}

function mceConfig() {
  const m = App.state.mce;
  const c = mce ? mce.sheet.cur.col : 0;
  return c >= 3 ? c - 2 : (m.current || 1);
}
async function mceInsert() { const r = mce ? Math.min(mce.sheet.cur.row, App.state.mce.rows.length) : 0; const x = await run("mce_insert", { r }); if (x !== undefined && mce) mce.sheet.setCurrent(x, 0); }
async function mceDelete() { if (mce) await run("mce_delete", { rows: mce.sheet.selectedRows() }); }
async function mceMakeCurrent() { await run("switch_config", { k: mceConfig() }); }
async function mceToggleVar() {
  const cells = mce.sheet.selectedCells().filter(([, c]) => c >= 3).map(([r, c]) => [r, c - 2]);
  if (!cells.length) { status("Select value cells (configuration columns) to make them variable"); return; }
  await run("mce_toggle_variable", { cells });
}
async function mceRename(k) {
  const m = App.state.mce;
  if (!m.n) return;
  const name = await prompt("Rename configuration", `Name of configuration ${k}:`, m.names[k - 1] || "");
  if (name !== null) await run("mce_rename_config", { k, name });
}

// ================================================================== Python Shell
let shell = null;
export async function showShell() {
  if (!shell) {
    const editor = el("textarea", { class: "mono", spellcheck: false, style: { flex: "1", minHeight: "60px", border: "none", borderBottom: "1px solid var(--border)", resize: "none", padding: "6px" } });
    editor.value = await call("script_example");
    const output = el("pre", { class: "mono", style: { flex: "1", minHeight: "40px", padding: "6px", background: "#fbfbfd" } });
    const runIt = async () => {
      status("Running script...", 0);
      const out = await run("run_script", { code: editor.value });
      status("");
      if (out !== undefined) { output.textContent += (output.textContent ? "\n" : "") + out; output.scrollTop = output.scrollHeight; }
    };
    editor.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); runIt(); }
      if (e.key === "Tab" && !e.shiftKey && !e.ctrlKey) {
        e.preventDefault();
        const s = editor.selectionStart;
        editor.setRangeText("    ", s, editor.selectionEnd, "end");
      }
    });
    editor.addEventListener("focusin", () => { App.focusScope = "shell"; });
    const pop = popButton(() => shell.panel);
    const element = el("div", { class: "pane" }, editor, output,
      el("div", { class: "editor-bar" }, el("span", { class: "muted", title: "Names defined for the script" }, "lens, lf, opt, np"), el("span", { class: "grow" }), pop.element,
        el("button", { type: "button", onclick: () => { output.textContent = ""; } }, "Clear Output"),
        el("button", { type: "button", onclick: runIt, title: "Run the script against the open lens (Ctrl+Enter)" }, "Run (Ctrl+Enter)")));
    shell = { element, editor, output, run: runIt, panel: null, pop };
  }
  if (!docks.bottom.has("script")) shell.panel = docks.bottom.add({ id: "script", title: "Python Shell", element: shell.element, helpId: "Tools > Python Shell",
    onpop: (on) => shell.pop.set(on) });
  else docks.bottom.show(shell.panel);
  shell.editor.focus();
}

// ================================================================== Undo History
let undoPanel = null;
export function showUndoHistory() {
  if (!undoPanel) {
    const list = el("div", { class: "undo-list" });
    const render = () => {
      const s = App.state;
      const items = ["<original lens>", ...s.history];
      list.replaceChildren(...items.map((t, i) => {
        const d = el("div", { class: i === s.history_index ? "current" : i > s.history_index ? "future" : "", title: t }, t);
        d.addEventListener("click", () => run("undo_to", { index: i }));
        return d;
      }));
      list.querySelector(".current")?.scrollIntoView({ block: "nearest" });
    };
    undoPanel = { element: el("div", { class: "pane" }, list), render };
    onState(() => { if (docks.left.has("undo")) render(); });
  }
  if (!docks.left.has("undo")) docks.left.add({ id: "undo", title: "Undo History", element: undoPanel.element, helpId: "Edit > Undo History" });
  else docks.left.show(docks.left.has("undo"));
  undoPanel.render();
}

/** Local shortcuts of the focused editor (Qt: WidgetWithChildrenShortcut actions). Returns true if handled. */
export function localShortcut(scope, key) {
  if (scope === "mfe") {
    if (key === "Ins") { mfeInsert(); return true; }
    if (key === "Shift+Del") { mfeDelete(); return true; }
    if (key === "Ctrl+Shift+A") { mfeAdd(); return true; }
  }
  if (scope === "mce") {
    if (key === "Ins") { mceInsert(); return true; }
    if (key === "Shift+Del") { mceDelete(); return true; }
    if (key === "Ctrl+Shift+V") { mceToggleVar(); return true; }
  }
  return false;
}
