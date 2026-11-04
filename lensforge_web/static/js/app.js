// LensForge in the browser: boot, menu bar, toolbar, keyboard shortcuts and the command of every menu
// item (as lensforge_qt/main_window.py). Lens files live in this browser's storage (IndexedDB).
import { App, run, call, status, statusError, onState, cmd, initDocks, setState } from "./core.js";
import * as engine from "./engine.js";
import * as store from "./storage.js";
import * as lde from "./lde.js";
import * as D from "./dialogs.js";
import { openAnalysis, closeAll, tabAll, windows } from "./analysis.js";
import { showMFE, showMCE, showShell, showUndoHistory, localShortcut } from "./editors.js";
import { optimization, tolerancing, nsEditor, helpBrowser, customizeToolbar } from "./tools.js";
import { el, esc, iconImg, message, confirmBox, popupMenu, closePopups, popupsOpen, topModal, download, pickFile, readText } from "./ui.js";

const IS_MAC = /Mac|iPhone|iPad/.test(navigator.platform || navigator.userAgent);
const plain = (html) => { const d = document.createElement("div"); d.innerHTML = html || ""; return d.textContent; };

// ================================================================== files
/** Ask to save unsaved changes (Qt: maybe_save). Resolves true when it is fine to replace the lens. */
async function maybeSave() {
  const s = App.state;
  if (!s || !s.modified) return true;
  const r = await message("LensForge", `Save changes to <b>${esc(s.title)}</b>?`,
    { buttons: [["Cancel", null, false], ["Discard", "discard", false], ["Save", "save", true]] });
  if (r === "save") return save();
  return r === "discard";
}

async function openSource(src) {
  if (!src) return false;
  const r = await run("open_text", { text: src.text, filename: src.filename || src.name, path: src.path || null }, { priority: 0 });
  if (!r) return false;
  if (src.path) store.addRecent(src.path);
  status(`Opened ${r.name}`);
  if (r.missing) await message("Missing glass", esc(r.missing).replace(/\n/g, "<br>") +
    "<br><br>Load the catalog with File &gt; Load Glass Catalog (AGF), or pick another material.");
  if (r.notes) await message("Imported file", esc(r.notes).replace(/\n/g, "<br>"));
  return true;
}

async function openStored(name) {
  const l = await store.loadLens(name);
  if (!l) { store.dropRecent(name); statusError(`${name} is no longer in this browser's storage`); return; }
  if (await maybeSave()) await openSource({ name, text: l.text, path: name, filename: name + ".lens.json" });
}

let askedPersistence = false;
async function saveTo(name) {
  const text = await run("lens_text");
  if (text === undefined) return false;
  try { await store.saveLens(name, text); } catch (e) { statusError(`Could not save: ${e.message || e}`); return false; }
  await run("mark_saved", { path: name });
  store.addRecent(name);
  status(`Saved ${name} in this browser (File > Export to Disk writes a file)`);
  if (!askedPersistence) { askedPersistence = true; store.askPersistence(); }
  return true;
}

async function save() {
  if (!App.state.path) return saveAs();
  return saveTo(App.state.path);
}

async function saveAs() {
  const name = await D.saveAsDialog(await run("suggested_name"));
  return name ? saveTo(name) : false;
}

/** Open a bundled example (Examples menu) as an unsaved lens named after the file. */
async function openExample(x) {
  if (!(await maybeSave())) return;
  const text = await D.fetchExample(x.path);
  if (text == null) { statusError(`Could not load the example ${x.path}`); return; }
  if (await openSource({ name: x.name, text, path: null, filename: x.path.split("/").pop() }))
    status(`Opened a copy of the example ${x.name}; File > Save keeps it in this browser`);
}

async function browseExamples() {
  if (await maybeSave()) await openSource(await D.chooseLens({ title: "Open Example", tab: 1 }));
}

async function importFromDisk() {
  if (!(await maybeSave())) return;
  const f = await pickFile(".json,.zmx,.ZMX,.zos");
  if (f) await openSource({ name: f.name, text: f.text, path: null, filename: f.name });
}

