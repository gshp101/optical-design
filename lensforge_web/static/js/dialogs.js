// Dialogs of the File and Edit menus and the Lens Data Editor (as the Qt dialogs of lensforge_qt).
import { App, run, call, status, statusError } from "./core.js";
import { el, esc, btn, select, numInput, check, tabs, dialog, message, confirmBox, prompt, openWindow,
  download, pickFile, copyText, fmtDate, fmtSize, svgURL } from "./ui.js";
import * as store from "./storage.js";

// ================================================================== solves
export async function solveDialog(row, key, name) {
  const form = await run("solve_form", { row, key, name });
  if (!form) return;
  await dialog({ title: form.title, width: 420 }, (win, done, bar) => {
    win.body.append(el("div", { class: "note" }, form.doc));
    const grid = el("div", { class: "form" });
    const inputs = {};
    for (const f of form.fields) {
      inputs[f.name] = el("input", { type: "text", value: f.value, placeholder: f.placeholder });
      grid.append(el("label", {}, f.label), inputs[f.name]);
    }
    win.body.append(grid);
    const ok = async () => {
      const values = Object.fromEntries(Object.entries(inputs).map(([k, i]) => [k, i.value]));
      try { await call("set_solve", { row, key, name, values }); done(true); }
      catch (e) { await message("Solve", esc(e.message)); }
    };
    win.body.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } });
    bar.append(btn("Cancel", () => done(null)), btn("OK", ok, { primary: true }));
  });
}

// ================================================================== deleting surfaces
export function confirmDelete(first, last, lines) {
  const n = last - first + 1;
  const what = n === 1 ? `surface ${first}` : `surfaces ${first} to ${last} (${n} surfaces)`;
  const shown = lines.length <= 14 ? lines : lines.slice(0, 12).concat([`... and ${lines.length - 12} more (see below)`]);
  return message("Delete Surfaces", `<p><b>Delete ${esc(what)}?</b></p><p>${shown.map(esc).join("<br>")}</p>` +
    "<p>You can undo this with Edit &gt; Undo.</p>", {
    buttons: [["Delete", true, false], ["Cancel", false, true]],
    detail: lines.length > 14 ? lines.join("\n") : undefined,
  });
}

export async function deleteSurfacesDialog(first, last) {
  const ima = App.state.image_index;
  const hi = Math.max(1, ima - 1);
  return dialog({ title: "Delete Surfaces", width: 480 }, (win, done, bar) => {
    const a = numInput(Math.max(1, Math.min(first, hi)), { min: 1, max: hi, step: 1 });
    const b = numInput(Math.max(1, Math.min(last, hi)), { min: 1, max: hi, step: 1 });
    const preview = el("pre", { class: "mono", style: { minHeight: "140px", border: "1px solid var(--border)", padding: "6px", whiteSpace: "pre-wrap" } });
    const okBtn = btn("Delete...", () => done([+a.value, +b.value]), { primary: true });
    const update = async () => {
      const d = await run("describe_deletion", { first: +a.value, last: +b.value }, { quiet: true });
      const ok = d && !d.error && ima > 1;
      preview.textContent = d ? (d.error || d.lines.join("\n")) : "";
      okBtn.disabled = !ok;
    };
    a.addEventListener("input", update);
    b.addEventListener("input", update);
    win.body.append(el("div", {}, `Surfaces 1 to ${hi} can be deleted; the object and image surfaces cannot. You will be asked to confirm.`),
      el("div", { class: "form" }, el("label", {}, "From surface"), a, el("label", {}, "To surface"), b),
      el("div", {}, "Will be deleted:"), preview);
    bar.append(btn("Cancel", () => done(null)), okBtn);
    update();
  });
}

// ================================================================== surface properties
export async function surfacePropertiesDialog(row) {
  const p = await run("surface_properties", { row });
  if (!p) return;
  await dialog({ title: p.title, width: 440 }, (win, done, bar) => {
    const comment = el("input", { type: "text", value: p.comment });
    const stop = check("This surface is the aperture stop", p.stop);
    stop.input.disabled = !p.stop_enabled;
    const kind = select(p.kinds.map(([lab, k]) => [k ?? "", lab]), p.aperture ?? "");
    const grid = el("div", { class: "form" }, el("label", {}, "Comment"), comment, el("span"), stop, el("label", {}, "Aperture"), kind);
    const edits = {};
    for (const n of ["r_max", "r_min", "radius", "half_x", "half_y", "dx", "dy"]) {
      edits[n] = el("input", { type: "text", value: p.values[n] });
      grid.append(el("label", {}, "  " + n), edits[n]);
    }
    let terms = null;
    if (p.terms !== null) {
      terms = el("textarea", { class: "mono", rows: 6, placeholder: "one term per line: i j coefficient   (x^i y^j / R0^(i+j))" }, p.terms);
      grid.append(el("label", {}, "XY terms"), terms);
    }
    const enable = () => {
      const names = (p.kinds.find(([, k]) => (k ?? "") === kind.value) || [, , []])[2];
      for (const [n, i] of Object.entries(edits)) i.disabled = !names.includes(n);
    };
    kind.addEventListener("change", enable);
    enable();
    win.body.append(grid);
    const ok = async () => {
      const data = { comment: comment.value, stop: stop.input.checked, aperture: kind.value || null,
        values: Object.fromEntries(Object.entries(edits).map(([k, i]) => [k, i.value])), terms: terms ? terms.value : null };
      try { await call("set_surface_properties", { row, data }); done(true); }
      catch (e) { await message("Surface properties", "Invalid value: " + esc(e.message)); }
    };
    bar.append(btn("Cancel", () => done(null)), btn("OK", ok, { primary: true }));
  });
}

