// Small DOM toolkit: elements, windows (floating and modal), popup menus, files.

export function el(tag, attrs = {}, ...children) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === undefined || v === null || v === false) continue;
    if (k === "class") e.className = v;
    else if (k === "style" && typeof v === "object") Object.assign(e.style, v);
    else if (k.startsWith("on") && typeof v === "function") e.addEventListener(k.slice(2), v);
    else if (k === "html") e.innerHTML = v;
    else if (k === "text") e.textContent = v;
    else if (k in e && typeof v !== "string") e[k] = v;
    else e.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat()) {
    if (c === null || c === undefined || c === false) continue;
    e.append(c instanceof Node ? c : document.createTextNode(String(c)));
  }
  return e;
}

export const $ = (sel, root = document) => root.querySelector(sel);
export const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
export const svgURL = (svg) => "data:image/svg+xml;charset=utf-8," + encodeURIComponent(svg);
export const iconImg = (svg, size = 16) => svg ? el("img", { src: svgURL(svg), width: size, height: size, alt: "" }) : null;

export function btn(text, onclick, attrs = {}) {
  return el("button", { class: "btn" + (attrs.primary ? " primary" : "") + (attrs.small ? " small" : ""), type: "button",
    onclick, title: attrs.title, disabled: attrs.disabled }, text);
}

export function select(options, value, onchange, attrs = {}) {
  // options: [[value, label], ...]
  const s = el("select", attrs);
  for (const [v, lab] of options) s.append(el("option", { value: String(v) }, lab));
  if (value !== undefined && value !== null) s.value = String(value);
  if (onchange) s.addEventListener("change", () => onchange(s.value));
  return s;
}

export function numInput(value, { min, max, step, width, onchange } = {}) {
  const i = el("input", { type: "number", value: String(value), min, max, step: step ?? "any" });
  if (width) i.style.width = width;
  if (onchange) i.addEventListener("change", () => onchange(i.value));
  return i;
}

export function check(label, checked, onchange, title) {
  const i = el("input", { type: "checkbox", checked: !!checked });
  if (onchange) i.addEventListener("change", () => onchange(i.checked));
  const l = el("label", { class: "check", title }, i, label);
  l.input = i;
  return l;
}

export function tabs(pages, active = 0, onchange) {
  // pages: [[title, element], ...] -> {element, select(i), index}
  const bar = el("div", { class: "tabs" });
  const wrap = el("div", { style: { display: "flex", flexDirection: "column", flex: "1", minHeight: "0" } }, bar);
  const t = { element: wrap, index: active, tabs: [], pages: [] };
  pages.forEach(([title, page], i) => {
    const tab = el("div", { class: "tab", onclick: () => t.select(i) }, title);
    const p = el("div", { class: "tab-page" }, page);
    bar.append(tab);
    wrap.append(p);
    t.tabs.push(tab);
    t.pages.push(p);
  });
  t.select = (i) => {
    t.index = i;
    t.tabs.forEach((x, k) => x.classList.toggle("active", k === i));
    t.pages.forEach((x, k) => x.classList.toggle("active", k === i));
    if (onchange) onchange(i);
  };
  t.select(active);
  return t;
}

// ------------------------------------------------------------------ windows
let zTop = 10;
const modalStack = [];
const openWindows = new Set();

// ------------------------------------------------------------------ documents (the page and its pop-out tabs)
// An editor moved to its own browser tab (popOut) is still run by this page: its elements, listeners and
// state stay here and only the drawing moves. Windows and popup menus open in the document the user last
// touched ("host"), so a context menu or dialog of a popped-out editor appears in its tab.
const documents = new Set([document]);
const newDocumentHooks = [];
let hostDoc = document;
export function host() {
  if (!documents.has(hostDoc) || !hostDoc.defaultView || hostDoc.defaultView.closed) hostDoc = document;
  return hostDoc;
}
export const allDocuments = () => [...documents];
/** fn(doc) runs for every pop-out tab's document when it opens (the page's own document is not included). */
export function onNewDocument(fn) { newDocumentHooks.push(fn); }
/** setTimeout in the window an element is shown in: a hidden tab's timers are throttled by the browser. */
export function later(node, fn, ms) {
  const v = (node && node.ownerDocument && node.ownerDocument.defaultView) || window;
  return v.setTimeout(fn, ms);
}
function trackDocument(doc) {
  documents.add(doc);
  for (const type of ["pointerdown", "keydown", "focusin"]) doc.addEventListener(type, () => { hostDoc = doc; }, true);
  doc.addEventListener("pointerdown", closePopupsOutside);
  for (const fn of newDocumentHooks) { try { fn(doc); } catch (e) { console.error(e); } }
}
function untrackDocument(doc) {
  documents.delete(doc);
  if (hostDoc === doc) hostDoc = document;
  // windows, dialogs and menus that were open in the closed tab go with it (an orphaned modal would block the keyboard)
  for (const w of [...openWindows]) if (w.element.ownerDocument === doc) w.close();
  openPopups = openPopups.filter((p) => p.ownerDocument !== doc);
}

