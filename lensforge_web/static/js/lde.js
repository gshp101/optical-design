// Lens Data Editor: the surface spreadsheet (as lensforge_qt/lde.py).
// One row per surface; cells carry markers: V variable, a letter for a solve (M, C, F, P ...), U a fixed
// semi-diameter. Right-click a cell for variables, solves, surface type, stop and surface properties.
import { App, run, status, statusError, onState, cmd } from "./core.js";
import { el, popupMenu, closePopups } from "./ui.js";
import * as D from "./dialogs.js";

const WIDTHS = [44, 110, 90, 100, 100, 120, 92, 92];
const PAR_W = 92;
let root = null;
let cur = { row: 1, col: 3 };
let anchor = null;          // shift-click range start (row)
let rangeRows = null;       // [first, last] when several rows are selected
let editing = null;         // {td, input, row, col, key, original}

export function init() {
  root = document.getElementById("lde");
  root.addEventListener("keydown", onKey);
  root.addEventListener("focusin", () => { App.focusScope = "lde"; });
  root.addEventListener("contextmenu", onContext);
  root.addEventListener("pointerdown", onPointer);
  root.addEventListener("dblclick", (e) => {
    const td = e.target.closest("td[data-col]");
    if (td && !editing) startEdit(+td.dataset.row, +td.dataset.col);
  });
  onState((s, old) => {
    if (editing && old && s.revision !== old.revision) cancelEdit();
    render();
  });
}

const rows = () => (App.state ? App.state.lde.rows : []);
const nCols = () => 2 + 6 + (App.state ? App.state.lde.n_par : 8);

function cellInfo(row, col) {
  const r = rows()[row];
  if (!r) return null;
  if (col === 0) return { k: "surf", t: r.label, na: false, ro: true };
  if (col === 1) return { k: "type", t: r.type, e: r.kind };
  return r.cells[col - 2];
}

export function current() {
  const c = cellInfo(cur.row, cur.col);
  return { row: cur.row, col: cur.col, key: c ? c.k : null };
}

export function selectedRows() {
  if (rangeRows) return rangeRows.slice();
  return [cur.row, cur.row];
}

export function select(row, col = cur.col) {
  const n = rows().length;
  cur = { row: Math.max(0, Math.min(row, n - 1)), col: Math.max(0, Math.min(col, nCols() - 1)) };
  rangeRows = null;
  anchor = cur.row;
  render();
  scrollIntoView();
}

function scrollIntoView() {
  const td = root.querySelector(`td[data-row="${cur.row}"][data-col="${cur.col}"]`);
  if (td) td.scrollIntoView({ block: "nearest", inline: "nearest" });
}

export function render() {
  if (!root || !App.state) return;
  const st = App.state.lde;
  const n = st.rows.length;
  if (cur.row >= n) cur.row = n - 1;
  const fixed = st.fixed;
  const pars = (st.rows[cur.row] || {}).pars || [];
  const head = el("tr", {}, ...fixed.map((lab, i) => el("th", { style: { width: WIDTHS[i] + "px" } }, lab)),
    ...Array.from({ length: st.n_par }, (_, k) => el("th", { style: { width: PAR_W + "px" }, title: pars[k] || `Par ${k + 1}` }, pars[k] || `Par ${k + 1}`)));
  const body = el("tbody");
  st.rows.forEach((r, i) => {
    const inRange = rangeRows && i >= rangeRows[0] && i <= rangeRows[1];
    const tr = el("tr", { class: inRange ? "selrow" : "" });
    tr.append(el("td", { class: "rowhead" + (r.stop ? " stop" : "") + (cur.row === i && cur.col === 0 ? " cur" : ""), "data-row": i, "data-col": 0 }, r.label));
    tr.append(el("td", { class: cur.row === i && cur.col === 1 ? "cur" : "", "data-row": i, "data-col": 1, title: `Surface ${i}: ${r.type}` }, r.type));
    r.cells.forEach((c, k) => {
      const col = k + 2;
      const cls = [];
      if (c.na) cls.push("na");
      else {
        if (c.k !== "comment" && c.k !== "material") cls.push("num");
        if (c.missing) cls.push("missing");
        else if (c.solve) cls.push("solve");
        else if (c.var) cls.push("var");
        if (c.auto) cls.push("auto");
        if (c.m) cls.push("has-mk");
      }
      if (cur.row === i && cur.col === col) cls.push("cur");
      const td = el("td", { class: cls.join(" "), "data-row": i, "data-col": col, title: c.tip || "" }, c.t);
      if (c.m) td.append(el("span", { class: "mk" + (c.m === "U" ? " u" : "") }, c.m));
      tr.append(td);
    });
    body.append(tr);
  });
  const table = el("table", { class: "sheet" }, el("thead", {}, head), body);
  const scroll = [root.scrollLeft, root.scrollTop];
  root.replaceChildren(table);
  root.scrollLeft = scroll[0];
  root.scrollTop = scroll[1];
}