// ================================================================== material picker
let catalogCache = null;
export function forgetCatalogCache() { catalogCache = null; }

export async function materialDialog(row) {
  const init = await run("material_dialog", { row });
  if (!init) return null;
  if (!catalogCache) catalogCache = await run("catalog_rows");
  return dialog({ title: init.title, width: 900, height: 600, resizable: true }, (win, done, bar) => {
    let rows = catalogCache.rows;
    let selected = init.spec;
    // ---- catalog tab
    const cat = select([["", "All"], ...catalogCache.catalogs.map((c) => [c, c])], "");
    const filter = el("input", { type: "text", placeholder: "Filter by any part of the name, e.g. BK7 or LAH", class: "grow" });
    const loadBtn = btn("Load AGF Catalog...", async () => {
      if (await loadAGF()) { catalogCache = await run("catalog_rows"); rows = catalogCache.rows;
        cat.replaceChildren(...[["", "All"], ...catalogCache.catalogs.map((c) => [c, c])].map(([v, l]) => el("option", { value: v }, l))); fill(); }
    });
    const tbody = el("tbody");
    const table = el("table", { class: "grid" }, el("thead", {}, el("tr", {}, ...["Glass", "Catalog", "nd", "Vd"].map((h, i) =>
      el("th", { onclick: () => sortBy(i), title: "Sort" }, h)))), tbody);
    const wrap = el("div", { class: "table-wrap" }, table);
    const map = el("div", { style: { flex: "1", minWidth: "0", display: "flex" } });
    let sortCol = -1, sortDir = 1;
    const squash = (t) => String(t).toUpperCase().replace(/[-\s]/g, "");
    const visible = () => {
      const c = cat.value, t = squash(filter.value);
      let v = rows.filter((r) => (!c || r[1] === c) && (!t || squash(r[2]).includes(t)));
      if (sortCol >= 0) v = v.slice().sort((a, b) => (a[sortCol + 1] < b[sortCol + 1] ? -1 : a[sortCol + 1] > b[sortCol + 1] ? 1 : 0) * sortDir);
      return v;
    };
    const sortBy = (i) => { sortDir = sortCol === i ? -sortDir : 1; sortCol = i; fill(); };
    const fill = () => {
      const v = visible();
      tbody.replaceChildren(...v.slice(0, 3000).map((r) => {
        const tr = el("tr", { class: r[0] === selected ? "sel" : "", onclick: () => pick(r[0]), ondblclick: () => accept() },
          el("td", {}, r[2]), el("td", {}, r[1]), el("td", { class: "num" }, r[3].toFixed(5)), el("td", { class: "num" }, r[4].toFixed(2)));
        tr.dataset.spec = r[0];
        return tr;
      }));
      drawMap(v);
    };
    const drawMap = (v) => {
      const W = 420, H = 380, m = { l: 48, r: 10, t: 22, b: 36 };
      const hl = rows.find((r) => r[0] === selected);
      const pts = v.length ? v : (hl ? [hl] : []);
      const vd = pts.map((r) => r[4]), nd = pts.map((r) => r[3]);
      let x0 = Math.min(...vd, 20), x1 = Math.max(...vd, 90), y0 = Math.min(...nd, 1.45), y1 = Math.max(...nd, 2.0);
      const px = (x) => m.l + (x1 - x) / (x1 - x0) * (W - m.l - m.r);  // Abbe axis reversed
      const py = (y) => H - m.b - (y - y0) / (y1 - y0) * (H - m.t - m.b);
      const ns = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(ns, "svg");
      svg.setAttribute("viewBox", `0 0 ${W} ${H}`);
      svg.setAttribute("class", "glass-map");
      const add = (tag, attrs, text) => { const e = document.createElementNS(ns, tag); for (const [k, v2] of Object.entries(attrs)) e.setAttribute(k, v2); if (text) e.textContent = text; svg.append(e); return e; };
      for (let k = 0; k <= 5; k++) {
        const x = x0 + (x1 - x0) * k / 5, y = y0 + (y1 - y0) * k / 5;
        add("line", { x1: px(x), x2: px(x), y1: m.t, y2: H - m.b, class: "gridline" });
        add("line", { x1: m.l, x2: W - m.r, y1: py(y), y2: py(y), class: "gridline" });
        add("text", { x: px(x), y: H - m.b + 13, "text-anchor": "middle", class: "lab" }, x.toFixed(0));
        add("text", { x: m.l - 4, y: py(y) + 3, "text-anchor": "end", class: "lab" }, y.toFixed(2));
      }
      add("text", { x: (W + m.l) / 2, y: H - 4, "text-anchor": "middle", class: "lab" }, "Abbe number Vd");
      add("text", { x: 12, y: (H) / 2, "text-anchor": "middle", class: "lab", transform: `rotate(-90 12 ${H / 2})` }, "index nd");
      add("text", { x: (W + m.l) / 2, y: 14, "text-anchor": "middle", class: "lab" }, "Glass map");
      const labels = v.length <= 400;
      for (const r of v) {
        const c = add("circle", { cx: px(r[4]), cy: py(r[3]), r: 3 });
        c.addEventListener("click", () => pick(r[0], true));
        c.addEventListener("dblclick", () => { pick(r[0], true); accept(); });
        const t = document.createElementNS(ns, "title"); t.textContent = `${r[2]} (${r[1]}): nd ${r[3].toFixed(5)}, Vd ${r[4].toFixed(2)}`; c.append(t);
        if (labels) add("text", { x: px(r[4]) + 3, y: py(r[3]) - 3 }, r[2]);
      }
      if (hl) add("circle", { cx: px(hl[4]), cy: py(hl[3]), r: 7, class: "hl" });
      map.replaceChildren(svg);
    };
    const pick = (spec, scroll) => {
      selected = spec;
      tbody.querySelectorAll("tr").forEach((tr) => tr.classList.toggle("sel", tr.dataset.spec === spec));
      if (scroll) tbody.querySelector("tr.sel")?.scrollIntoView({ block: "nearest" });
      drawMap(visible());
      preview();
    };
    cat.addEventListener("change", fill);
    filter.addEventListener("input", fill);
    const catPage = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minHeight: "0" } },
      el("div", { class: "row" }, el("label", {}, "Catalog"), cat, filter, loadBtn),
      el("div", { style: { display: "flex", gap: "8px", flex: "1", minHeight: "0" } }, el("div", { style: { flex: "1", display: "flex", minWidth: "0" } }, wrap), map),
      el("div", { class: "note" }, "Click a glass on the map (Abbe diagram) or in the table; double-click to choose."));
    // ---- model glass tab
    const mnd = numInput(init.nd, { min: 1, max: 4.5, step: 0.0001 });
    const mvd = numInput(init.vd, { min: 5, max: 120, step: 0.01 });
    const mdp = numInput(init.dpgf, { min: -0.1, max: 0.1, step: 0.0001 });
    [mnd, mvd, mdp].forEach((i) => i.addEventListener("input", () => preview()));
    const modelPage = el("div", { class: "form" }, el("label", {}, "nd"), mnd, el("label", {}, "Vd"), mvd, el("label", {}, "dPgF"), mdp,
      el("div", { class: "full note" }, "A model glass is defined by its index and Abbe number; it can be optimised (Vary Glass) and later snapped to the nearest catalog glass."));
    // ---- other tab
    const other = el("div", { class: "form" });
    const radio = (value, label) => { const r = el("input", { type: "radio", name: "lf-other", value, checked: init.other === value }); r.addEventListener("change", () => preview()); return el("label", { class: "check" }, r, label); };
    const on = numInput(init.n, { min: 0.01, max: 10, step: 0.001 });
    on.addEventListener("input", () => preview());
    other.append(radio("air", "Air (no material)"), el("span"), radio("mirror", "Mirror (reflecting surface)"), el("span"), radio("const", "Constant index"), on);
    const t = tabs([["Catalog Glass", catPage], ["Model Glass", modelPage], ["Other", other]], init.tab, () => preview());
    const prev = el("div", { style: { padding: "4px", minHeight: "2.6em" } });
    win.body.append(t.element, prev);
    win.body.style.overflow = "hidden";
    const chosen = () => {
      if (t.index === 0) return selected;
      if (t.index === 1) {
        const dp = parseFloat(mdp.value) || 0;
        return `${+parseFloat(mnd.value).toPrecision(6)},${+parseFloat(mvd.value).toPrecision(6)}` + (dp ? `,${+dp.toPrecision(5)}` : "");
      }
      const v = other.querySelector("input[name=lf-other]:checked")?.value;
      if (v === "mirror") return "MIRROR";
      if (v === "const") return String(+parseFloat(on.value).toPrecision(6));
      return "";
    };
    let ptoken = 0;
    const preview = async () => {
      const my = ++ptoken;
      const h = await run("material_preview", { spec: chosen() ?? null }, { quiet: true });
      if (my === ptoken) prev.innerHTML = h || "";
    };
    const accept = async () => {
      const spec = chosen();
      if (spec === null || spec === undefined) { await message("Material", "Select a glass first."); return; }
      done(spec);
    };
    bar.append(btn("Cancel", () => done(null)), btn("OK", accept, { primary: true }));
    fill();
    preview();
    setTimeout(() => tbody.querySelector("tr.sel")?.scrollIntoView({ block: "center" }), 0);
  });
}

