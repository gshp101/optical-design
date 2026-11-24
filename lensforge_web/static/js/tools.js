// Tools: optimisation, tolerancing, the non-sequential editor, the help browser and Customize Toolbar
// (as lensforge_qt/opt_dialogs.py, ns_window.py, help_browser.py and toolbar_dialog.py).
import { App, run, call, status, statusError, onState, cmd, keyLabel } from "./core.js";
import * as engine from "./engine.js";
import * as store from "./storage.js";
import { el, esc, btn, select, numInput, check, openWindow, dialog, message, confirmBox, download, pickFile, iconImg, svgURL, copyText } from "./ui.js";
import { openAnalysis } from "./analysis.js";

const dpr = () => Math.min(2, window.devicePixelRatio || 1);
const fmt = (v, p = 10) => (v === null || v === undefined ? "-" : (+v).toPrecision(p));
let progressHandler = null;
engine.on("progress", (p) => progressHandler && progressHandler(p));

function stopButton(onstop) {
  const b = btn("Stop", () => {
    if (!engine.requestStop()) {
      message("Stop", "This page is not cross-origin isolated, so Stop cannot reach the running computation. It will finish by " +
        "itself (set fewer cycles, trials or a time limit to keep runs short). Opening LensForge from <code>python -m lensforge_web</code> " +
        "or a host that serves the page's service worker makes Stop work.");
      return;
    }
    onstop && onstop();
  });
  b.disabled = true;
  if (!engine.canStop()) b.title = "Stop needs a cross-origin isolated page (see Help)";
  return b;
}