async function exportToDisk() {
  const text = await run("lens_text");
  if (text === undefined) return;
  const name = D.safeFile(await run("suggested_name"));
  download(name + ".lens.json", text);
  status(`Downloaded ${name}.lens.json`);
}

async function exportPrescription() {
  const r = await run("prescription");
  if (r === undefined) return;
  const text = typeof r === "string" ? r : r.text || "";
  download(D.safeFile(await run("suggested_name")) + "_prescription.txt", text, "text/plain");
}

async function loadSample(name) {
  if (!(await maybeSave())) return;
  if (await run("load_sample", { name }, { priority: 0 })) {
    if (!windows.length) openAnalysis("layout");
    status(`Loaded sample lens ${name}`);
  }
}

async function forgetCatalogs() {
  const cats = await store.list("catalogs");
  if (!cats.length) { await message("Glass catalogs", "No glass catalogs are stored in this browser."); return; }
  if (!(await confirmBox("Forget Loaded Glass Catalogs", "Stop reloading these catalogs when LensForge starts?<br><br>" +
    cats.map((c) => `<b>${esc(c.name)}</b> (${esc(c.file)})`).join("<br>") +
    "<br><br>They stay available until the page is reloaded.", "Forget"))) return;
  for (const c of cats) await store.remove("catalogs", c.name);
  D.forgetCatalogCache();
  status("Stored glass catalogs forgotten; they are gone after the next reload");
}

async function convertToNS() {
  const w = await nsEditor();
  if (w && w.fromLens) w.fromLens();
}

// ================================================================== commands
function buildCommands() {
  const C = App.commands;
  const lensCmd = (method, args) => () => run(method, args || {}, { priority: 0 });
  Object.assign(C, {
    "File > New": async () => { if (await maybeSave()) { await run("new_lens"); status("New lens"); } },
    "File > Open": async () => { if (await maybeSave()) await openSource(await D.chooseLens()); },
    "File > Save": save,
    "File > Save As": saveAs,
    "File > Import from Disk": importFromDisk,
    "File > Export to Disk": exportToDisk,
    "File > Insert Lens": () => D.insertLensDialog(lde.current().row),
    "File > Inspect Lens File": () => D.inspectLens(async (src) => { if (await maybeSave()) await openSource(src); }),
    "File > System Explorer": () => D.systemExplorer(0),
    "File > Fields": () => D.systemExplorer(1),
    "File > Wavelengths": () => D.systemExplorer(2),
    "File > Input Rays": () => D.inputRaysDialog(),
    "File > Load Glass Catalog (AGF)": () => D.loadAGF(),
    "File > Forget Loaded Glass Catalogs": forgetCatalogs,
    "File > Export Prescription": exportPrescription,
    "Examples > Browse Examples": browseExamples,

    "Edit > Undo": lensCmd("undo"),
    "Edit > Redo": lensCmd("redo"),
    "Edit > Undo History": showUndoHistory,
    "Edit > Insert Surface": () => lde.insertBefore(),
    "Edit > Insert Surface After": () => lde.insertAfter(),
    "Edit > Delete Surface": () => lde.deleteSurface(),
    "Edit > Delete Surfaces": () => lde.deleteSurfacesDialog(),
    "Edit > Toggle Variable": () => lde.toggleVariable(),
    "Edit > Choose Material": () => lde.chooseMaterial(lde.current().row),
    "Edit > Surface Properties": () => lde.surfaceProperties(lde.current().row),
    "Edit > Quick Focus (paraxial)": async () => { if (await run("quick_focus", {}, { priority: 0 }) !== undefined) status("Quick focus: image distance set for best paraxial focus"); },
    "Edit > Fix Semi-Diameters at Current Values": lensCmd("fix_semi_diameters"),
    "Edit > Make All Semi-Diameters Automatic": lensCmd("auto_semi_diameters"),

    "Analysis > Tab All Analysis Windows": tabAll,
    "Analysis > Close All Analysis Windows": closeAll,

    "Tools > Optimization": optimization,
    "Tools > Tolerancing": tolerancing,
    "Tools > Python Shell": showShell,
    "Tools > Merit Function Editor": showMFE,
    "Tools > Multi-Configuration Editor": showMCE,
    "Tools > Next Configuration": lensCmd("step_config", { step: 1 }),
    "Tools > Previous Configuration": lensCmd("step_config", { step: -1 }),
    "Tools > Non-Sequential > Non-Sequential Editor": nsEditor,
    "Tools > Non-Sequential > Convert Lens to Non-Sequential": convertToNS,
    "Tools > Variables and Solves > Make All Curvatures Variable": lensCmd("vary_curvatures"),
    "Tools > Variables and Solves > Make All Air Spaces Variable": lensCmd("vary_air_spaces"),
    "Tools > Variables and Solves > Remove All Variables": lensCmd("clear_variables"),
    "Tools > Variables and Solves > Remove All Solves": lensCmd("clear_solves"),

    "View > Show Toolbar": () => showToolbar(!toolbarVisible()),
    "View > Customize Toolbar": customize,
    "View > Undo History": showUndoHistory,

    "Help > Help Contents": () => helpBrowser(contextHelp()),
    "Help > What's This?": () => whatsThis(!document.body.classList.contains("whats-this")),
    "Help > Keyboard Shortcuts": D.shortcutsHelp,
    "Help > About": D.about,
  });
  for (const name of App.menus.samples) C["File > Sample Lenses > " + name] = () => loadSample(name);
  for (const spec of Object.values(App.specs)) C[spec.id] = () => openAnalysis(spec.key);
  App.onHelp = (id) => helpBrowser(id);
  const missing = Object.keys(App.menus.commands).filter((id) => !C[id]);
  if (missing.length) console.warn("menu commands without an action:", missing);
}