// ------------------------------------------------------------------ selection and keys
function onPointer(e) {
  const td = e.target.closest("td[data-col]");
  if (!td || editing && editing.td.contains(e.target)) return;
  if (editing) commitEdit();
  const row = +td.dataset.row, col = +td.dataset.col;
  if (e.shiftKey && anchor !== null) {
    rangeRows = [Math.min(anchor, row), Math.max(anchor, row)];
    if (rangeRows[0] === rangeRows[1]) rangeRows = null;
    cur = { row, col };
  } else {
    if (e.button === 2 && rangeRows && row >= rangeRows[0] && row <= rangeRows[1]) { cur = { row, col }; render(); return; }
    cur = { row, col };
    anchor = row;
    rangeRows = null;
  }
  render();
  root.focus({ preventScroll: true });
}

function move(dr, dc, extend = false) {
  const n = rows().length;
  const row = Math.max(0, Math.min(cur.row + dr, n - 1));
  const col = Math.max(0, Math.min(cur.col + dc, nCols() - 1));
  if (extend) {
    if (anchor === null) anchor = cur.row;
    rangeRows = [Math.min(anchor, row), Math.max(anchor, row)];
    if (rangeRows[0] === rangeRows[1]) rangeRows = null;
  } else { rangeRows = null; anchor = row; }
  cur = { row, col };
  render();
  scrollIntoView();
}

function onKey(e) {
  if (editing) return;  // the editor handles its keys
  const k = e.key;
  const plainKey = !e.ctrlKey && !e.metaKey && !e.altKey;
  const moves = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1], PageUp: [-10, 0], PageDown: [10, 0] };
  if (moves[k] && !e.ctrlKey && !e.metaKey) { e.preventDefault(); move(...moves[k], e.shiftKey && (k === "ArrowUp" || k === "ArrowDown")); return; }
  if (k === "Home" && plainKey) { e.preventDefault(); move(0, -cur.col); return; }
  if (k === "End" && plainKey) { e.preventDefault(); move(0, nCols() - 1 - cur.col); return; }
  if (k === "Tab" && !e.ctrlKey) { e.preventDefault(); move(0, e.shiftKey ? -1 : 1); return; }
  if ((k === "Enter" || k === "F2") && plainKey) { e.preventDefault(); startEdit(cur.row, cur.col); return; }
  if (k.length === 1 && plainKey && !e.isComposing) { e.preventDefault(); startEdit(cur.row, cur.col, k); return; }
  if ((k === "Delete" || k === "Backspace") && plainKey) {
    const c = cellInfo(cur.row, cur.col);
    if (c && !c.na && !c.ro && cur.col >= 2 && (c.k === "comment" || c.k === "semi_diameter")) {
      e.preventDefault();
      commit(cur.row, c.k, "", c.e);
    }
  }
}

// ------------------------------------------------------------------ editing
function editable(row, col) {
  const c = cellInfo(row, col);
  if (!c || col === 0) return false;
  if (col === 1) return true;
  return !c.na && !c.ro;
}