export async function loadAGF() {
  const f = await pickFile(".agf,.AGF");
  if (!f) return false;
  try {
    const r = await call("load_agf", { name: f.name, text: f.text });
    await store.put("catalogs", { name: r.catalog, file: f.name, text: f.text, saved: Date.now() });
    forgetCatalogCache();
    status(`Loaded glass catalog ${f.name} (${r.glasses} glasses); it is reloaded every time LensForge starts`);
    return true;
  } catch (e) {
    await message("Glass catalog", `Could not load ${esc(f.name)}:<br>${esc(e.message)}`);
    return false;
  }
}

// ================================================================== System Explorer
export async function systemExplorer(tab = 0) {
  const d = await run("system_settings");
  if (!d) return;
  await dialog({ title: "System Explorer", width: 660, height: 520, resizable: true }, (win, done, bar) => {
    // aperture
    const apType = select(d.aperture_types, d.aperture_type);
    const apValue = el("input", { type: "text", value: d.aperture_value });
    const aiming = select([["paraxial", "Paraxial"], ["real", "Real"]], d.ray_aiming);
    const apPage = el("div", { class: "form" }, el("label", {}, "Aperture Type"), apType, el("label", {}, "Aperture Value"), apValue,
      el("label", {}, "Ray Aiming"), aiming);
    // fields
    const fieldType = select(d.field_types, d.field_type);
    const fTable = editTable(["X", "Y", "Weight", "VDX", "VDY", "VCX", "VCY"], d.fields);
    const fPage = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minHeight: "0" } },
      el("div", { class: "row" }, el("label", {}, "Field Type"), fieldType),
      fTable.element,
      el("div", { class: "row" }, btn("Add Field", () => fTable.add(["0", "0", "1", "0", "0", "0", "0"])),
        btn("Remove Field", () => fTable.removeSelected()),
        btn("Equal-Area Fields...", () => {
          const ys = fTable.values().map((r) => Math.abs(parseFloat(r[1]) || 0));
          const ymax = Math.max(...ys, 0) || 1;
          fTable.set(Array.from({ length: 5 }, (_, k) => ["0", String(+(ymax * Math.sqrt(k / 4)).toPrecision(6)), "1", "0", "0", "0", "0"]));
        })));
    // wavelengths
    let primary = d.primary;
    const wTable = editTable(["Wavelength (um)", "Weight", "Primary"], d.waves.map((w, i) => [...w, i === primary ? "primary" : ""]), { readonly: [2] });
    const markPrimary = () => wTable.set(wTable.values().map((r, i) => [r[0], r[1], i === primary ? "primary" : ""]));
    const presets = select([["", "Presets..."], ...Object.keys(d.presets).map((k) => [k, k])], "", (v) => {
      if (!v) return;
      const [waves, prim] = d.presets[v];
      primary = prim;
      wTable.set(waves.map((w, i) => [w, "1", i === prim ? "primary" : ""]));
      presets.value = "";
    });
    const wPage = el("div", { style: { display: "flex", flexDirection: "column", gap: "6px", flex: "1", minHeight: "0" } }, wTable.element,
      el("div", { class: "row" }, btn("Add Wavelength", () => wTable.add(["0.55", "1", ""])),
        btn("Remove Wavelength", () => { wTable.removeSelected(); if (primary >= wTable.values().length) primary = 0; markPrimary(); }),
        btn("Make Primary", () => { const r = wTable.selectedRow(); if (r >= 0) { primary = r; markPrimary(); } }), presets));
    // general
    const name = el("input", { type: "text", value: d.name });
    const units = select([["mm", "mm"], ["cm", "cm"], ["m", "m"], ["in", "in"]], d.units);
    const notes = el("textarea", { rows: 8 }, d.notes);
    const gPage = el("div", { class: "form" }, el("label", {}, "Lens Title"), name, el("label", {}, "Lens Units"), units, el("label", {}, "Notes"), notes);
    const t = tabs([["Aperture", apPage], ["Fields", fPage], ["Wavelengths", wPage], ["General", gPage]], tab);
    win.body.append(t.element);
    const apply = async () => {
      const data = { aperture_type: apType.value, aperture_value: apValue.value, ray_aiming: aiming.value, field_type: fieldType.value,
        fields: fTable.values(), waves: wTable.values().map((r) => [r[0], r[1]]), primary, name: name.value, units: units.value, notes: notes.value };
      try { await call("apply_system_settings", { d: data }); return true; }
      catch (e) { await message("System Explorer", esc(e.message)); return false; }
    };
    bar.append(btn("OK", async () => { if (await apply()) done(true); }, { primary: true }), btn("Apply", apply), btn("Cancel", () => done(null)));
  });
}