/** F1 in an editor opens that editor's page (Qt: context help). */
function contextHelp() {
  const scope = App.focusScope;
  if (scope === "mfe") return App.help.root;
  if (scope === "mce") return "Tools > Multi-Configuration Editor";
  if (scope === "shell") return "Tools > Python Shell";
  return undefined;
}

// ================================================================== menu bar
const menubar = () => document.getElementById("menubar");
let openTop = null;

function menuItems(items) {
  const C = App.menus.commands;
  return items.map((it) => {
    if (!it) return null;
    if (it.items) {
      if (it.label === "Open Recent") return { label: it.label, items: recentItems() };
      return { label: it.label, items: menuItems(it.items) };
    }
    const c = C[it.id] || {};
    return { label: it.label, shortcut: it.shortcut, icon: c.icon, cmd: it.id, title: plain(c.summary),
      checked: it.id === "View > Show Toolbar" ? toolbarVisible() : undefined, action: () => cmd(it.id) };
  });
}

/** The Examples menu's lens entries, nested by folder like examples/ (built from examples/index.json). */
function exampleItems() {
  const ex = App.examples || [];
  if (!ex.length) return [{ label: "(no example lenses found)", disabled: true }];
  const root = { files: [], folders: new Map() };
  for (const x of ex) {
    let node = root;
    for (const f of x.folders || []) {
      if (!node.folders.has(f)) node.folders.set(f, { files: [], folders: new Map() });
      node = node.folders.get(f);
    }
    node.files.push(x);
  }
  const items = (node) => [
    ...node.files.map((x) => ({ label: x.name, title: `Open a copy of the example examples/${x.path}`, action: () => openExample(x) })),
    ...[...node.folders].map(([label, sub]) => ({ label, items: items(sub) }))];
  return items(root);
}

function recentItems() {
  const names = store.recent();
  if (!names.length) return [{ label: "(no recent lenses)", disabled: true }];
  return [...names.map((n, i) => ({ label: `${i + 1}  ${n}`, title: `Open ${n} from this browser's storage`, action: () => openStored(n) })),
    null, { label: "Clear Recent", action: () => { store.setSetting("recent", []); status("Recent list cleared"); } }];
}