// ================================================================== Optimization
let optWin = null;
export async function optimization() {
  if (optWin && !optWin.closed) { optWin.raise(); return; }
  const info = await run("opt_info");
  if (!info) return;
  const buttons = el("div", { class: "win-buttons" });
  const w = optWin = openWindow({ title: "Optimization", popout: "optimization", width: 660, height: 600, resizable: true, buttons, help: () => cmd("__help:Tools > Optimization") });
  const algorithm = select(info.algorithms, "dls");
  const cycles = numInput(50, { min: 1, max: 10000, step: 1 });
  cycles.title = "Most cycles of the local optimiser (damped least squares or orthogonal descent); Hammer and global search use up to 20 / 30 per local run";
  const trials = numInput(50, { min: 1, max: 100000, step: 1 });
  const timeLimit = numInput(0, { min: 0, max: 1e6, step: 1 });
  timeLimit.title = "Seconds (0 = none)";
  const nearest = numInput(5, { min: 1, max: 200, step: 1 });
  nearest.title = "Glass substitution tries this many catalog glasses nearest each current glass";
  const catalog = select([["", "All catalogs"], ...info.catalogs.map((c) => [c, c])], "");
  catalog.title = "Catalog that glass substitution takes candidate glasses from (and that model glasses are snapped to)";
  const autoApply = check("Load the result into the lens when finished", true);
  const form = el("div", { class: "form" }, el("label", {}, "Algorithm"), algorithm, el("label", {}, "Cycles"), cycles,
    el("label", {}, "Trials / starts"), trials, el("label", {}, "Time limit (s, 0 = none)"), timeLimit,
    el("label", {}, "Glass candidates (nearest)"), nearest, el("label", {}, "Glass catalog"), catalog, el("span"), autoApply);
  const infoText = el("div", { style: { whiteSpace: "pre-wrap" } });
  const meritLabel = el("div", { style: { fontWeight: "bold", fontSize: "15px" } });
  const plot = el("img", { style: { width: "100%", height: "150px", objectFit: "contain", border: "1px solid var(--border-soft)" }, alt: "" });
  const log = el("pre", { class: "mono", style: { flex: "1", minHeight: "80px", border: "1px solid var(--border)", padding: "4px" } });
  w.body.append(form, infoText, meritLabel, plot, log);
  const startB = btn("Start", () => start(), { primary: true });
  const stopB = stopButton(() => { log.textContent += "Stopping...\n"; });
  const applyB = btn("Load Result", () => apply(), { disabled: true });
  buttons.append(el("div", { class: "left" }, startB, stopB, applyB), btn("Close", () => w.close()));
  let running = false, history = [];
  const enable = () => {
    const a = algorithm.value;
    trials.disabled = timeLimit.disabled = !["hammer", "global"].includes(a);
    nearest.disabled = catalog.disabled = a !== "glass";
  };
  algorithm.addEventListener("change", enable);
  enable();
  const refresh = async () => {
    if (running || w.closed) return;
    const i = await run("opt_info", {}, { quiet: true, priority: engine.PRIORITY.background });
    if (!i || running) return;
    infoText.textContent = i.info;
    meritLabel.textContent = i.n_rows ? `Current merit function: ${fmt(i.merit)}` : "No merit function (Tools > Merit Function Editor)";
  };
  onState((s, old) => { if (!w.closed && (!old || s.revision !== old.revision)) refresh(); });
  refresh();
  const drawHistory = async () => {
    const png = await run("history_plot", { values: history, width: plot.clientWidth || 600, height: 150, dpr: dpr() }, { quiet: true });
    if (png) plot.src = "data:image/png;base64," + png;
  };
  const start = async () => {
    const i = await run("opt_info");
    if (!i) return;
    if (!i.n_vars && algorithm.value !== "glass") { await message("Optimization", "There are no variables. Right-click a radius, thickness, conic or material cell in the Lens Data Editor and choose Make Variable."); return; }
    if (!i.n_rows) { await message("Optimization", "The merit function is empty. Use the Merit Function Editor (its Wizard builds a default merit function)."); return; }
    running = true;
    history = [];
    startB.disabled = true; stopB.disabled = false; applyB.disabled = true;
    log.textContent += `--- ${algorithm.selectedOptions[0].textContent} started\n`;
    const t0 = performance.now();
    let lastPlot = 0;
    progressHandler = (p) => {
      if (p.kind !== "optimize") return;
      history.push(p.best);
      meritLabel.textContent = `Best merit: ${fmt(p.best)}   (${p.evaluations} evaluations, ${p.seconds} s)`;
      if (performance.now() - lastPlot > 1000) { lastPlot = performance.now(); }
    };
    const out = await engine.callRaw("optimize", { algorithm: algorithm.value, cycles: +cycles.value, trials: +trials.value,
      time_limit: +timeLimit.value, nearest: +nearest.value, catalog: catalog.value || null });
    progressHandler = null;
    running = false;
    startB.disabled = false; stopB.disabled = true;
    if (out.error) { log.textContent += `Failed: ${out.error}\n`; refresh(); return; }
    const r = out.result;
    log.textContent += r.message + "\n";
    log.scrollTop = log.scrollHeight;
    history = r.history;
    drawHistory();
    meritLabel.textContent = `Result merit function: ${fmt(r.merit)}   (${((performance.now() - t0) / 1000).toFixed(1)} s)`;
    if (autoApply.input.checked) apply(); else applyB.disabled = false;
  };
  const apply = async () => {
    await run("load_optimization_result", { label: `Optimization (${algorithm.selectedOptions[0].textContent})` });
    applyB.disabled = true;
  };
}