/** An editable table of text cells. */
export function editTable(headers, data, { readonly = [] } = {}) {
  const tbody = el("tbody");
  const table = el("table", { class: "grid" }, el("thead", {}, el("tr", {}, ...headers.map((h) => el("th", {}, h)))), tbody);
  const wrap = el("div", { class: "table-wrap" }, table);
  let sel = -1;
  const t = { element: wrap };
  const rowEl = (vals) => {
    const tr = el("tr", {});
    vals.forEach((v, c) => {
      const td = el("td", {});
      if (readonly.includes(c)) td.append(el("span", {}, v)); else td.append(el("input", { type: "text", value: v }));
      tr.append(td);
    });
    tr.addEventListener("pointerdown", () => { sel = [...tbody.children].indexOf(tr); [...tbody.children].forEach((x) => x.classList.toggle("sel", x === tr)); });
    return tr;
  };
  t.set = (rows) => { tbody.replaceChildren(...rows.map(rowEl)); sel = -1; };
  t.add = (vals) => { tbody.append(rowEl(vals)); };
  t.values = () => [...tbody.children].map((tr) => [...tr.children].map((td) => (td.querySelector("input") ? td.querySelector("input").value : td.textContent)));
  t.selectedRow = () => sel;
  t.removeSelected = () => {
    const n = tbody.children.length;
    if (n <= 1) return;
    const r = sel >= 0 ? sel : n - 1;
    tbody.children[r].remove();
    sel = -1;
  };
  t.set(data);
  return t;
}