function placeWindow(w, width, height) {
  const d = w.ownerDocument, v = d.defaultView;
  const vw = v.innerWidth, vh = v.innerHeight;
  const W = Math.min(width, vw - 20), H = Math.min(height, vh - 20);
  const n = d.querySelectorAll("#floating-layer .window").length;
  w.style.width = W + "px";
  if (height) w.style.height = H + "px";
  w.style.left = Math.max(10, (vw - W) / 2 + (n % 6) * 24) + "px";
  w.style.top = Math.max(10, (vh - (height ? H : 400)) / 3 + (n % 6) * 24) + "px";
}

function makeDraggable(w, handle) {
  handle.addEventListener("pointerdown", (e) => {
    if (e.target.closest("button")) return;
    const r = w.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    const v = w.ownerDocument.defaultView;
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      w.style.left = Math.max(-r.width + 80, Math.min(v.innerWidth - 80, ev.clientX - dx)) + "px";
      w.style.top = Math.max(0, Math.min(v.innerHeight - 30, ev.clientY - dy)) + "px";
    };
    const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

/** A window. opts: {title, width, height, modal, resizable, buttons: el, onclose, className, flush, help,
 *  popout: name (adds a button that moves the window's contents to its own browser tab)}
 *  returns {element, body, close(), setTitle(), raise(), popOut(), popped} */
export function openWindow(opts) {
  const layer = host().getElementById(opts.modal ? "modal-layer" : "floating-layer");
  const titleText = el("span", { class: "wt-text" }, opts.title || "");
  const close = el("button", { type: "button", title: "Close", "aria-label": "Close" }, "×");
  const title = el("div", { class: "win-title" }, opts.icon ? iconImg(opts.icon, 16) : null, titleText);
  if (opts.help) title.append(el("button", { type: "button", title: "Help on this window (F1)", onclick: opts.help }, "?"));
  if (opts.extraTitle) title.append(opts.extraTitle);
  const popBtn = opts.popout ? el("button", { type: "button", class: "pop-btn", title: POPOUT_TIP, "aria-label": "Open in New Tab" }, POPOUT_GLYPH) : null;
  if (popBtn) title.append(popBtn);
  title.append(close);
  const body = el("div", { class: "win-body" + (opts.flush ? " flush" : "") });
  const w = el("div", { class: "window" + (opts.modal || opts.dialog ? " dialog" : "") + (opts.resizable ? " resizable" : "") + (opts.className ? " " + opts.className : ""),
    role: "dialog", "aria-label": opts.title || "" }, title, body);
  if (opts.buttons) w.append(opts.buttons);
  layer.append(w);
  placeWindow(w, opts.width || 520, opts.height);
  makeDraggable(w, title);
  const win = { element: w, body, title: titleText, closed: false, popped: null };
  win.raise = () => { if (win.popped) win.popped.raise(); else w.style.zIndex = ++zTop; };
  win.setTitle = (t) => { titleText.textContent = t; w.setAttribute("aria-label", t); if (win.popped) win.popped.setTitle(t); };
  win.popOut = () => {
    if (win.popped || win.closed) { win.raise(); return win.popped; }
    const box = el("div", { class: "pane win-pop" }, body, opts.buttons || null);
    const h = popOut(box, { name: opts.popout, title: titleText.textContent, help: opts.help,
      onreturn: () => {
        if (win.popped !== h) return;
        win.popped = null;
        w.append(body);
        if (opts.buttons) w.append(opts.buttons);
        w.hidden = false;
        win.raise();
      } });
    if (!h) { w.append(body); if (opts.buttons) w.append(opts.buttons); return null; }
    win.popped = h;
    w.hidden = true;
    return h;
  };
  if (popBtn) popBtn.addEventListener("click", () => { if (!win.popOut()) popupBlocked(); });
  win.close = (result) => {
    if (win.closed) return;
    if (opts.beforeclose && opts.beforeclose() === false) return;
    win.closed = true;
    openWindows.delete(win);
    if (win.popped) { const h = win.popped; win.popped = null; h.close(); }
    w.remove();
    if (opts.modal) {
      modalStack.splice(modalStack.indexOf(win), 1);
      if (!modalStack.length) layer.classList.remove("active");
    }
    if (opts.onclose) opts.onclose(result);
  };
  close.addEventListener("click", () => win.close());
  w.addEventListener("pointerdown", () => win.raise(), true);
  w.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !e.defaultPrevented) { e.preventDefault(); e.stopPropagation(); win.close(); }
  });
  if (opts.modal) { modalStack.push(win); layer.classList.add("active"); }
  openWindows.add(win);
  win.raise();
  return win;
}