// ================================================================== Tolerancing
let tolWin = null;
export async function tolerancing() {
  if (tolWin && !tolWin.closed) { tolWin.raise(); return; }
  const setup = await run("tolerance_setup");
  if (!setup) return;
  const w = tolWin = openWindow({ title: "Tolerancing", popout: "tolerancing", width: 980, height: 700, resizable: true, help: () => cmd("__help:Tools > Tolerancing") });
  const wiz = {};
  const wizGrid = el("div", { style: { display: "grid", gridTemplateColumns: "repeat(4, max-content minmax(70px, 1fr))", gap: "4px 8px", alignItems: "center" } });
  for (const [name, label, val, dec] of setup.wizard) {
    wiz[name] = numInput(val, { min: 0, max: 1e4, step: Math.pow(10, -dec) * 10 });
    wiz[name].style.width = "80px";
    wizGrid.append(el("label", {}, label), wiz[name]);
  }
  const table = el("tbody");
  const tolTable = el("table", { class: "grid" }, el("thead", {}, el("tr", {}, ...["Type", "Surf", "Surf2", "Param", "Min", "Max", "Comment"].map((h) => el("th", {}, h)))), table);
  tolTable.title = "Types: " + setup.types.join(", ");
  let selRow = -1;
  const addRow = (vals) => {
    const tr = el("tr", {}, ...vals.map((v) => el("td", {}, el("input", { type: "text", value: v }))));
    tr.addEventListener("pointerdown", () => { selRow = [...table.children].indexOf(tr); [...table.children].forEach((x) => x.classList.toggle("sel", x === tr)); });
    table.append(tr);
  };
  const generate = async () => {
    const rows = await run("default_tolerances", { wiz: Object.fromEntries(Object.entries(wiz).map(([k, i]) => [k, +i.value])) });
    if (!rows) return;
    table.replaceChildren();
    rows.forEach(addRow);
  };
  const wizBox = el("fieldset", {}, el("legend", {}, "Tolerance wizard"), wizGrid,
    el("div", { class: "row", style: { marginTop: "6px" } }, btn("Generate Default Tolerances", generate),
      btn("Add Row", () => addRow(["TTHI", "1", "", "", "-0.05", "0.05", ""])),
      btn("Remove Rows", () => { if (selRow >= 0 && table.children[selRow]) { table.children[selRow].remove(); selRow = -1; } })));
  const criterion = select(setup.criteria, "rms_spot");
  const freq = numInput(30, { min: 0.1, max: 1e5, step: 1 });
  const comp = select(setup.compensators.map(([k, l]) => [k ?? "", l]), "focus");
  const trials = numInput(100, { min: 1, max: 100000, step: 1 });
  const dist = select(setup.distributions.map((d) => [d, d]), "normal");
  const seed = numInput(0, { min: 0, max: 2 ** 31 - 1, step: 1 });
  const progress = el("div", { class: "muted" });
  const sensB = btn("Run Sensitivity", () => runIt("sensitivity"));
  const mcB = btn("Run Monte Carlo", () => runIt("monte_carlo"));
  const stopB = stopButton();
  const worstB = btn("Load Worst Monte Carlo Lens", () => run("load_worst_monte_carlo"), { disabled: true });
  const runBox = el("fieldset", {}, el("legend", {}, "Analysis"), el("div", { class: "form" },
    el("label", {}, "Criterion"), criterion, el("label", {}, `MTF frequency (cycles/${setup.units || "mm"})`), freq, el("label", {}, "Compensator"), comp,
    el("label", {}, "Monte Carlo trials"), trials, el("label", {}, "Distribution"), dist, el("label", {}, "Seed"), seed,
    el("div", { class: "full row" }, sensB, mcB, stopB), el("div", { class: "full" }, progress)));
  const plot = el("img", { style: { width: "100%", flex: "1", minHeight: "120px", objectFit: "contain", border: "1px solid var(--border-soft)" }, alt: "" });
  const output = el("pre", { class: "mono", style: { flex: "1", minHeight: "120px", border: "1px solid var(--border)", padding: "4px" } });
  const left = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "3", minWidth: "0" } }, wizBox, el("div", { class: "table-wrap" }, tolTable));
  const right = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "2", minWidth: "0" } }, runBox, plot, worstB);
  w.body.append(el("div", { style: { display: "flex", gap: "8px", flex: "3", minHeight: "0" } }, left, right), output);
  const rows = () => [...table.children].map((tr) => [...tr.querySelectorAll("input")].map((i) => i.value));
  const runIt = async (what) => {
    sensB.disabled = mcB.disabled = true; stopB.disabled = false;
    output.textContent += `=== ${what === "sensitivity" ? "Sensitivity" : "Monte Carlo"}: ${rows().length} tolerances, criterion ${criterion.selectedOptions[0].textContent}, compensator ${comp.selectedOptions[0].textContent}\n`;
    progressHandler = (p) => { if (p.kind === "tolerance") progress.textContent = `${p.done} / ${p.total} evaluations (${p.seconds} s)`; };
    const r = plot.getBoundingClientRect();
    const out = await engine.callRaw("tolerance_run", { what, rows: rows(), criterion: criterion.value, frequency: +freq.value,
      compensator: comp.value || null, trials: +trials.value, distribution: dist.value, seed: +seed.value,
      width: Math.max(300, r.width), height: Math.max(200, r.height), dpr: dpr() });
    progressHandler = null;
    sensB.disabled = mcB.disabled = false; stopB.disabled = true;
    progress.textContent = "";
    if (out.error) { output.textContent += (out.error === "Stopped" ? "Stopped." : `Failed: ${out.error}`) + "\n"; return; }
    output.textContent += out.result.text + "\n";
    output.scrollTop = output.scrollHeight;
    if (out.result.png) plot.src = "data:image/png;base64," + out.result.png;
    if (what === "monte_carlo") worstB.disabled = !out.result.worst;
  };
  generate();
}