// ================================================================== Input Rays
export async function inputRaysDialog() {
  const d = await run("input_rays");
  if (!d) return;
  const s = d.settings;
  await dialog({ title: "Input Rays", width: 680, height: 660, resizable: true }, (win, done, bar) => {
    const layoutRays = numInput(s.layout_rays, { min: 1, max: 101, step: 1 });
    const plane = select([["y", "Y-Z fan (meridional)"], ["x", "X-Z fan (sagittal)"]], s.layout_plane);
    const checks = (labels, on) => {
      const box = el("div", { class: "list", style: { maxHeight: "110px", minHeight: "40px" } });
      labels.forEach((lab, i) => box.append(el("div", {}, check(lab, on.includes(i)))));
      box.values = () => [...box.querySelectorAll("input")].map((c, i) => (c.checked ? i : -1)).filter((i) => i >= 0);
      return box;
    };
    const lf = checks(d.fields, d.layout_fields);
    const lw = checks(d.waves, d.layout_waves);
    const pattern = select(d.patterns.map((p) => [p, p[0].toUpperCase() + p.slice(1)]), s.spot_pattern);
    const rings = numInput(s.spot_rings, { min: 1, max: 100, step: 1 });
    const reference = select([["chief", "Chief ray"], ["centroid", "Centroid"]], s.spot_reference);
    const fanPoints = numInput(s.fan_points, { min: 3, max: 1001, step: 1 });
    const fpRays = numInput(s.footprint_rays, { min: 8, max: 2000, step: 1 });
    const prevSvg = el("div", { class: "pupil-preview", title: "Where the spot diagram's rays cross the entrance pupil (traced for every field and wavelength)" });
    const drawPupil = async () => {
      const p = await run("pupil_pattern", { pattern: pattern.value, n: +rings.value || 1 }, { quiet: true });
      if (!p) return;
      const R = 75, cx = 85, cy = 80, n = p.x.length, dot = Math.max(0.8, Math.min(3, 0.9 * R / Math.sqrt(Math.max(n, 1))));
      prevSvg.innerHTML = `<svg viewBox="0 0 170 190" width="170" height="190"><circle cx="${cx}" cy="${cy}" r="${R}" fill="#fff" stroke="#999"/>` +
        `<path d="M${cx - R} ${cy}h${2 * R}M${cx} ${cy - R}v${2 * R}" stroke="#bbb" stroke-dasharray="2 2"/>` +
        p.x.map((x, i) => `<circle cx="${(cx + x * R).toFixed(1)}" cy="${(cy - p.y[i] * R).toFixed(1)}" r="${dot.toFixed(2)}" fill="#1f5f99"/>`).join("") +
        `<text x="85" y="182" text-anchor="middle" font-size="12">${n} rays</text></svg>`;
    };
    pattern.addEventListener("change", drawPupil);
    rings.addEventListener("input", drawPupil);
    const users = editTable(["Hx", "Hy", "Px", "Py", "Wavelength"], s.user_rays.map((r) => [r.hx, r.hy, r.px, r.py, r.wave ?? -1].map(String)));
    const layoutBox = el("fieldset", {}, el("legend", {}, "Layout rays"), el("div", { class: "form" },
      el("label", {}, "Rays per fan"), layoutRays, el("label", {}, "Fan plane"), plane,
      el("label", {}, "Fields / wavelengths"), el("div", { class: "row", style: { alignItems: "stretch" } }, el("div", { class: "grow" }, lf), el("div", { class: "grow" }, lw))));
    const spotBox = el("fieldset", {}, el("legend", {}, "Spot diagrams, fans and footprints"), el("div", { class: "row", style: { alignItems: "flex-start" } },
      el("div", { class: "form grow" }, el("label", {}, "Spot pattern"), pattern, el("label", {}, "Rings / grid size"), rings,
        el("label", {}, "Spot reference"), reference, el("label", {}, "Fan points"), fanPoints, el("label", {}, "Footprint rays per beam"), fpRays), prevSvg));
    const userBox = el("fieldset", { style: { display: "flex", flexDirection: "column", gap: "6px", minHeight: "160px", flex: "1" } },
      el("legend", {}, "User rays (drawn on the layout, listed by Reports > User Ray Trace)"),
      el("div", { class: "note" }, "Hx, Hy: normalised field; Px, Py: normalised pupil; Wavelength: number from 0, or -1 for the primary."),
      users.element, el("div", { class: "row" }, btn("Add Ray", () => users.add(["0", "1", "0", "1", "-1"])), btn("Remove Ray", () => users.removeSelected())));
    win.body.append(layoutBox, spotBox, userBox);
    const apply = async () => {
      const userRays = users.values().filter((r) => r.some((v) => String(v).trim() !== "")).map((r) => ({ hx: +r[0] || 0, hy: +r[1] || 0, px: +r[2] || 0, py: +r[3] || 0, wave: parseInt(r[4]) || -1 }));
      const data = { ...s, layout_rays: +layoutRays.value, layout_plane: plane.value, layout_fields: lf.values(), layout_waves: lw.values(),
        spot_pattern: pattern.value, spot_rings: +rings.value, spot_reference: reference.value, fan_points: +fanPoints.value,
        footprint_rays: +fpRays.value, user_rays: userRays };
      try { await call("set_input_rays", { d: data }); return true; }
      catch (e) { await message("Input Rays", esc(e.message)); return false; }
    };
    bar.append(btn("OK", async () => { if (await apply()) done(true); }, { primary: true }), btn("Apply", apply), btn("Cancel", () => done(null)));
    drawPupil();
  });
}