export function topModal() { return modalStack[modalStack.length - 1] || null; }

/** Modal dialog promise: content builder gets (win, done). Resolves with done(value) or null on close. */
export function dialog(opts, build) {
  return new Promise((resolve) => {
    let result = null;
    const buttons = el("div", { class: "win-buttons" });
    const win = openWindow({ ...opts, modal: true, buttons, onclose: () => resolve(result) });
    const done = (v) => { result = v; win.close(v); };
    build(win, done, buttons);
    setTimeout(() => {
      const f = win.body.querySelector("[autofocus], input:not([type=checkbox]):not([disabled]), select, textarea");
      (f || buttons.querySelector("button.primary") || win.element).focus?.();
    }, 0);
  });
}

export function message(title, html, { buttons = [["OK", true]], width = 460, detail } = {}) {
  return dialog({ title, width }, (win, done, bar) => {
    win.body.append(el("div", { html }));
    if (detail) win.body.append(el("pre", { class: "mono", style: { maxHeight: "240px", border: "1px solid var(--border)", padding: "6px" } }, detail));
    buttons.forEach(([label, value, primary], i) => {
      const b = btn(label, () => done(value), { primary: primary ?? i === buttons.length - 1 });
      bar.append(b);
    });
    setTimeout(() => (bar.querySelector(".primary") || bar.lastChild)?.focus(), 0);
  });
}

export const confirmBox = (title, html, okLabel = "OK", opts = {}) =>
  message(title, html, { ...opts, buttons: [["Cancel", false, !opts.defaultOk ? true : false], [okLabel, true, !!opts.defaultOk]] });

export function prompt(title, label, value = "", { okLabel = "OK", note } = {}) {
  return dialog({ title, width: 420 }, (win, done, bar) => {
    const input = el("input", { type: "text", value, autofocus: true, style: { width: "100%" } });
    input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); done(input.value); } });
    win.body.append(el("label", {}, label), input);
    if (note) win.body.append(el("div", { class: "note", html: note }));
    bar.append(btn("Cancel", () => done(null)), btn(okLabel, () => done(input.value), { primary: true }));
    setTimeout(() => { input.focus(); input.select(); }, 0);
  });
}

// ------------------------------------------------------------------ popup menus
let openPopups = [];
export function closePopups(level = 0) {
  while (openPopups.length > level) openPopups.pop().remove();
}