// ================================================================== Non-Sequential Component Editor
// The lens's non-sequential scene (as lensforge_qt/ns_window.py): object and source tables laid out as
// Zemax's NSC Editor, the Ray Trace Control settings and Trace. Every edit is an undoable lens edit; the
// tables come with each lens state (state.nonseq), the analyses are Analysis > Non-Sequential windows.
const NS_HELP = "Tools > Non-Sequential > Non-Sequential Component Editor";
let nsWin = null, nsInfo = null;
export async function nsEditor() {
  if (nsWin && !nsWin.closed) { nsWin.raise(); return nsWin; }
  if (!nsInfo) nsInfo = await run("ns_info");
  if (!nsInfo) return null;
  const I = nsInfo;
  let alive = true;
  const w = nsWin = openWindow({ title: "Non-Sequential Component Editor", popout: "nonseq", width: 1180, height: 640, resizable: true, flush: true,
    help: () => cmd("__help:" + NS_HELP), onclose: () => { alive = false; } });
  let tab = "objects";
  const sel = { objects: -1, sources: -1 };
  const tb = el("div", { class: "editor-bar" });
  const tabsBar = el("div", { class: "tabs", style: { padding: "4px 6px 0" } });
  const tableWrap = el("div", { class: "table-wrap", style: { flex: "1 1 260px", minHeight: "120px", margin: "0 6px" } });
  const traceBar = el("div", { class: "an-bar", title: "Ray Trace Control: saved with the scene and used by the Analysis > Non-Sequential windows." });
  const summary = el("pre", { class: "mono", style: { flex: "0 1 170px", minHeight: "60px", overflow: "auto", border: "1px solid var(--border)", padding: "4px", margin: "0 6px 6px" } },
    "Press Trace (F5) to trace the scene; the summary appears here.");
  w.body.append(tb, tabsBar, tableWrap, traceBar, summary);

  const traceCtl = {};
  for (const [key, label, kind, tip] of I.trace_fields) {
    if (kind === "bool") {
      const c = check(label, false, (v) => edit("ns_set_trace", { key, value: v }), tip);
      traceCtl[key] = { set: (v) => { c.input.checked = !!v; } };
      traceBar.append(c);
    } else {
      const inp = numInput(0, { min: 0, max: kind === "int" ? 1000000 : 1, step: kind === "int" ? 1 : "any", width: kind === "int" ? "80px" : "100px",
        onchange: (v) => edit("ns_set_trace", { key, value: v }) });
      inp.title = tip;
      traceCtl[key] = { set: (v) => { if (document.activeElement !== inp) inp.value = String(v); } };
      traceBar.append(el("label", { title: tip }, label, inp));
    }
  }
  const tip = (k) => `${I.buttons.find((b) => b[0] === k)[1]}\n${I.buttons.find((b) => b[0] === k)[2]}`;
  const traceB = btn("Trace", () => trace(), { title: tip("trace") });
  traceBar.append(traceB);
  for (const [k, key] of [["layout", "ns_layout"], ["detector", "ns_detector"], ["paths", "ns_paths"]])
    traceBar.append(btn(I.buttons.find((b) => b[0] === k)[1], () => openAnalysis(key), { title: tip(k) }));

  async function edit(method, args) {
    try { const r = await call(method, args); status(""); return r; }
    catch (e) { statusError(`Not changed: ${e.message}`); fill(App.state); return undefined; }
  }
  const pick = (items, anchor) => new Promise((resolve) => {
    const r = (anchor || tb).getBoundingClientRect();
    import("./ui.js").then(({ popupMenu }) => popupMenu(items.map(([k, lab]) => ({ label: lab, action: () => resolve(k) })), r.left, r.bottom));
  });
  const select1 = (t, r) => { tab = t; sel[t] = r; fill(App.state); };
  const actions = {
    new: async () => {
      const st = App.state.nonseq;
      if ((st.objects.length || st.sources.length) && !(await confirmBox("New scene", "Delete every object and source of the scene?", "Delete"))) return;
      await edit("ns_new", {});
    },
    open: async () => {
      const f = await pickFile(".json");
      if (!f) return;
      try { await call("ns_open", { text: f.text, filename: f.name }); status(`Imported ${f.name}`); } catch (e) { message("Import scene", `Could not open ${esc(f.name)}: ${esc(e.message)}`); }
    },
    save: async () => { const t = await run("ns_text"); if (t) { download((App.state.nonseq.name || "scene").replace(/[\\/:*?"<>|]+/g, "_") + ".ns.json", t); status("Scene downloaded"); } },
    convert: async () => { try { await call("ns_from_lens"); status("Lens converted to a non-sequential scene"); return true; } catch (e) { message("Convert lens", esc(e.message)); return false; } },
    add_object: async (anchor) => { const k = await pick(I.object_types, anchor); const r = await edit("ns_add", { kind: k, after: sel.objects }); if (r) select1(r.table, r.row); },
    add_source: async (anchor) => { const k = await pick(I.source_types, anchor); const r = await edit("ns_add", { kind: k, after: sel.sources }); if (r) select1(r.table, r.row); },
    duplicate: async () => { if (sel[tab] < 0) return status("Select a row first"); const r = await edit("ns_duplicate", { table: tab, r: sel[tab] }); if (r) select1(tab, r.row); },
    move_up: async () => { if (sel[tab] < 0) return; const r = await edit("ns_move", { table: tab, r: sel[tab], delta: -1 }); if (r) select1(tab, r.row); },
    move_down: async () => { if (sel[tab] < 0) return; const r = await edit("ns_move", { table: tab, r: sel[tab], delta: 1 }); if (r) select1(tab, r.row); },
    delete: async () => { if (sel[tab] < 0) return status("Select a row to delete first"); await edit("ns_delete", { table: tab, r: sel[tab] }); sel[tab] = -1; fill(App.state); },
    trace: () => trace(),
    layout: () => openAnalysis("ns_layout"),
    detector: () => openAnalysis("ns_detector"),
    paths: () => openAnalysis("ns_paths"),
    help: () => cmd("__help:" + NS_HELP),
  };
  for (const [k, text, t, svg] of I.buttons) {
    const b = el("button", { type: "button", title: `${text}\n${t}`, style: { display: "inline-flex", alignItems: "center", gap: "4px" } }, iconImg(svg, 20), text);
    b.addEventListener("click", () => actions[k](b));
    tb.append(b);
    if (k === "convert" || k === "delete" || k === "trace") tb.append(el("span", { class: "sep", style: { borderLeft: "1px solid var(--border)", margin: "0 4px" } }));
  }
  w.element.addEventListener("keydown", (e) => {
    if (e.key === "F5") { e.preventDefault(); e.stopPropagation(); trace(); }
    else if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown")) { e.preventDefault(); e.stopPropagation(); actions[e.key === "ArrowUp" ? "move_up" : "move_down"](); }
  });

  function fill(state) {
    if (!alive || !state || !state.nonseq) return;
    const st = state.nonseq;
    w.setTitle(`Non-Sequential Component Editor - ${st.name}`);
    tabsBar.replaceChildren(...[["objects", `Objects (${st.objects.length})`], ["sources", `Sources (${st.sources.length})`]].map(([k, lab]) =>
      el("div", { class: "tab" + (tab === k ? " active" : ""), onclick: () => { tab = k; fill(App.state); } }, lab)));
    const isObj = tab === "objects";
    const cols = isObj ? I.obj_cols : I.src_cols;
    const par0 = isObj ? I.obj_par0 : I.src_par0;
    const rows = isObj ? st.objects : st.sources;
    const types = isObj ? I.object_types : I.source_types;
    if (sel[tab] >= rows.length) sel[tab] = rows.length - 1;
    const labels = sel[tab] >= 0 ? rows[sel[tab]].labels : [];
    const head = cols.map((h) => el("th", { title: I.column_tips[h] || "" }, h));
    const nameHeads = (labs) => cols.forEach((h, c) => {
      if (c < par0) return;
      head[c].textContent = labs[c - par0] || h;
      head[c].title = labs[c - par0] ? `${labs[c - par0]}\n${I.column_tips[h] || ""}` : I.column_tips[h] || "";
    });
    nameHeads(labels);
    const tbody = el("tbody");
    rows.forEach((row, r) => {
      const tr = el("tr", { class: sel[tab] === r ? "sel" : "" });
      tr.append(el("td", { class: "num", style: { color: "var(--muted, #667)" } }, isObj ? String(r + 1) : `S${r + 1}`));
      row.cells.forEach((v, c) => {
        if (c === 0) {
          const s = select(types, row.kind, (k) => edit("ns_change_type", { table: tab, r, kind: k }), { title: I.column_tips.Type, style: "max-width: 190px" });
          tr.append(el("td", {}, s));
          return;
        }
        const bad = row.bad.includes(c);
        if (!row.editable[c]) { tr.append(el("td", { title: row.tips[c], style: { background: "#eee" } }, v)); return; }
        const inp = el("input", { type: "text", value: v, title: row.tips[c], "data-r": String(r), "data-c": String(c),
          style: { width: `${Math.max(c === 1 ? 10 : 6, Math.min(24, v.length + 2))}ch` } });
        inp.addEventListener("change", () => edit("ns_set_cell", { table: tab, r, c, text: inp.value }));
        tr.append(el("td", { style: bad ? { background: "#ffd6d6" } : {} }, inp));
      });
      tr.addEventListener("pointerdown", () => {  // select the row (Par headers follow) without rebuilding it
        if (sel[tab] === r) return;
        sel[tab] = r;
        tbody.querySelectorAll("tr").forEach((x, i) => x.classList.toggle("sel", i === r));
        nameHeads(row.labels);
      });
      tbody.append(tr);
    });
    const t = el("table", { class: "grid", style: { width: "auto" }, title: isObj ? "One row per object. The Par columns are named after the selected row's type (hover a cell for its parameter); grey cells do not apply to the row." :
      "One row per source. Rays leave along the source's local +z axis." },
      el("thead", {}, el("tr", {}, el("th", {}, "#"), ...head)), tbody);
    // keep the focus in the cell the user is in (an edit's new state rebuilds the table)
    const a = document.activeElement;
    const at = a && tableWrap.contains(a) && a.dataset && a.dataset.r !== undefined ? [a.dataset.r, a.dataset.c] : null;
    const scroll = tableWrap.scrollTop;
    tableWrap.replaceChildren(t);
    tableWrap.scrollTop = scroll;
    if (at) { const inp = t.querySelector(`input[data-r="${at[0]}"][data-c="${at[1]}"]`); if (inp) { inp.focus({ preventScroll: true }); inp.select(); } }
    for (const [k, c] of Object.entries(traceCtl)) c.set(st.trace[k]);
  }
  async function trace() {
    summary.textContent = "Tracing...";
    traceB.disabled = true;
    try { summary.textContent = await call("ns_trace"); }
    catch (e) { summary.textContent = `Trace failed: ${e.message}`; }
    traceB.disabled = false;
  }
  onState((s) => fill(s));
  w.fromLens = actions.convert;
  fill(App.state);
  return w;
}

// ================================================================== Help browser
let helpWin = null;
export function helpBrowser(itemId) {
  if (helpWin && !helpWin.closed) { helpWin.raise(); if (itemId) helpWin.showItem(itemId); return helpWin; }
  const w = helpWin = openWindow({ title: "LensForge Help", popout: "help", width: 980, height: 680, resizable: true });
  const filter = el("input", { type: "text", placeholder: "Filter: type a word to find commands and pages" });
  const tree = el("div", { class: "tree", style: { width: "330px", flex: "none" } });
  const page = el("div", { class: "help-page", style: { flex: "1" } });
  w.body.append(filter, el("div", { style: { display: "flex", gap: "8px", flex: "1", minHeight: "0" } }, tree, page));
  const H = App.help, C = App.menus.commands;
  let current = itemId || ":overview";
  const commandHtml = (id) => {
    const c = C[id];
    const where = esc(id.replace(/ > /g, " ▸ "));
    const head = `<div class="help-head">${c && c.icon ? `<img src="${svgURL(c.icon)}" alt="">` : ""}<div><h2 style="margin:0">${esc(c ? c.path[c.path.length - 1] : id)}</h2>` +
      `<span class="muted">${where}${c && c.shortcut ? `&nbsp;&nbsp;·&nbsp;&nbsp;Shortcut: <b>${esc(keyLabel(c.shortcut))}</b>` : ""}</span></div></div>`;
    if (!c || !c.summary) return head + "<p><i>No help has been written for this command yet.</i></p>";
    return `${head}<p><b>${c.summary}</b></p><p>${c.details}</p>`;
  };
  const menuHtml = (name) => {
    const rows = Object.entries(C).filter(([, c]) => c.path[0] === name).map(([id, c]) =>
      `<tr><td valign="top">${c.icon ? `<img src="${svgURL(c.icon)}" width="20" height="20" alt="">` : ""}</td><td valign="top"><b>${esc(c.path.slice(1).join(" ▸ "))}</b></td>` +
      `<td valign="top" style="padding-left:8px">${c.summary}</td></tr>`).join("");
    return `<h2>${esc(name)} menu</h2><table cellspacing="4">${rows}</table>`;
  };
  const show = (id) => {
    current = id;
    if (id === ":overview") page.innerHTML = H.overview;
    else if (id.startsWith(":menu:")) page.innerHTML = menuHtml(id.slice(6));
    else if (id.startsWith(":topic:")) page.innerHTML = (H.topics.find((t) => t.key === id) || {}).html || "";
    else page.innerHTML = commandHtml(id);
    page.scrollTop = 0;
    tree.querySelectorAll(".node").forEach((n) => n.classList.toggle("sel", n.dataset.id === id));
    tree.querySelector(".node.sel")?.scrollIntoView({ block: "nearest" });
  };
  page.addEventListener("click", (e) => {
    const a = e.target.closest("a[href]");
    if (!a) return;
    const href = a.getAttribute("href");
    if (href.startsWith("help:")) { e.preventDefault(); show(":topic:" + href.slice(5)); }
    else if (!href.startsWith("#")) { a.target = "_blank"; a.rel = "noopener"; }
  });
  const build = () => {
    const f = filter.value.trim().toLowerCase();
    tree.replaceChildren();
    const node = (id, label, depth, icon, branch) => {
      const n = el("div", { class: "node" + (branch ? " branch" : "") + (id === current ? " sel" : ""), style: { paddingLeft: 6 + depth * 16 + "px" }, "data-id": id }, icon ? iconImg(icon, 16) : null, label);
      n.addEventListener("click", () => show(id));
      tree.append(n);
    };
    if (!f) node(":overview", "Overview", 0, null, true);
    for (const top of App.menus.tree) {
      const entries = Object.entries(C).filter(([, c]) => c.path[0] === top.label);
      const match = entries.filter(([id, c]) => !f || (id + " " + c.summary + " " + c.details).toLowerCase().includes(f));
      if (match.length) {
        node(":menu:" + top.label, top.label + " menu", 0, null, true);
        let lastGroup = "";
        for (const [id, c] of match) {
          const group = c.path.slice(1, -1).join(" ▸ ");
          if (group && group !== lastGroup) { node(":menu:" + top.label, group, 1, null, true); tree.lastChild.dataset.id = ""; tree.lastChild.onclick = null; }
          lastGroup = group;
          node(id, c.path[c.path.length - 1], group ? 2 : 1, c.icon);
        }
      }
      if (top.label === "Tools") {
        const topics = H.topics.filter((t) => !f || t.text.toLowerCase().includes(f) || t.title.toLowerCase().includes(f));
        topics.forEach((t, i) => node(t.key, t.title, i === 0 && t.key === H.root ? 0 : 1, null, t.key === H.root));
      }
    }
  };
  filter.addEventListener("input", () => {
    build();
    const first = [...tree.querySelectorAll(".node")].find((n) => n.dataset.id && !n.classList.contains("branch"));
    if (filter.value && first) show(first.dataset.id);
  });
  w.showItem = (id) => { if (filter.value) { filter.value = ""; build(); } show(id); };
  build();
  show(current);
  return w;
}

// ================================================================== Customize Toolbar
export const STYLE_LABELS = [["icons", "Icons only"], ["icons+text", "Icons with text below"], ["icon+text beside", "Icons with text beside"], ["text", "Text only"]];

export function customizeToolbar(items, style, defaults) {
  return dialog({ title: "Customize Toolbar", width: 820, height: 600, resizable: true }, (win, done, bar) => {
    const C = App.menus.commands, SEP = App.menus.separator;
    let ids = items.slice();
    let selAvail = null, selTb = -1;
    const filter = el("input", { type: "text", placeholder: "Filter commands" });
    const avail = el("div", { class: "tree", style: { flex: "1" } });
    const tb = el("div", { class: "list", style: { flex: "1" } });
    const fillAvail = () => {
      const f = filter.value.toLowerCase();
      avail.replaceChildren();
      for (const [id, c] of Object.entries(C)) {
        if (f && !id.toLowerCase().includes(f)) continue;
        const n = el("div", { class: "node" + (selAvail === id ? " sel" : "") + (ids.includes(id) ? " muted" : ""), title: c.summary },
          iconImg(c.icon, 16), id.replace(/ > /g, " ▸ "));
        n.addEventListener("click", () => { selAvail = id; fillAvail(); });
        n.addEventListener("dblclick", () => { selAvail = id; add(); });
        avail.append(n);
      }
    };
    const fillTb = () => {
      tb.replaceChildren(...ids.map((id, i) => {
        const d = el("div", { class: (i === selTb ? "sel" : "") + (id === SEP ? " sep-item" : "") },
          id === SEP ? "──────  separator  ──────" : el("span", { style: { display: "inline-flex", gap: "6px", alignItems: "center" } }, iconImg(C[id] && C[id].icon, 16), C[id] ? C[id].path.join(" ▸ ") : id + " (missing)"));
        d.addEventListener("click", () => { selTb = i; fillTb(); });
        return d;
      }));
    };
    const add = () => { if (!selAvail) return; const at = selTb >= 0 ? selTb + 1 : ids.length; ids.splice(at, 0, selAvail); selTb = at; fillTb(); fillAvail(); };
    const addSep = () => { const at = selTb >= 0 ? selTb + 1 : ids.length; ids.splice(at, 0, SEP); selTb = at; fillTb(); };
    const remove = () => { if (selTb < 0) return; ids.splice(selTb, 1); selTb = Math.min(selTb, ids.length - 1); fillTb(); fillAvail(); };
    const moveBy = (d) => { const j = selTb + d; if (selTb < 0 || j < 0 || j >= ids.length) return; [ids[selTb], ids[j]] = [ids[j], ids[selTb]]; selTb = j; fillTb(); };
    filter.addEventListener("input", fillAvail);
    const styleSel = select(STYLE_LABELS, style);
    const mid = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", justifyContent: "center" } },
      btn("Add →", add), btn("Separator →", addSep), btn("← Remove", remove), btn("Move Up", () => moveBy(-1)), btn("Move Down", () => moveBy(1)),
      btn("Reset", () => { ids = defaults.slice(); selTb = -1; fillTb(); fillAvail(); }));
    win.body.append(el("div", { style: { display: "flex", gap: "8px", flex: "1", minHeight: "0" } },
      el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minWidth: "0" } }, el("b", {}, "Menu commands"), filter, avail),
      mid, el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minWidth: "0" } }, el("b", {}, "Toolbar buttons"), tb)),
      el("div", { class: "row" }, el("label", {}, "Buttons show"), styleSel));
    bar.append(btn("Cancel", () => done(null)), btn("OK", () => done({ ids, style: styleSel.value }), { primary: true }));
    fillAvail();
    fillTb();
  });
}