// ================================================================== Open / Save As (browser storage)
async function examplesIndex() {
  try { return await (await fetch("examples/index.json")).json(); } catch (e) { return []; }
}

/** Choose a lens: from browser storage, the examples or a file. Resolves {name, text, path|null} or null.
 *  opts: {title, okLabel, allowManage} */
export function chooseLens({ title = "Open", okLabel = "Open", manage = true } = {}) {
  return dialog({ title, width: 760, height: 560, resizable: true }, async (win, done, bar) => {
    let lenses = await store.listLenses();
    let selected = null;   // {kind: "stored"|"example", name, path}
    const info = el("div", { class: "note", style: { minHeight: "2.8em" } });
    const list = el("div", { class: "list" });
    const exList = el("div", { class: "list" });
    const filter = el("input", { type: "text", placeholder: "Filter by name", class: "grow" });
    const okBtn = btn(okLabel, () => accept(), { primary: true, disabled: true });
    const describe = async (text, name) => {
      const r = await run("lens_info", { text, filename: name }, { quiet: true });
      if (!r) return;
      info.innerHTML = r.error ? `<span class="error-text">${esc(r.error)}</span>` :
        `<b>${esc(r.name || name)}</b>: ${r.surfaces} surfaces, ${esc(r.units)}` + (r.efl != null ? `, EFL ${(+r.efl).toPrecision(6)}` : "") +
        (r.fnum != null ? `, F/${(+r.fnum).toPrecision(4)}` : "") + (r.missing ? `<br><span class="error-text">${esc(r.missing)}</span>` : "");
    };
    const fillStored = () => {
      const f = filter.value.toLowerCase();
      list.replaceChildren();
      const shown = lenses.filter((l) => !f || l.name.toLowerCase().includes(f));
      if (!shown.length) list.append(el("div", { class: "muted" }, lenses.length ? "No lens matches the filter." : "No lenses are saved in this browser yet. Save one with File > Save, or import a file."));
      for (const l of shown) {
        const d = el("div", { class: selected && selected.kind === "stored" && selected.name === l.name ? "sel" : "", title: l.name },
          el("span", {}, l.name), el("span", { class: "muted", style: { float: "right", marginLeft: "20px" } }, `${fmtSize(l.size || l.text.length)}   ${fmtDate(l.saved)}`));
        d.addEventListener("click", () => { selected = { kind: "stored", name: l.name }; mark(); describe(l.text, l.name + ".lens.json"); });
        d.addEventListener("dblclick", () => { selected = { kind: "stored", name: l.name }; accept(); });
        list.append(d);
      }
    };
    let examples = null;
    const fillExamples = async () => {
      if (!examples) examples = await examplesIndex();
      const f = filter.value.toLowerCase();
      exList.replaceChildren();
      let group = null;
      for (const x of examples) {
        if (f && !(x.name + " " + x.group).toLowerCase().includes(f)) continue;
        if (x.group !== group) { group = x.group; exList.append(el("div", { class: "group" }, group)); }
        const d = el("div", { class: selected && selected.kind === "example" && selected.path === x.path ? "sel" : "", title: x.path, style: { paddingLeft: "18px" } }, x.name);
        d.addEventListener("click", async () => { selected = { kind: "example", name: x.name, path: x.path }; mark(); const t = await fetchExample(x.path); if (t) describe(t, x.path); });
        d.addEventListener("dblclick", () => { selected = { kind: "example", name: x.name, path: x.path }; accept(); });
        exList.append(d);
      }
    };
    const mark = () => {
      okBtn.disabled = !selected;
      for (const b of manageBtns) b.disabled = !(selected && selected.kind === "stored");
      fillStored();
      if (examples) fillExamples();
    };
    filter.addEventListener("input", () => { fillStored(); if (examples) fillExamples(); });
    const fetchExample = async (path) => {
      try { const r = await fetch("examples/" + path.split("/").map(encodeURIComponent).join("/")); return r.ok ? await r.text() : null; } catch (e) { return null; }
    };
    const accept = async () => {
      if (!selected) return;
      if (selected.kind === "stored") {
        const l = await store.loadLens(selected.name);
        if (l) done({ name: selected.name, text: l.text, path: selected.name, filename: selected.name + ".lens.json" });
      } else {
        const text = await fetchExample(selected.path);
        if (text) done({ name: selected.name, text, path: null, filename: selected.path.split("/").pop() });
      }
    };
    const fromDisk = btn("Import from Disk...", async () => {
      const f = await pickFile(".json,.zmx,.ZMX,.zos");
      if (f) done({ name: f.name, text: f.text, path: null, filename: f.name });
    });
    const rename = btn("Rename...", async () => {
      const n = await prompt("Rename lens", "New name:", selected.name);
      if (!n || n === selected.name) return;
      if (lenses.some((l) => l.name === n) && !(await confirmBox("Rename lens", `A lens named <b>${esc(n)}</b> already exists. Replace it?`, "Replace"))) return;
      await store.renameLens(selected.name, n);
      if (App.state.path === selected.name) await call("mark_saved", { path: n }).catch(() => {});
      store.dropRecent(selected.name);
      selected.name = n;
      lenses = await store.listLenses();
      mark();
    }, { disabled: true });
    const del = btn("Delete...", async () => {
      if (!(await confirmBox("Delete lens", `Delete <b>${esc(selected.name)}</b> from this browser? This cannot be undone.`, "Delete"))) return;
      await store.deleteLens(selected.name);
      store.dropRecent(selected.name);
      selected = null;
      lenses = await store.listLenses();
      info.textContent = "";
      mark();
    }, { disabled: true });
    const exp = btn("Export...", async () => {
      const l = await store.loadLens(selected.name);
      if (l) download(safeFile(selected.name) + ".lens.json", l.text);
    }, { disabled: true, title: "Download this lens as a .lens.json file" });
    const manageBtns = manage ? [rename, del, exp] : [];
    const t = tabs([["Saved in this browser", list], ["Examples", exList]], 0, (i) => { if (i === 1) fillExamples(); });
    win.body.append(el("div", { class: "row" }, filter), t.element, info);
    if (manage) bar.append(el("div", { class: "left" }, rename, del, exp));
    bar.append(fromDisk, btn("Cancel", () => done(null)), okBtn);
    fillStored();
    filter.focus();
  });
}

