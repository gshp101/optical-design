// Tools: optimisation, tolerancing, the non-sequential editor, the help browser and Customize Toolbar
// (as lensforge_qt/opt_dialogs.py, ns_window.py, help_browser.py and toolbar_dialog.py).
import { App, run, call, status, statusError, onState, cmd } from "./core.js";
import * as engine from "./engine.js";
import * as store from "./storage.js";
import { el, esc, btn, select, numInput, check, openWindow, dialog, message, confirmBox, download, pickFile, iconImg, svgURL, copyText } from "./ui.js";

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
    el("label", {}, "Criterion"), criterion, el("label", {}, "MTF frequency (cycles/mm)"), freq, el("label", {}, "Compensator"), comp,
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

// ================================================================== Non-Sequential Editor
let nsWin = null;
export async function nsEditor() {
  if (nsWin && !nsWin.closed) { nsWin.raise(); return nsWin; }
  const w = nsWin = openWindow({ title: "Non-Sequential Editor", popout: "nonseq", width: 1200, height: 820, resizable: true, flush: true,
    help: () => cmd("__help:Tools > Non-Sequential > Non-Sequential Editor") });
  let st = await run("ns_state");
  let tab = "objects", sel = { objects: -1, sources: -1 };
  const tb = el("div", { class: "editor-bar" });
  const tabsBar = el("div", { class: "tabs", style: { padding: "4px 6px 0" } });
  const tableWrap = el("div", { class: "table-wrap", style: { flex: "0 0 260px", margin: "0 6px" } });
  const split = check("Split rays", true, null, "Follow both the reflected and transmitted part at every refracting face (shows ghosts and stray light).");
  const fresnel = check("Fresnel losses", true);
  const minInt = numInput(1e-5, { min: 0, max: 1, step: 1e-5 });
  minInt.title = "Minimum relative ray intensity: split rays weaker than this fraction of their source ray are dropped.";
  const maxSeg = numInput(100, { min: 2, max: 10000, step: 1 });
  maxSeg.title = "Maximum segments per ray.";
  const det = el("select", { title: "Detector shown on the right." });
  const filt = select([["all", "All rays"], ["direct", "Direct (no reflection)"], ["ghost", "Ghosts (2+ reflections)"], ["1", "1 reflection"], ["2", "2 reflections"], ["3", "3 reflections"], ["4", "4 reflections"]], "all");
  filt.title = "Which rays the detector image and the layout count, by the number of Fresnel (partial) reflections they took.";
  const log = check("Log scale", true);
  const plane = select([["y", "YZ layout"], ["x", "XZ layout"]], "y");
  const traceB = btn("Trace", () => trace(), { title: "Trace all sources with the settings below and show the rays and the detector (F5)." });
  const plotImg = el("img", { style: { flex: "1", minHeight: "0", width: "100%", objectFit: "contain" }, alt: "" });
  const summary = el("pre", { class: "mono", style: { height: "100px", border: "1px solid var(--border)", padding: "4px", margin: "0 6px 6px", flex: "none" } });
  const settings = el("div", { class: "an-bar" }, split, fresnel, el("label", {}, "Min. intensity", minInt), el("label", {}, "Max. segments", maxSeg),
    el("label", {}, "Detector", det), el("label", {}, "Show", filt), log, plane, traceB);
  w.body.append(tb, tabsBar, tableWrap, settings, el("div", { style: { flex: "1", minHeight: "0", display: "flex", padding: "0 6px" } }, plotImg), summary);
  [det, filt, plane].forEach((x) => x.addEventListener("change", () => redraw()));
  log.input.addEventListener("change", () => redraw());

  const pick = async (kinds) => new Promise((resolve) => {
    const r = tb.getBoundingClientRect();
    import("./ui.js").then(({ popupMenu }) => popupMenu(kinds.map(([k, lab]) => ({ label: lab, action: () => resolve(k) })), r.left + 120, r.bottom));
  });
  const actions = {
    new: async () => { if ((st.objects.length || st.sources.length) && !(await confirmBox("New scene", "Discard the current scene?", "Discard"))) return; await run("ns_new"); refresh(); },
    open: async () => {
      const f = await pickFile(".json");
      if (!f) return;
      try { await call("ns_open", { text: f.text, filename: f.name }); refresh(); } catch (e) { message("Open scene", `Could not open ${esc(f.name)}: ${esc(e.message)}`); }
    },
    save: async () => { const t = await run("ns_text"); if (t) { download((st.name || "scene").replace(/[\\/:*?"<>|]+/g, "_") + ".ns.json", t); status("Scene downloaded"); } },
    convert: async () => { try { await call("ns_from_lens"); refresh(); } catch (e) { message("Convert lens", esc(e.message)); } },
    add_object: async () => { const k = await pick(st.object_types); const r = await run("ns_add", { kind: k, after: sel.objects }); if (r) { tab = r.table; sel[tab] = r.row; refresh(); } },
    add_source: async () => { const k = await pick(st.source_types); const r = await run("ns_add", { kind: k }); if (r) { tab = r.table; sel[tab] = r.row; refresh(); } },
    delete: async () => { await run("ns_delete", { table: tab, r: sel[tab] }); sel[tab] = -1; refresh(); },
    trace: () => trace(),
    help: () => cmd("__help:Tools > Non-Sequential > Non-Sequential Editor"),
  };
  tb.append(...st.buttons.map(([k, text, tip, svg]) => el("button", { type: "button", title: `${text}\n${tip}`, onclick: actions[k],
    style: { display: "inline-flex", alignItems: "center", gap: "4px" } }, iconImg(svg, 20), text)));
  w.element.addEventListener("keydown", (e) => { if (e.key === "F5") { e.preventDefault(); e.stopPropagation(); trace(); } });

  const fill = () => {
    w.setTitle(`Non-Sequential Editor - ${st.name}`);
    tabsBar.replaceChildren(...[["objects", "Objects"], ["sources", "Sources"]].map(([k, lab]) =>
      el("div", { class: "tab" + (tab === k ? " active" : ""), onclick: () => { tab = k; fill(); } }, lab)));
    const cols = tab === "objects" ? st.obj_cols : st.src_cols;
    const items = tab === "objects" ? st.objects : st.sources;
    const tbody = el("tbody");
    items.forEach((it, r) => {
      const tr = el("tr", { class: sel[tab] === r ? "sel" : "" });
      it.cells.forEach((v, c) => {
        if (c === 0) { tr.append(el("td", {}, v)); return; }
        const inp = el("input", { type: "text", value: v, title: c === it.cells.length - 1 ? it.tip : "" });
        inp.addEventListener("change", async () => {
          try { await call("ns_set_cell", { table: tab, r, c, text: inp.value }); status(""); }
          catch (e) { statusError(`Not changed: ${e.message}`); }
          refresh();
        });
        tr.append(el("td", {}, inp));
      });
      tr.addEventListener("pointerdown", () => { if (sel[tab] !== r) { sel[tab] = r; tbody.querySelectorAll("tr").forEach((x, i) => x.classList.toggle("sel", i === r)); } });
      tbody.append(tr);
    });
    const t = el("table", { class: "grid", title: tab === "objects" ? "One row per object. Edit any cell; Parameters are name=value pairs (hover a row's Parameters cell for the names)." : "One row per source. Rays leave along the source's local +z axis." },
      el("thead", {}, el("tr", {}, ...cols.map((h) => el("th", {}, h)))), tbody);
    tableWrap.replaceChildren(t);
    const cur = det.value;
    det.replaceChildren(...st.detectors.map(([k, lab]) => el("option", { value: String(k) }, lab)));
    if (st.detectors.some(([k]) => String(k) === cur)) det.value = cur;
  };
  const refresh = async () => { st = await run("ns_state"); fill(); if (!st.traced) { plotImg.removeAttribute("src"); summary.textContent = st.summary; } };
  const trace = async () => {
    summary.textContent = "Tracing...";
    traceB.disabled = true;
    const r = await run("ns_trace", { split: split.input.checked, fresnel: fresnel.input.checked, min_relative_intensity: +minInt.value, max_segments: +maxSeg.value });
    traceB.disabled = false;
    if (!r) { summary.textContent = "Trace failed."; return; }
    summary.textContent = r.summary;
    if (r.traced) redraw();
  };
  const redraw = async () => {
    const b = plotImg.parentNode.getBoundingClientRect();
    const rays = filt.value;
    const png = await run("ns_plot", { detector: det.value === "" ? null : +det.value, rays: /^\d$/.test(rays) ? +rays : rays, log: log.input.checked,
      plane: plane.value, width: Math.max(500, b.width), height: Math.max(250, b.height), dpr: dpr() });
    if (png) plotImg.src = "data:image/png;base64," + png; else plotImg.removeAttribute("src");
  };
  w.fromLens = actions.convert;
  fill();
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
      `<span class="muted">${where}${c && c.shortcut ? `&nbsp;&nbsp;·&nbsp;&nbsp;Shortcut: <b>${esc(c.shortcut)}</b>` : ""}</span></div></div>`;
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