export function startEdit(row, col, initial) {
  if (!editable(row, col)) {
    const c = cellInfo(row, col);
    if (c && c.ro && col > 1) status("This cell is set by a solve: right-click > Solve > Remove Solve to type a value");
    return;
  }
  cur = { row, col };
  render();
  const td = root.querySelector(`td[data-row="${row}"][data-col="${col}"]`);
  const c = cellInfo(row, col);
  td.classList.add("editing");
  td.replaceChildren();
  if (col === 1) {
    const s = el("select", {}, ...App.state.lde.types.map(([k, lab]) => el("option", { value: k }, lab)));
    s.value = c.e;
    td.append(s);
    editing = { td, input: s, row, col, key: "type", original: c.e };
    s.addEventListener("change", () => commitEdit());
    s.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancelEdit(); }
      if (e.key === "Enter") { e.preventDefault(); commitEdit(); }
    });
    s.addEventListener("blur", () => setTimeout(() => editing && editing.input === s && commitEdit(), 0));
    s.focus();
    return;
  }
  const input = el("input", { type: "text", value: initial !== undefined ? initial : (c.e ?? c.t), spellcheck: false, autocomplete: "off" });
  if (c.k === "material") {
    const more = el("button", { type: "button", title: "Choose a material from the catalog (Ctrl+G)",
      onpointerdown: (e) => e.preventDefault(), onclick: () => { const r = row; cancelEdit(); chooseMaterial(r); } }, "...");
    td.append(el("div", { class: "mat-editor" }, input, more));
    input.title = "Type any part of a glass name (bk7 offers N-BK7), CATALOG:NAME, 'nd,vd', an index or MIRROR";
    attachCompletion(input);
  } else td.append(input);
  editing = { td, input, row, col, key: c.k, original: c.e ?? c.t };
  input.addEventListener("keydown", (e) => {
    if (input._completion && input._completion.key(e)) return;
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); cancelEdit(); root.focus(); }
    else if (e.key === "Enter") { e.preventDefault(); commitEdit(); move(1, 0); root.focus(); }
    else if (e.key === "Tab") { e.preventDefault(); commitEdit(); move(0, e.shiftKey ? -1 : 1); root.focus(); }
    else if ((e.key === "ArrowUp" || e.key === "ArrowDown") && !input._completion?.open()) {
      e.preventDefault(); commitEdit(); move(e.key === "ArrowUp" ? -1 : 1, 0); root.focus();
    }
  });
  input.addEventListener("blur", () => setTimeout(() => { if (editing && editing.input === input && document.activeElement !== input) commitEdit(); }, 120));
  input.focus();
  if (initial === undefined) input.select();
  else input.setSelectionRange(input.value.length, input.value.length);
}

function cancelEdit() {
  if (!editing) return;
  if (editing.input._completion) editing.input._completion.close();
  editing = null;
  render();
}

function commitEdit() {
  if (!editing) return;
  const e = editing;
  if (e.input._completion) e.input._completion.close();
  editing = null;
  const value = e.input.value;
  render();
  if (String(value) === String(e.original)) return;
  if (e.key === "type") run("set_type", { row: e.row, kind: value });
  else commit(e.row, e.key, value, e.original);
}

function commit(row, key, text) {
  return run("set_cell", { row, key, text });
}

// material name completion (substring match, as the Qt editor's QCompleter)
function attachCompletion(input) {
  let pop = null, items = [], active = -1, timer = null, token = 0;
  const close = () => { if (pop) pop.remove(); pop = null; items = []; active = -1; };
  const show = () => {
    close();
    if (!items.length) return;
    const r = input.getBoundingClientRect();
    pop = el("div", { class: "complete-pop", style: { left: r.left + "px", top: r.bottom + "px", minWidth: r.width + "px" } });
    items.slice(0, 200).forEach((t, i) => pop.append(el("div", { class: i === active ? "active" : "",
      onpointerdown: (e) => { e.preventDefault(); input.value = t; close(); commitEdit(); root.focus(); } }, t)));
    document.body.append(pop);
  };
  input.addEventListener("input", () => {
    clearTimeout(timer);
    const my = ++token;
    timer = setTimeout(async () => {
      const hits = await run("material_search", { text: input.value }, { quiet: true });
      if (my !== token || !editing || editing.input !== input) return;
      items = hits || [];
      active = -1;
      show();
    }, 100);
  });
  input._completion = {
    open: () => !!pop,
    close,
    key(e) {
      if (!pop) return false;
      if (e.key === "ArrowDown" || e.key === "ArrowUp") {
        e.preventDefault();
        active = Math.max(0, Math.min(items.length - 1, active + (e.key === "ArrowDown" ? 1 : -1)));
        [...pop.children].forEach((d, i) => d.classList.toggle("active", i === active));
        pop.children[active]?.scrollIntoView({ block: "nearest" });
        return true;
      }
      if (e.key === "Enter" && active >= 0) { e.preventDefault(); input.value = items[active]; close(); commitEdit(); move(1, 0); root.focus(); return true; }
      if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); return true; }
      return false;
    },
  };
}