/** items: [{label, icon, shortcut, checked, disabled, title, action(), items: [...]}, null = separator] */
export function popupMenu(items, x, y, { level = 0, onhover } = {}) {
  closePopups(level);
  const pop = el("div", { class: "menu-popup", role: "menu" });
  for (const it of items) {
    if (!it) { pop.append(el("div", { class: "menu-sep" })); continue; }
    const row = el("div", { class: "menu-item" + (it.disabled ? " disabled" : ""), role: "menuitem", title: it.title || "" },
      el("span", { class: "mi-icon" }, it.checked ? el("span", { class: "mi-check" }, "✓") : iconImg(it.icon, 16)),
      el("span", { class: "mi-label" }, it.label),
      it.items ? el("span", { class: "mi-arrow" }, "▸") : (it.shortcut ? el("span", { class: "mi-sc" }, it.shortcut) : null));
    if (it.cmd) row.dataset.cmd = it.cmd;
    let sub = null;  // this row's open submenu
    const enter = () => {
      pop.querySelectorAll(".menu-item.active").forEach((r) => r.classList.remove("active"));
      row.classList.add("active");
      if (onhover) onhover(it);
      if (it.items) {
        if (sub && openPopups[level + 1] === sub) return;
        const r = row.getBoundingClientRect();
        sub = popupMenu(it.items, r.right - 2, r.top - 4, { level: level + 1, onhover });
      } else closePopups(level + 1);
    };
    row.addEventListener("mouseenter", enter);
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      if (it.disabled) return;
      // touch screens have no hover: a tap on a submenu row opens the submenu
      if (it.items) { enter(); return; }
      if (document.body.classList.contains("whats-this") && it.cmd) { closePopups(); window.dispatchEvent(new CustomEvent("lf-whatsthis", { detail: it.cmd })); return; }
      closePopups();
      window.dispatchEvent(new Event("lf-menus-closed"));
      it.action && it.action();
    });
    pop.append(row);
  }
  const d = level > 0 && openPopups[level - 1] ? openPopups[level - 1].ownerDocument : host();
  const v = d.defaultView;
  d.body.append(pop);
  const r = pop.getBoundingClientRect();
  // a submenu with no room on the right opens to the left of its parent (narrow screens, tablets)
  if (level > 0 && x + r.width > v.innerWidth - 4) {
    const parent = openPopups[level - 1];
    if (parent) x = parent.getBoundingClientRect().left - r.width + 2;
  }
  pop.style.left = Math.max(0, Math.min(x, v.innerWidth - r.width - 4)) + "px";
  pop.style.top = Math.max(0, Math.min(y, v.innerHeight - r.height - 4)) + "px";
  openPopups.push(pop);
  return pop;
}
export const popupsOpen = () => openPopups.length > 0;

function closePopupsOutside(e) {
  if (openPopups.length && !e.target.closest(".menu-popup") && !e.target.closest(".menu-top")) {
    closePopups();
    window.dispatchEvent(new Event("lf-menus-closed"));
  }
}
document.addEventListener("pointerdown", closePopupsOutside);
for (const type of ["pointerdown", "keydown", "focusin"]) document.addEventListener(type, () => { hostDoc = document; }, true);

// ------------------------------------------------------------------ pop-out tabs
export const POPOUT_GLYPH = "↗";
export const POPOUT_TIP = "Open in New Tab\nMove this editor into its own browser tab (or window), e.g. on a second screen. " +
  "It stays connected to this page and shows every change at once; closing the tab, or Return to Main Tab, puts it back.";
const popouts = new Map();     // name -> handle
const pending = new Map();     // name -> attach(win), until popout.html has loaded
let popSerial = 0;

/** Tell the user the browser refused to open the tab (pop-up blocker). */
export function popupBlocked() {
  message("New tab blocked", "The browser did not open a new tab. Allow pop-ups for this site (in Safari on iPad: " +
    "Settings &gt; Apps &gt; Safari &gt; Block Pop-ups off) and try again.");
}

/** Move `element` into a new browser tab (popout.html). opts: {name, title, help(), onreturn(), onresize()}.
 *  Must be called from a click (browsers only open tabs for a user action). Returns a handle
 *  {popout: true, window, raise(), close(), setTitle(t)} or null if the browser blocked the tab. */