export const safeFile = (name) => String(name || "lens").replace(/[\\/:*?"<>|]+/g, "_").replace(/\.lens\.json$|\.json$/i, "");

/** Ask for a name to save under (browser storage). Resolves the name or null. */
export async function saveAsDialog(suggested) {
  const lenses = await store.listLenses();
  return dialog({ title: "Save As", width: 480, height: 420, resizable: true }, (win, done, bar) => {
    const input = el("input", { type: "text", value: suggested || "", autofocus: true });
    const list = el("div", { class: "list" });
    for (const l of lenses) {
      const d = el("div", {}, l.name);
      d.addEventListener("click", () => { input.value = l.name; });
      d.addEventListener("dblclick", () => { input.value = l.name; ok(); });
      list.append(d);
    }
    if (!lenses.length) list.append(el("div", { class: "muted" }, "(no lenses saved in this browser yet)"));
    const ok = async () => {
      const n = input.value.trim().replace(/\.lens\.json$|\.json$/i, "");
      if (!n) return;
      if (lenses.some((l) => l.name === n) && !(await confirmBox("Save As", `<b>${esc(n)}</b> already exists in this browser. Replace it?`, "Replace"))) return;
      done(n);
    };
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); ok(); } });
    win.body.append(el("label", {}, "Name:"), input, el("div", { class: "muted" }, "Lenses saved in this browser:"), list,
      el("div", { class: "note" }, "The lens is stored in this browser (IndexedDB). File > Export to Disk downloads a copy."));
    bar.append(btn("Cancel", () => done(null)), btn("Save", ok, { primary: true }));
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

// ================================================================== Insert Lens
export async function insertLensDialog(at) {
  const src = await chooseLens({ title: "Insert Lens: choose the lens to insert", okLabel: "Choose", manage: false });
  if (!src) return;
  const ima = App.state.image_index;
  await dialog({ title: "Insert Lens", width: 760, height: 620, resizable: true }, (win, done, bar) => {
    const first = numInput(1, { min: 1, step: 1 }), last = numInput(1, { min: 1, step: 1 });
    const where = numInput(Math.max(1, Math.min(at ?? ima, ima)), { min: 1, max: ima, step: 1 });
    where.title = "The inserted surfaces go in front of this surface of the current lens";
    const scale = numInput(1, { min: 1e-6, max: 1e6, step: 0.1 });
    scale.title = "Every length (radii, thicknesses, semi-diameters, aspheric terms) is multiplied";
    const reverse = check("Reverse the surface order (turn the lens round)", false);
    const keepStop = check("Use the inserted lens's stop surface as the system stop", false);
    const units = check("Convert units to the current lens's units", true);
    const copySd = check("Copy semi-diameters from the inserted lens", false, null,
      "Checked: each surface keeps the semi-diameter it has in the lens file (automatic ones are computed there), as a fixed value, scaled.\nUnchecked: the inserted surfaces get automatic semi-diameters.");
    const preview = el("pre", { class: "mono", style: { flex: "1", border: "1px solid var(--border)", padding: "6px", minHeight: "120px" } });
    const info = el("div", {});
    const okBtn = btn("Insert", () => insert(), { primary: true });
    let n = 1;
    const opts = () => ({ first: +first.value, last: Math.max(+first.value, +last.value), scale: +scale.value || 1, reverse: reverse.input.checked,
      keep_stop: keepStop.input.checked, convert_units: units.input.checked, copy_semi_diameters: copySd.input.checked });
    let token = 0, initialised = false;
    const update = async () => {
      const my = ++token;
      const r = await run("insert_preview", { text: src.text, filename: src.filename, opts: opts() }, { quiet: true });
      if (my !== token || !r) return;
      if (r.error) { preview.textContent = ""; info.innerHTML = `<span class="error-text">${esc(r.error)}</span>`; okBtn.disabled = true; return; }
      n = r.n;
      first.max = last.max = n;
      if (!initialised) { initialised = true; last.value = n; update(); return; }
      preview.textContent = r.preview || "";
      info.textContent = r.info || "";
      okBtn.disabled = !r.ok;
    };
    [first, last, where, scale].forEach((i) => i.addEventListener("input", update));
    [reverse, keepStop, units, copySd].forEach((c) => c.input.addEventListener("change", update));
    const insert = async () => {
      try { await call("insert_lens", { text: src.text, filename: src.filename, at: +where.value, opts: opts() }); done(true); }
      catch (e) { info.innerHTML = `<span class="error-text">Cannot insert: ${esc(e.message)}</span>`; }
    };
    win.body.append(el("div", { class: "form" }, el("label", {}, "File:"), el("b", {}, src.name),
      el("label", {}, "Surfaces:"), el("div", { class: "row" }, first, "to", last),
      el("label", {}, "Insert before surface:"), where, el("label", {}, "Scale factor:"), scale,
      el("span"), reverse, el("span"), keepStop, el("span"), units, el("span"), copySd),
      el("div", {}, "Surfaces to insert (scaled and in the order they will be inserted):"), preview, info);
    bar.append(btn("Cancel", () => done(null)), okBtn);
    update();
  });
}

// ================================================================== Inspect Lens File
export async function inspectLens(openInEditor) {
  const src = await chooseLens({ title: "Inspect Lens File", okLabel: "Inspect", manage: false });
  if (!src) return;
  const head = el("div", { html: `<b>${esc(src.name)}</b>` });
  const text = el("pre", { class: "mono", style: { flex: "1", border: "1px solid var(--border)", padding: "6px" } }, "Computing system report...");
  const buttons = el("div", { class: "win-buttons" });
  const w = openWindow({ title: `Inspect: ${src.name}`, width: 860, height: 620, resizable: true, buttons });
  w.body.append(head, text);
  buttons.append(btn("Copy", async () => status((await copyText(text.textContent)) ? "Report copied" : "Copy failed")),
    btn("Save...", () => download(safeFile(src.name) + "_report.txt", text.textContent, "text/plain")),
    btn("Open in Editor", () => { w.close(); openInEditor(src); }), btn("Close", () => w.close(), { primary: true }));
  const r = await run("inspect", { text: src.text, filename: src.filename }, { priority: 0 });
  if (!r) { text.textContent = "The system report failed."; return; }
  if (r.error) { text.textContent = r.error; return; }
  head.innerHTML = `<b>${esc(src.name)}</b><br>${esc(r.info)}`;
  text.textContent = r.report;
}

// ================================================================== Help-menu dialogs
export async function about() {
  const i = App.info || {};
  await message("About LensForge", `<div class="row" style="align-items:flex-start;gap:16px"><img src="${svgURL(i.icon || "")}" width="72" height="72" alt="">` +
    `<div><b>LensForge ${esc(i.version || "")}</b> (lensforge)<br>Sequential optical design: lens data editor, analyses, optimisation and tolerancing.` +
    `<br><br>Web front end over the lensforge Python API, running in this browser with Pyodide (Python ${esc(i.python || "")}, NumPy ${esc(i.numpy || "")}, matplotlib). ` +
    `Lens files are kept in this browser's storage.<br><br>MIT License.</div></div>`, { width: 540 });
}

export async function shortcutsHelp() {
  const rows = [];
  for (const [id, c] of Object.entries(App.menus.commands)) if (c.shortcut) rows.push([c.path[0], c.path.slice(1).join(" > "), c.shortcut]);
  const extra = "<p>In the Lens Data Editor, right-click a cell for variables, solves, surface type and stop; the ... button in a " +
    "Material cell opens the material picker; type into a cell to replace it, Enter or F2 edits it, Delete clears a comment or " +
    "semi-diameter. In the Python Shell, Ctrl+Enter runs the script. On a Mac, Cmd works wherever Ctrl is shown.</p>" +
    "<p>A few shortcuts the browser keeps for itself use Alt instead of Ctrl: New (Alt+N), Wavefront Map (Alt+W), Tolerancing " +
    "(Alt+Shift+T), Non-Sequential Editor (Alt+Shift+N), Delete Surfaces (Alt+Shift+Del), Surface Properties (Alt+Shift+P), " +
    "Inspect Lens File (Alt+Shift+O).</p>";
  await message("Keyboard Shortcuts", `<div style="max-height:60vh;overflow:auto"><table class="grid"><tr><th>Menu</th><th>Command</th><th>Keys</th></tr>` +
    rows.map(([m, c, k]) => `<tr><td>${esc(m)}</td><td>${esc(c)}</td><td><b>${esc(k)}</b></td></tr>`).join("") + `</table></div>${extra}`, { width: 640 });
}
