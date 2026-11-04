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

function placeWindow(w, width, height) {
  const vw = window.innerWidth, vh = window.innerHeight;
  const W = Math.min(width, vw - 20), H = Math.min(height, vh - 20);
  const n = document.querySelectorAll("#floating-layer .window").length;
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
    handle.setPointerCapture(e.pointerId);
    const move = (ev) => {
      w.style.left = Math.max(-r.width + 80, Math.min(window.innerWidth - 80, ev.clientX - dx)) + "px";
      w.style.top = Math.max(0, Math.min(window.innerHeight - 30, ev.clientY - dy)) + "px";
    };
    const up = () => { handle.removeEventListener("pointermove", move); handle.removeEventListener("pointerup", up); };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", up);
  });
}

/** A window. opts: {title, width, height, modal, resizable, buttons: el, onclose, className, flush, help}
 *  returns {element, body, close(), setTitle(), raise()} */
export function openWindow(opts) {
  const layer = document.getElementById(opts.modal ? "modal-layer" : "floating-layer");
  const titleText = el("span", { class: "wt-text" }, opts.title || "");
  const close = el("button", { type: "button", title: "Close", "aria-label": "Close" }, "×");
  const title = el("div", { class: "win-title" }, opts.icon ? iconImg(opts.icon, 16) : null, titleText);
  if (opts.help) title.append(el("button", { type: "button", title: "Help on this window (F1)", onclick: opts.help }, "?"));
  if (opts.extraTitle) title.append(opts.extraTitle);
  title.append(close);
  const body = el("div", { class: "win-body" + (opts.flush ? " flush" : "") });
  const w = el("div", { class: "window" + (opts.modal || opts.dialog ? " dialog" : "") + (opts.resizable ? " resizable" : "") + (opts.className ? " " + opts.className : ""),
    role: "dialog", "aria-label": opts.title || "" }, title, body);
  if (opts.buttons) w.append(opts.buttons);
  layer.append(w);
  placeWindow(w, opts.width || 520, opts.height);
  makeDraggable(w, title);
  const win = { element: w, body, title: titleText, closed: false };
  win.raise = () => { w.style.zIndex = ++zTop; };
  win.setTitle = (t) => { titleText.textContent = t; w.setAttribute("aria-label", t); };
  win.close = (result) => {
    if (win.closed) return;
    if (opts.beforeclose && opts.beforeclose() === false) return;
    win.closed = true;
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
    row.addEventListener("mouseenter", () => {
      pop.querySelectorAll(".menu-item.active").forEach((r) => r.classList.remove("active"));
      row.classList.add("active");
      if (onhover) onhover(it);
      if (it.items) {
        const r = row.getBoundingClientRect();
        popupMenu(it.items, r.right - 2, r.top - 4, { level: level + 1, onhover });
      } else closePopups(level + 1);
    });
    row.addEventListener("click", (e) => {
      e.stopPropagation();
      if (it.disabled || it.items) return;
      if (document.body.classList.contains("whats-this") && it.cmd) { closePopups(); window.dispatchEvent(new CustomEvent("lf-whatsthis", { detail: it.cmd })); return; }
      closePopups();
      window.dispatchEvent(new Event("lf-menus-closed"));
      it.action && it.action();
    });
    pop.append(row);
  }
  document.body.append(pop);
  const r = pop.getBoundingClientRect();
  pop.style.left = Math.max(0, Math.min(x, window.innerWidth - r.width - 4)) + "px";
  pop.style.top = Math.max(0, Math.min(y, window.innerHeight - r.height - 4)) + "px";
  openPopups.push(pop);
  return pop;
}
export const popupsOpen = () => openPopups.length > 0;

document.addEventListener("pointerdown", (e) => {
  if (openPopups.length && !e.target.closest(".menu-popup") && !e.target.closest(".menu-top")) {
    closePopups();
    window.dispatchEvent(new Event("lf-menus-closed"));
  }
});

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
    const up = () => { splitter.removeEventListener("pointermove", move); splitter.removeEventListener("pointerup", up); onend && onend(); };
    splitter.addEventListener("pointermove", move);
    splitter.addEventListener("pointerup", up);
  });
}