export function popOut(element, { name, title, help, onreturn, onresize }) {
  if (popouts.has(name)) popouts.get(name).close();
  const tab = window.open(`popout.html?${++popSerial}#${encodeURIComponent(name)}`, "lensforge-" + name);
  if (!tab) return null;
  element.hidden = true;
  let doc = null, ro = null, returned = false, titleEl = null;
  const h = { popout: true, window: tab, name };
  h.setTitle = (t) => { title = t; if (doc) { doc.title = `${t} - LensForge`; titleEl.textContent = t; } };
  h.raise = () => { try { tab.focus(); } catch (e) { /* closed */ } };
  const giveBack = () => {
    if (returned) return;
    returned = true;
    pending.delete(name);
    if (popouts.get(name) === h) popouts.delete(name);
    if (ro) ro.disconnect();
    if (doc) untrackDocument(doc);
    element.hidden = false;
    if (onreturn) onreturn();
  };
  h.close = () => { giveBack(); try { if (!tab.closed) tab.close(); } catch (e) { /* gone */ } };
  pending.set(name, (win) => {
    if (returned || win !== tab) return false;
    pending.delete(name);
    doc = win.document;
    titleEl = el("span", { class: "popout-title" }, title);
    const back = el("button", { type: "button", class: "btn small", title: "Return to Main Tab\nPut this editor back into the main LensForge tab and close this one.",
      onclick: () => h.close() }, "↙ Return to Main Tab");
    const bar = el("div", { class: "popout-bar" }, titleEl, el("span", { class: "grow" }),
      help ? el("button", { type: "button", class: "btn small", title: "Help on this editor (F1)", onclick: () => help() }, "? Help") : null, back);
    const root = doc.getElementById("popout-root");
    root.replaceChildren(bar, element);
    element.hidden = false;
    h.setTitle(title);
    trackDocument(doc);
    if (onresize) { ro = new win.ResizeObserver(() => onresize()); ro.observe(element); }
    win.addEventListener("pagehide", giveBack);
    return true;
  });
  popouts.set(name, h);
  // the tab never loaded (closed at once, or blocked after all): put the editor back
  setTimeout(() => { if (!doc) giveBack(); }, 20000);
  const poll = setInterval(() => { if (returned) clearInterval(poll); else if (tab.closed) { clearInterval(poll); giveBack(); } }, 1000);
  return h;
}

/** Called by popout.html when it has loaded (window.opener.LensForgePopout.ready(window)). */
window.LensForgePopout = {
  ready(win) {
    let name = "";
    try { name = decodeURIComponent(win.location.hash.slice(1)); } catch (e) { /* bad hash */ }
    const attach = pending.get(name);
    if (attach && attach(win)) return true;
    return false;
  },
};
// closing or reloading the main page closes its pop-out tabs (they cannot work without it)
window.addEventListener("pagehide", () => { for (const h of [...popouts.values()]) h.close(); });

// ------------------------------------------------------------------ files
export function download(name, text, type = "application/json") {
  const blob = text instanceof Blob ? text : new Blob([text], { type });
  const a = el("a", { href: URL.createObjectURL(blob), download: name });
  document.body.append(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

export function downloadDataURL(name, url) {
  const a = el("a", { href: url, download: name });
  document.body.append(a);
  a.click();
  a.remove();
}

export function pickFile(accept) {
  return new Promise((resolve) => {
    const i = el("input", { type: "file", accept, style: { display: "none" } });
    i.addEventListener("change", async () => {
      const f = i.files[0];
      i.remove();
      resolve(f ? { name: f.name, text: await readText(f) } : null);
    });
    i.addEventListener("cancel", () => { i.remove(); resolve(null); });
    document.body.append(i);
    i.click();
  });
}

export async function readText(file) {
  const buf = await file.arrayBuffer();
  const b = new Uint8Array(buf);
  if (b[0] === 0xff && b[1] === 0xfe) return new TextDecoder("utf-16le").decode(buf);
  if (b[0] === 0xfe && b[1] === 0xff) return new TextDecoder("utf-16be").decode(buf);
  try { return new TextDecoder("utf-8", { fatal: true }).decode(buf); } catch (e) { return new TextDecoder("latin1").decode(buf); }
}

export async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true; } catch (e) { return false; }
}

export function fmtDate(t) {
  if (!t) return "";
  const d = new Date(t);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) + " " +
    d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

export function fmtSize(n) { return n < 1024 ? n + " B" : (n / 1024).toFixed(n < 10240 ? 1 : 0) + " KB"; }

/** Drag a splitter: fn(delta) called with the pixel movement since the start. */
export function dragSplitter(splitter, onstart, onmove, onend) {
  splitter.addEventListener("pointerdown", (e) => {
    e.preventDefault();
    splitter.setPointerCapture(e.pointerId);
    const x0 = e.clientX, y0 = e.clientY;
    const s = onstart();
    const move = (ev) => onmove(s, ev.clientX - x0, ev.clientY - y0);
    // end the drag however the pointer goes away (released, cancelled by touch, capture lost), so a
    // half-finished drag never leaves the splitter stuck listening
    const up = () => {
      splitter.removeEventListener("pointermove", move);
      for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) splitter.removeEventListener(t, up);
      onend && onend();
    };
    splitter.addEventListener("pointermove", move);
    for (const t of ["pointerup", "pointercancel", "lostpointercapture"]) splitter.addEventListener(t, up);
  });
}
