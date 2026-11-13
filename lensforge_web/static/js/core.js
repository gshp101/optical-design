// The application object shared by every module: lens state, commands, status bar and dock areas.
import * as engine from "./engine.js";
import { el, openWindow, dragSplitter, popOut, popupBlocked, allDocuments, POPOUT_GLYPH, POPOUT_TIP } from "./ui.js";

export const App = {
  state: null,            // Session.state() from Python
  menus: null,            // menus.menu_data()
  specs: null,            // analysis registry
  info: null,             // versions
  commands: {},           // command id -> function
  stateListeners: [],
  focusScope: null,       // "lde" | "mfe" | "mce" | "shell" | null (where local shortcuts go)
};

// ------------------------------------------------------------------ status bar
let statusTimer = null;
// the main tab's status line, and the one of every pop-out tab (so an editor there shows its errors too)
const statusLines = () => allDocuments().map((d) => d.getElementById("status-msg")).filter(Boolean);
export function status(msg, ms = 5000) {
  for (const s of statusLines()) {
    s.textContent = msg || "";
    s.title = msg || "";
    s.classList.remove("error-text");
  }
  clearTimeout(statusTimer);
  if (ms && msg) statusTimer = setTimeout(() => { for (const s of statusLines()) s.textContent = ""; }, ms);
}
export function statusError(msg, ms = 8000) {
  status(msg, ms);
  for (const s of statusLines()) s.classList.add("error-text");
}

// ------------------------------------------------------------------ talking to Python
/** Run a Session method; errors go to the status bar (returns undefined then). */
export async function run(method, args = {}, opts = {}) {
  try {
    return await engine.call(method, args, opts);
  } catch (e) {
    if (!opts.quiet) statusError(e.message);
    if (opts.throws) throw e;
    return undefined;
  }
}
export const call = engine.call;

export function onState(fn) { App.stateListeners.push(fn); }
export function setState(s) {
  const old = App.state;
  App.state = s;
  for (const fn of App.stateListeners) {
    try { fn(s, old); } catch (e) { console.error(e); }
  }
}
engine.on("state", setState);

export function cmd(id) {
  const fn = id.startsWith("__help:") ? () => App.onHelp && App.onHelp(id.slice(7)) : App.commands[id];
  if (!fn) { statusError(`No command ${id}`); return; }
  try {
    const r = fn();
    if (r && r.catch) r.catch((e) => { console.error(e); statusError(String(e.message || e)); });
  } catch (e) { console.error(e); statusError(String(e.message || e)); }
}

// ------------------------------------------------------------------ dock areas (like QDockWidget areas)
export class DockArea {
  constructor(id, splitterId, orientation) {
    this.root = document.getElementById(id);
    this.splitter = splitterId ? document.getElementById(splitterId) : null;
    this.orientation = orientation;   // "right" | "left" | "bottom"
    this.panels = [];
    this.active = null;
    this.titleBar = el("div", { class: "dock-title" });
    this.body = el("div", { class: "dock-body" });
    this.tabBar = el("div", { class: "dock-tabs" });
    this.box = el("div", { class: "dock-panel" }, this.titleBar, this.body, this.tabBar);
    this.root.append(this.box);
    if (this.splitter) {
      const horizontal = orientation === "bottom";
      dragSplitter(this.splitter, () => (horizontal ? this.root.offsetHeight : this.root.offsetWidth), (start, dx, dy) => {
        if (horizontal) this.root.style.height = Math.max(80, start - dy) + "px";
        else this.root.style.width = Math.max(160, orientation === "right" ? start - dx : start + dx) + "px";
      }, () => {
        // keep the size the layout actually gave the dock (it stops where the Lens Data Editor reaches its
        // minimum), so a drag past that limit does not leave a size the next drag must first undo
        if (horizontal) this.root.style.height = this.root.offsetHeight + "px";
        else this.root.style.width = this.root.offsetWidth + "px";
        this.resized();
      });
    }
  }

  /** panel: {id, title, element, closable=true, floatable=true, onshow(), onclose(), onresize(), helpId} */
  add(panel, { show = true } = {}) {
    panel.area = this;
    panel.floating = null;
    this.panels.push(panel);
    if (show) this.show(panel);
    else this.render();
    return panel;
  }

  has(id) { return this.panels.find((p) => p.id === id) || null; }

  show(panel) {
    if (panel.floating) {
      panel.floating.raise();
      if (panel.floating.popout) status(`${panel.title} is open in its own browser tab`);
      return;
    }
    this.active = panel;
    this.render();
    if (panel.onshow) panel.onshow();
  }

  remove(panel) {
    const i = this.panels.indexOf(panel);
    if (i < 0) return;
    this.panels.splice(i, 1);
    if (panel.floating) {
      const f = panel.floating;
      panel.floating = null;
      f.close();
      if (f.popout && panel.onpop) panel.onpop(false);
    }
    // take its contents off the page: a closed panel left in the dock body stays visible under the next
    // panel opened there (a reopened analysis showed the old plot with the new one stacked below it)
    panel.element.remove();
    if (this.active === panel) this.active = this.docked()[Math.max(0, i - 1)] || null;
    this.render();
    if (panel.onclose) panel.onclose();
  }

  docked() { return this.panels.filter((p) => !p.floating); }

