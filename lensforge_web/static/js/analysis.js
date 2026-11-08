// Analysis windows: one dock panel per analysis (plot or text), recomputed when the lens changes
// (as lensforge_qt/analysis_window.py). They tab together in the right dock and can float.
import { App, run, status, onState, docks, cmd } from "./core.js";
import * as engine from "./engine.js";
const { PRIORITY } = engine;
import { el, btn, check, download, downloadDataURL, copyText, popupMenu } from "./ui.js";

export const windows = [];
let ids = 0;

export function openAnalysis(key, { settings, newWindow = false } = {}) {
  if (!newWindow && !settings) {
    for (let i = windows.length - 1; i >= 0; i--) {
      if (windows[i].spec.key === key) { windows[i].show(); return windows[i]; }
    }
  }
  const w = new AnalysisWindow(key, settings);
  windows.push(w);
  return w;
}

export function closeAll() { for (const w of windows.slice()) w.close(); }
export function closeOthers(keep) { for (const w of windows.slice()) if (w !== keep) w.close(); }

/** Right-click menu of an analysis tab (or the dock's title bar). */
function tabMenu(w, e) {
  const icon = (id) => (App.menus.commands[id] || {}).icon;
  const many = windows.length > 1;
  popupMenu([
    { label: "Close", action: () => w.close() },
    { label: "Close Other Analysis Windows", disabled: !many, action: () => closeOthers(w) },
    { label: "Close All Analysis Windows", icon: icon("Analysis > Close All Analysis Windows"), action: closeAll },
    null,
    { label: "Tab All Analysis Windows", icon: icon("Analysis > Tab All Analysis Windows"), action: tabAll },
  ], e.clientX, e.clientY);
}
export function tabAll() { for (const w of windows) if (w.panel.floating) docks.right.dock(w.panel); }

onState((s, old) => {
  for (const w of windows) w.lensChanged(s, old);
});

class AnalysisWindow {
  constructor(key, values) {
    this.spec = App.specs[key];
    this.id = "an" + ++ids;
    this.values = {};
    for (const st of this.spec.settings) this.values[st.name] = values && st.name in values ? values[st.name] : st.default;
    this.config = (values && values.config) || 0;
    this.busy = false;
    this.pending = false;
    this.stale = true;
    this.lastRevision = -1;
    this.result = null;

    this.configLabel = el("label", {}, "Config");
    this.configSel = el("select", { title: "Configuration to analyse: Current follows the configuration shown in the Lens Data Editor; a number keeps this window on that configuration" });
    this.configLabel.append(this.configSel);
    this.configSel.addEventListener("change", () => { this.config = +this.configSel.value; this.request(); });
    this.bar = el("div", { class: "an-bar" }, this.configLabel);
    this.widgets = {};
    for (const st of this.spec.settings) this.bar.append(this.makeSetting(st));
    if (this.spec.uses_rays) this.bar.append(btn("Input Rays...", () => cmd("File > Input Rays"), { small: true, title: "Ray sampling and user rays (File > Input Rays)" }));
    this.auto = check("Auto", true, (on) => { if (on && this.stale) this.request(); }, "Recompute whenever the lens changes");
    this.bar.append(el("span", { class: "grow" }), this.auto, btn("Update", () => this.request(true), { small: true, title: "Recompute now" }));

    this.body = el("div", { class: "an-body" });
    this.busyBadge = el("div", { class: "an-busy", hidden: true }, "computing...");
    this.body.append(this.busyBadge);
    this.errorLine = el("div", { class: "an-error", hidden: true });
    this.foot = el("div", { class: "an-foot" });
    if (this.spec.text) {
      this.pre = el("pre", { class: "mono" });
      this.body.prepend(this.pre);
      this.foot.append(btn("Copy", async () => status((await copyText(this.pre.textContent)) ? "Copied" : "Copy failed"), { small: true }),
        btn("Save...", () => download(`${this.spec.key}.txt`, this.pre.textContent, "text/plain"), { small: true }));
    } else {
      this.img = el("img", { alt: this.spec.title });
      this.body.prepend(this.img);
      this.foot.append(btn("Save Image...", () => this.img.src && downloadDataURL(`${this.spec.key}.png`, this.img.src), { small: true, title: "Download the plot as a PNG image" }),
        btn("Open in New Tab", () => { if (this.img.src) { const w = window.open(); if (w) w.document.write(`<title>${this.spec.title}</title><img src="${this.img.src}" style="max-width:100%">`); } }, { small: true }));
    }
    this.element = el("div", { class: "pane" }, this.bar, this.body, this.errorLine, this.foot);
    this.panel = docks.right.add({ id: this.id, title: this.spec.title, element: this.element, helpId: this.spec.id,
      onshow: () => { if (this.stale || this.sizeChanged()) this.request(); },
      onclose: () => { const i = windows.indexOf(this); if (i >= 0) windows.splice(i, 1); },
      onresize: () => this.resized(), contextMenu: (e) => tabMenu(this, e) }, { show: false });
    // re-render when the plot area changes size for any reason (window resize, splitters, a bottom
    // dock opening, floating): the PNG is drawn for the exact size it is shown at
    new ResizeObserver(() => this.resized()).observe(this.body);
    this.fillConfigs();
    docks.right.show(this.panel);  // onshow computes the first plot
  }