function buildMenubar() {
  const bar = menubar();
  bar.replaceChildren();
  for (const top of App.menus.tree) {
    const t = el("div", { class: "menu-top", role: "menuitem", tabindex: "-1" }, top.label);
    const open = () => {
      closePopups();
      bar.querySelectorAll(".menu-top.open").forEach((x) => x.classList.remove("open"));
      t.classList.add("open");
      openTop = t;
      const r = t.getBoundingClientRect();
      const items = top.label === "Examples" ? [...menuItems(top.items), null, ...exampleItems()] : menuItems(top.items);
      popupMenu(items, r.left, r.bottom, { onhover: (it) => status(it.title || "", 0) });
    };
    t.addEventListener("pointerdown", (e) => {
      e.preventDefault();
      if (openTop === t && popupsOpen()) { closeMenus(); return; }
      open();
    });
    t.addEventListener("mouseenter", () => { if (openTop && openTop !== t && popupsOpen()) open(); });
    bar.append(t);
  }
}

function closeMenus() {
  closePopups();
  menubar().querySelectorAll(".menu-top.open").forEach((x) => x.classList.remove("open"));
  openTop = null;
  status("");
}
window.addEventListener("lf-menus-closed", () => {
  menubar().querySelectorAll(".menu-top.open").forEach((x) => x.classList.remove("open"));
  openTop = null;
});

// ================================================================== toolbar
const toolbarEl = () => document.getElementById("toolbar");
const toolbarVisible = () => !!store.setting("toolbarVisible", false);
const toolbarIds = () => store.setting("toolbar", App.menus.default_toolbar);
const toolbarStyle = () => store.setting("toolbarStyle", "icons");

function tooltip(id) {
  const c = App.menus.commands[id];
  if (!c) return id;
  return c.label.replace(/\.\.\.$/, "") + (c.shortcut ? ` (${c.shortcut})` : "") + (c.summary ? "\n" + plain(c.summary) : "");
}

function buildToolbar() {
  const tb = toolbarEl();
  const C = App.menus.commands, SEP = App.menus.separator;
  const style = toolbarStyle();
  tb.replaceChildren();
  let sep = false;
  for (const id of toolbarIds()) {
    if (id === SEP) { sep = true; continue; }
    const c = C[id];
    if (!c) continue;
    if (sep && tb.childElementCount) tb.append(el("div", { class: "tb-sep" }));
    sep = false;
    const b = el("button", { type: "button", class: "tb-btn style-" + style.replace(/[^a-z]+/g, "-"), title: tooltip(id), "aria-label": c.label, "data-cmd": id });
    if (style !== "text") b.append(iconImg(c.icon, 22));
    if (style !== "icons") b.append(el("span", { class: "tb-text" }, c.short || c.label.replace(/\.\.\.$/, "")));
    b.addEventListener("click", () => {
      if (document.body.classList.contains("whats-this")) { whatsThis(false); helpBrowser(id); return; }
      cmd(id);
    });
    b.addEventListener("mouseenter", () => status(plain(c.summary), 0));
    b.addEventListener("mouseleave", () => status(""));
    tb.append(b);
  }
  tb.hidden = !toolbarVisible();
}

function showToolbar(on) {
  store.setSetting("toolbarVisible", !!on);
  toolbarEl().hidden = !on;
  window.dispatchEvent(new Event("resize"));
}

async function customize() {
  const r = await customizeToolbar(toolbarIds(), toolbarStyle(), App.menus.default_toolbar);
  if (!r) return;
  store.setSetting("toolbar", r.ids);
  store.setSetting("toolbarStyle", r.style);
  store.setSetting("toolbarVisible", true);
  buildToolbar();
  showToolbar(true);
  status("Toolbar updated", 4000);
}

function toolbarContextMenu(e) {
  e.preventDefault();
  popupMenu([{ label: "Customize Toolbar...", icon: App.menus.commands["View > Customize Toolbar"].icon, action: customize },
    { label: "Hide Toolbar", action: () => showToolbar(false) }], e.clientX, e.clientY);
}

// ================================================================== What's This?
function whatsThis(on) {
  document.body.classList.toggle("whats-this", on);
  status(on ? "What's This? Click a menu item or toolbar button for its help (Esc cancels)" : "", on ? 0 : 1);
}
window.addEventListener("lf-whatsthis", (e) => { whatsThis(false); closeMenus(); helpBrowser(e.detail); });
document.addEventListener("pointerdown", (e) => {
  if (!document.body.classList.contains("whats-this")) return;
  if (e.target.closest(".menu-top, .menu-popup, .tb-btn")) return;
  whatsThis(false);
}, true);