// ------------------------------------------------------------------ context menu
async function onContext(e) {
  const td = e.target.closest("td[data-col]");
  if (!td) return;
  e.preventDefault();
  if (editing) commitEdit();
  const row = +td.dataset.row, col = +td.dataset.col;
  const items = await run("context_menu", { row, col });
  if (!items) return;
  const conv = (list) => list.map((it) => {
    if (!it) return null;
    if (it.items) return { label: it.label, items: conv(it.items) };
    const c = it.id ? App.menus.commands[it.id] : null;
    return { label: it.label, checked: it.checked, icon: c ? c.icon : null, shortcut: c ? c.shortcut : null, cmd: it.id,
      title: c ? c.summary : "", action: () => (it.id ? cmd(it.id) : contextAction(it.cmd, it.args)) };
  });
  popupMenu(conv(items), e.clientX, e.clientY);
}

function contextAction(name, args) {
  const [row, key, extra] = args;
  if (name === "toggle_variable") return run("toggle_variable", { row, key });
  if (name === "solve_dialog") return D.solveDialog(row, key, extra);
  if (name === "remove_solve") return run("remove_solve", { row, key });
  if (name === "set_cell") return run("set_cell", { row, key, text: extra });
  if (name === "material_dialog") return chooseMaterial(row);
  if (name === "set_type") return run("set_type", { row, kind: key });
  if (name === "make_stop") return run("make_stop", { row });
  if (name === "surface_properties") return surfaceProperties(row);
}

// ------------------------------------------------------------------ Edit menu actions
export async function insertBefore() {
  const r = await run("insert_surface", { row: cur.row, after: false });
  if (r !== undefined) select(r);
}
export async function insertAfter() {
  const r = await run("insert_surface", { row: cur.row, after: true });
  if (r !== undefined) select(r);
}
export async function deleteSurface() {
  let [first, last] = selectedRows();
  const ima = App.state.image_index;
  if (first !== last) {
    first = Math.max(first, 1);
    last = Math.min(last, ima - 1);
    if (first < last) return deleteRange(first, last);
  }
  const r = await run("delete_surface", { row: first });
  if (r !== undefined) select(first);
}
export async function deleteRange(first, last) {
  const d = await run("describe_deletion", { first, last });
  if (!d) return false;
  if (d.error) { statusError(`Delete Surfaces: ${d.error}`); return false; }
  if (!(await D.confirmDelete(first, last, d.lines))) return false;
  const ok = await run("delete_range", { first, last });
  if (ok) {
    select(first);
    const n = last - first + 1;
    status(`Deleted ${n} surface${n > 1 ? "s" : ""}`);
  }
  return !!ok;
}
export async function deleteSurfacesDialog() {
  const [first, last] = selectedRows();
  const range = await D.deleteSurfacesDialog(first, last);
  if (range) return deleteRange(range[0], range[1]);
}
export async function toggleVariable() {
  const { row, key } = current();
  return run("toggle_variable", { row, key });
}
export async function chooseMaterial(row) {
  if (row === undefined) row = cur.row;
  const spec = await D.materialDialog(row);
  if (spec !== null && spec !== undefined) return run("set_cell", { row, key: "material", text: spec });
}
export async function surfaceProperties(row) {
  if (row === undefined) row = cur.row;
  return D.surfacePropertiesDialog(row);
}