  makeSetting(st) {
    const s = App.state;
    let w;
    if (["field", "field_all", "wave", "wave_all", "config_all"].includes(st.kind)) {
      w = el("select");
      this.fillChoice(st, w);
      w.addEventListener("change", () => { this.values[st.name] = +w.value; this.request(); });
    } else if (st.kind === "surface" || st.kind === "int") {
      w = el("input", { type: "number", step: 1, min: st.kind === "surface" ? 0 : st.min, max: st.kind === "surface" ? s.image_index : st.max, value: this.values[st.name] });
      w.addEventListener("change", () => { this.values[st.name] = Math.round(+w.value); this.request(); });
    } else if (st.kind === "float") {
      w = el("input", { type: "number", step: "any", min: st.min, max: st.max, value: this.values[st.name] });
      w.addEventListener("change", () => { this.values[st.name] = +w.value; this.request(); });
    } else if (st.kind === "choice") {
      w = el("select", {}, ...st.choices.map(([lab, v]) => el("option", { value: JSON.stringify(v) }, lab)));
      w.value = JSON.stringify(this.values[st.name]);
      w.addEventListener("change", () => { this.values[st.name] = JSON.parse(w.value); this.request(); });
    } else if (st.kind === "bool") {
      const c = check(st.label, this.values[st.name], (on) => { this.values[st.name] = on; this.request(); });
      this.widgets[st.name] = c.input;
      return c;
    }
    this.widgets[st.name] = w;
    return el("label", {}, st.label, w);
  }

  fillChoice(st, w) {
    const s = App.state;
    const opts = [];
    if (["field_all", "wave_all", "wave", "config_all"].includes(st.kind)) opts.push([-1, st.kind === "wave" ? "Primary" : "All"]);
    if (st.kind === "config_all") for (const [k, name] of s.configs) opts.push([k, name]);
    else if (st.kind.startsWith("field")) s.fields.forEach((f, k) => opts.push([k, f]));
    else s.waves.forEach((f, k) => opts.push([k, f]));
    let v = this.values[st.name];
    if (!opts.some(([k]) => k === v)) v = opts[0][0];
    this.values[st.name] = v;
    w.replaceChildren(...opts.map(([k, lab]) => el("option", { value: String(k) }, lab)));
    w.value = String(v);
  }

  syncChoices() {
    for (const st of this.spec.settings) {
      const w = this.widgets[st.name];
      if (["field", "field_all", "wave", "wave_all", "config_all"].includes(st.kind)) this.fillChoice(st, w);
      else if (st.kind === "surface") w.max = App.state.image_index;
    }
  }