// ================================================================== keyboard shortcuts
const CODE_KEYS = { BracketLeft: "[", BracketRight: "]", Insert: "Ins", Delete: "Del", Minus: "-", Equal: "=", Comma: ",", Period: ".",
  Slash: "/", Semicolon: ";", Quote: "'", Backquote: "`", Backslash: "\\", Escape: "Esc", Enter: "Enter", Backspace: "Backspace",
  Space: "Space", Tab: "Tab", PageUp: "PgUp", PageDown: "PgDown", Home: "Home", End: "End",
  ArrowUp: "Up", ArrowDown: "Down", ArrowLeft: "Left", ArrowRight: "Right" };

/** The key as the menus write it: Ctrl+Shift+S, Alt+N, F5, Ins, Shift+Del, Ctrl+] ... (Cmd counts as Ctrl on a Mac). */
export function keyName(e) {
  let k;
  if (/^Key[A-Z]$/.test(e.code)) k = e.code.slice(3);
  else if (/^Digit\d$/.test(e.code)) k = e.code.slice(5);
  else if (/^F\d{1,2}$/.test(e.key)) k = e.key;
  else k = CODE_KEYS[e.code] || (e.key && e.key.length === 1 ? e.key.toUpperCase() : e.key);
  if (["Control", "Shift", "Alt", "Meta"].includes(k)) return null;
  const ctrl = IS_MAC ? e.metaKey || e.ctrlKey : e.ctrlKey;
  return (ctrl ? "Ctrl+" : "") + (e.altKey ? "Alt+" : "") + (e.shiftKey ? "Shift+" : "") + k;
}

// keys a text field needs for itself (typing, its own undo, clipboard, deleting)
const TEXT_KEYS = new Set(["Ctrl+Z", "Ctrl+Y", "Ctrl+Shift+Z", "Ctrl+A", "Ctrl+C", "Ctrl+V", "Ctrl+X", "Ins", "Ctrl+Ins", "Shift+Ins",
  "Shift+Del", "Ctrl+Left", "Ctrl+Right", "Ctrl+Shift+Left", "Ctrl+Shift+Right"]);

let shortcutMap = {};
function buildShortcuts() {
  shortcutMap = {};
  for (const [id, c] of Object.entries(App.menus.commands)) if (c.shortcut) shortcutMap[c.shortcut] = id;
}

function onKey(e) {
  if (e.defaultPrevented) return;
  const k = keyName(e);
  if (!k) return;
  if (k === "Esc") {
    if (document.body.classList.contains("whats-this")) { whatsThis(false); e.preventDefault(); return; }
    if (popupsOpen()) { closeMenus(); e.preventDefault(); return; }
    return;
  }
  if (/^F[1-8]$/.test(k)) e.preventDefault();  // browser help, search, reload ... belong to LensForge here
  if (topModal()) return;                        // a modal dialog has the keyboard
  const t = e.target;
  const typing = t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || t.tagName === "SELECT" || t.isContentEditable);
  if (typing) {
    const plainKey = !/^(Ctrl|Alt)\+/.test(k) && !/^(Shift\+)?F\d+$/.test(k);
    if (plainKey || TEXT_KEYS.has(k)) return;
  }
  const scope = App.focusScope;
  if (scope && localShortcut(scope, k)) { e.preventDefault(); return; }
  const id = shortcutMap[k];
  if (!id || !App.commands[id]) return;
  e.preventDefault();
  closeMenus();
  cmd(id);
}

// ================================================================== status bar, title
function showState(s) {
  const lensEl = document.getElementById("status-lens");
  lensEl.textContent = s.status.text;
  lensEl.title = s.missing || s.status.text;
  lensEl.classList.toggle("error-text", !!s.status.error);
  document.getElementById("status-config").textContent = s.config ? `Config ${s.config}` : "";
  document.title = `${s.title}${s.modified ? " *" : ""} - LensForge`;
}