  float(panel) {
    if (panel.floating) return;
    const r = panel.element.getBoundingClientRect();
    const w = openWindow({ title: panel.title, width: Math.max(420, r.width), height: Math.max(300, r.height + 30),
      flush: true, resizable: true,
      extraTitle: el("span", { class: "win-extra" },
        el("button", { type: "button", title: "Dock (put it back in the window)", onclick: () => this.dock(panel) }, "⧉"),
        panel.popout !== false ? el("button", { type: "button", class: "pop-btn", title: POPOUT_TIP, "aria-label": "Open in New Tab", onclick: () => this.popOut(panel) }, POPOUT_GLYPH) : null),
      onclose: () => { if (panel.floating) { panel.floating = null; this.remove(panel); } } });
    w.body.append(panel.element);
    panel.floating = w;
    if (this.active === panel) this.active = this.docked()[0] || null;
    this.render();
    new ResizeObserver(() => panel.onresize && panel.onresize()).observe(w.body);
    if (panel.onshow) panel.onshow();
  }

  /** Move the panel into its own browser tab (Open in New Tab); closing that tab docks it again. */
  popOut(panel) {
    if (panel.floating && panel.floating.popout) { panel.floating.raise(); return panel.floating; }
    if (panel.floating) { const f = panel.floating; panel.floating = null; f.close(); }
    const h = popOut(panel.element, { name: panel.id, title: panel.title,
      help: panel.helpId ? () => cmd("__help:" + panel.helpId) : null,
      onresize: () => panel.onresize && panel.onresize(),
      onreturn: () => {
        if (panel.floating !== h) return;
        panel.floating = null;
        if (!this.panels.includes(panel)) return;
        this.active = panel;
        this.render();
        if (panel.onshow) panel.onshow();
        if (panel.onpop) panel.onpop(false);
      } });
    if (!h) { this.render(); popupBlocked(); return null; }
    panel.floating = h;
    if (this.active === panel) this.active = this.docked()[0] || null;
    this.render();
    if (panel.onpop) panel.onpop(true);
    return h;
  }

  /** Back into the dock from a floating window or a pop-out tab. */
  dock(panel) {
    if (!panel.floating) return;
    const w = panel.floating;
    panel.floating = null;
    w.close();
    this.active = panel;
    this.render();
    if (panel.onshow) panel.onshow();
    if (w.popout && panel.onpop) panel.onpop(false);
  }

  setTitle(panel, title) {
    panel.title = title;
    if (panel.floating) panel.floating.setTitle(title);
    this.render(false);
  }

  render(refill = true) {
    const docked = this.docked();
    const visible = docked.length > 0;
    this.root.hidden = !visible;
    if (this.splitter) this.splitter.hidden = !visible;
    if (!visible) {
      this.active = null;
      this.titleBar.replaceChildren();
      this.tabBar.replaceChildren();
      for (const c of [...this.body.children]) c.remove();
      return;
    }
    if (!this.active || this.active.floating || !docked.includes(this.active)) this.active = docked[0];
    const a = this.active;
    this.titleBar.replaceChildren(el("span", { class: "dt-text", title: a.title }, a.title));
    this.titleBar.oncontextmenu = a.contextMenu ? (e) => { e.preventDefault(); a.contextMenu(e); } : null;
    if (a.helpId) this.titleBar.append(el("button", { type: "button", title: "Help", onclick: () => cmd("__help:" + a.helpId) }, "?"));
    if (a.floatable !== false) this.titleBar.append(el("button", { type: "button", title: "Float (own window)", onclick: () => this.float(a) }, "⧉"));
    if (a.popout !== false) this.titleBar.append(el("button", { type: "button", class: "pop-btn", title: POPOUT_TIP, "aria-label": "Open in New Tab", onclick: () => this.popOut(a) }, POPOUT_GLYPH));
    if (a.closable !== false) this.titleBar.append(el("button", { type: "button", title: "Close", onclick: () => this.remove(a) }, "×"));
    if (refill) {
      // only the docked panels' contents belong in the body (anything else is left over from a closed panel)
      for (const c of [...this.body.children]) if (!docked.some((p) => p.element === c)) c.remove();
      for (const p of docked) {
        if (p.element.parentNode !== this.body) this.body.append(p.element);
        p.element.hidden = p !== a;
      }
    }
    this.tabBar.hidden = docked.length < 2;
    this.tabBar.replaceChildren(...docked.map((p) => el("div", { class: "dock-tab" + (p === a ? " active" : ""), title: p.title,
      onclick: () => this.show(p), oncontextmenu: p.contextMenu ? (e) => { e.preventDefault(); p.contextMenu(e); } : null }, el("span", {}, p.title),
      p.closable !== false ? el("button", { type: "button", title: "Close", onclick: (e) => { e.stopPropagation(); this.remove(p); } }, "×") : null)));
  }

  resized() { for (const p of this.panels) if (p.onresize && !p.floating) p.onresize(); }
}

export const docks = {};
export function initDocks() {
  docks.right = new DockArea("right-dock", "split-right", "right");
  docks.bottom = new DockArea("bottom-dock", "split-bottom", "bottom");
  docks.left = new DockArea("left-dock", "split-left", "left");
  window.addEventListener("resize", () => { for (const d of Object.values(docks)) d.resized(); });
}