  fillConfigs() {
    const s = App.state;
    const opts = [[0, "Current"], ...s.configs];
    if (!opts.some(([k]) => k === this.config)) this.config = 0;
    this.configSel.replaceChildren(...opts.map(([k, lab]) => el("option", { value: String(k) }, lab)));
    this.configSel.value = String(this.config);
    const many = s.configs.length > 1 && this.spec.key !== "mc_layout";
    this.configLabel.hidden = !many;
  }

  title() {
    const s = App.state;
    if (s.configs.length < 2 || this.configLabel.hidden) return this.spec.title;
    const k = this.config || s.current_config;
    const c = s.configs.find(([n]) => n === k);
    return c ? `${this.spec.title} [${c[1]}]` : this.spec.title;
  }

  setTitle(extra = "") { docks.right.setTitle(this.panel, this.title() + extra); }

  lensChanged(s, old) {
    if (old && s.revision === old.revision) return;
    this.fillConfigs();
    this.syncChoices();
    this.stale = true;
    if (this.auto.input.checked) this.request();
  }

  visible() {
    if (this.panel.floating) return true;
    return docks.right.active === this.panel && !docks.right.root.hidden;
  }

  size() {
    const r = this.body.getBoundingClientRect();
    return [Math.max(200, Math.round(r.width)), Math.max(150, Math.round(r.height))];
  }

  sizeChanged() {
    if (!this.renderedSize || this.spec.text) return false;
    const [w, h] = this.size();
    return Math.abs(w - this.renderedSize[0]) > 8 || Math.abs(h - this.renderedSize[1]) > 8;
  }

  resized() {
    clearTimeout(this.resizeTimer);
    this.resizeTimer = setTimeout(() => { if (this.visible() && this.sizeChanged()) this.request(true); }, 250);
  }

  /** Recompute (hidden tabs wait until they are shown, as nobody can see them). */
  request(force = false) {
    if (!this.visible() && !force) { this.stale = true; return; }
    if (this.busy) { this.pending = true; return; }
    this.compute();
  }

  async compute() {
    this.busy = true;
    this.stale = false;
    this.busyBadge.hidden = false;
    this.setTitle("  (computing...)");
    const [w, h] = this.size();
    const rev = App.state.revision;
    const out = await engine.callRaw("run_analysis", { key: this.spec.key, opts: this.values, config: this.config,
      width: w, height: h, dpr: Math.min(2, window.devicePixelRatio || 1) }, { priority: PRIORITY.background, key: "analysis:" + this.id });
    this.busy = false;
    this.busyBadge.hidden = true;
    if (out.superseded) return;
    if (this.panel.area.panels.indexOf(this.panel) < 0) return;  // closed meanwhile
    const r = out.error ? { error: out.error } : out.result;
    this.result = r;
    this.renderedSize = [w, h];  // also after an error, so a size check never loops
    if (r.error) this.showError(r.error);
    else {
      this.errorLine.hidden = true;
      if (this.pre) this.pre.textContent = r.text;
      else this.img.src = "data:image/png;base64," + r.png;
      this.setTitle();
    }
    this.updates = (this.updates || 0) + 1;
    // the plot area may have changed size while this ran (a dock opened): draw it again at the new size
    if (this.pending || this.sizeChanged() || rev !== App.state.revision && this.auto.input.checked) { this.pending = false; this.request(); }
  }

  showError(msg) {
    // never leave the previous lens's plot or report on screen under an error
    if (this.pre) this.pre.textContent = "";
    else this.img.removeAttribute("src");
    this.errorLine.textContent = msg;
    this.errorLine.hidden = false;
    this.setTitle("  (error)");
  }

  show() { docks.right.show(this.panel); }
  close() { docks.right.remove(this.panel); }
}