// ================================================================== session (survives a reload)
let sessionTimer = null;
function saveSessionSoon() {
  clearTimeout(sessionTimer);
  sessionTimer = setTimeout(saveSession, 600);
}
async function saveSession() {
  const out = await engine.callRaw("session_dump", {}, { priority: engine.PRIORITY.background, key: "session" });
  if (out.superseded || !out.result) return;
  try { await store.put("session", { name: "current", ...out.result, saved: Date.now() }); } catch (e) { /* storage full or blocked */ }
}

async function restoreSession() {
  let rec = null;
  try { rec = await store.get("session", "current"); } catch (e) { rec = null; }
  if (rec && rec.text) {
    try {
      await call("session_restore", { data: rec });
      status(`Restored ${App.state.title} from the last visit`);
      return true;
    } catch (e) {
      statusError(`Could not restore the last session: ${e.message}`);
    }
  }
  return false;
}

async function reloadCatalogs() {
  let cats = [];
  try { cats = await store.list("catalogs"); } catch (e) { return; }
  for (const c of cats) {
    try { await call("load_agf", { name: c.file || c.name, text: c.text }); }
    catch (e) { statusError(`Stored glass catalog ${c.name} could not be loaded: ${e.message}`); }
  }
}

// ================================================================== drag and drop
function setupDrop() {
  window.addEventListener("dragover", (e) => { if ([...(e.dataTransfer?.types || [])].includes("Files")) e.preventDefault(); });
  window.addEventListener("drop", async (e) => {
    const files = [...(e.dataTransfer?.files || [])];
    if (!files.length) return;
    e.preventDefault();
    for (const f of files) {
      const text = await readText(f);
      if (/\.agf$/i.test(f.name)) {
        try {
          const r = await call("load_agf", { name: f.name, text });
          await store.put("catalogs", { name: r.catalog, file: f.name, text, saved: Date.now() });
          D.forgetCatalogCache();
          status(`Loaded glass catalog ${f.name} (${r.glasses} glasses)`);
        } catch (err) { statusError(`${f.name}: ${err.message}`); }
      } else if (await maybeSave()) {
        await openSource({ name: f.name, text, path: null, filename: f.name });
        break;
      }
    }
  });
}

// ================================================================== boot
function splash(text, fraction) {
  document.getElementById("splash-msg").textContent = text;
  if (fraction != null) document.getElementById("splash-progress").style.width = Math.round(fraction * 100) + "%";
}

async function boot() {
  initDocks();
  engine.on("status", (m) => splash(m.text, m.fraction));
  let info;
  try {
    info = await engine.start();
  } catch (e) {
    splash("");
    document.getElementById("splash-msg").innerHTML = `<span class="error-text">The lens engine could not start: ${esc(e.message)}</span>` +
      "<br>LensForge needs a recent browser with WebAssembly, and the first start needs the internet to download Python.";
    return;
  }
  splash("Starting the user interface...", 0.95);
  const [menus, specs, help, about, operandNames] = await Promise.all([
    call("menus"), call("analysis_specs"), call("help_data"), call("about"), call("operand_names")]);
  Object.assign(App, { menus, specs, help, operandNames, info: { ...info, ...about } });
  D.examplesIndex().then((ex) => { App.examples = ex; });  // the Examples menu's entries
  await reloadCatalogs();
  lde.init();
  onState((s, old) => {
    showState(s);
    if (!old || s.revision !== old.revision || s.modified !== old.modified || s.path !== old.path) saveSessionSoon();
  });
  if (!(await restoreSession())) setState(await call("state"));
  buildCommands();
  buildShortcuts();
  buildMenubar();
  buildToolbar();
  toolbarEl().addEventListener("contextmenu", toolbarContextMenu);
  document.addEventListener("keydown", onKey);
  // editors claim the keyboard scope in their own focusin handlers, which run after this capture one
  document.addEventListener("focusin", () => { App.focusScope = null; }, true);
  setupDrop();
  window.addEventListener("pagehide", () => { clearTimeout(sessionTimer); saveSession(); });
  document.getElementById("splash").classList.add("gone");
  document.getElementById("lde").focus();
  if (!engine.canStop()) console.info("LensForge: the page is not cross-origin isolated, so Stop cannot interrupt a running optimisation");
  window.LensForge = { App, cmd, run, call, engine, store };  // for the browser console and the tests
}

boot();
