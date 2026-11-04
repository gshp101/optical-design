// Browser-local storage. Lens files, AGF catalogs and non-sequential scenes go in IndexedDB (no size
// limit worth worrying about, unlike cookies at 4 KB); small settings (toolbar, recent files) in localStorage.
const DB_NAME = "lensforge";
const STORES = ["lenses", "catalogs", "scenes", "session"];
let dbPromise = null;
let memory = null;  // fallback when IndexedDB is unavailable (private windows of some browsers)

function db() {
  if (!dbPromise) {
    dbPromise = new Promise((resolve) => {
      let req;
      try { req = indexedDB.open(DB_NAME, 1); } catch (e) { resolve(null); return; }
      req.onupgradeneeded = () => {
        for (const s of STORES) if (!req.result.objectStoreNames.contains(s)) req.result.createObjectStore(s, { keyPath: "name" });
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    });
  }
  return dbPromise;
}

function mem(store) {
  if (!memory) memory = Object.fromEntries(STORES.map((s) => [s, new Map()]));
  return memory[store];
}

async function tx(store, mode, fn) {
  const d = await db();
  if (!d) return fn(null, mem(store));
  return new Promise((resolve, reject) => {
    const t = d.transaction(store, mode);
    const s = t.objectStore(store);
    let out;
    Promise.resolve(fn(s, null)).then((v) => { out = v; });
    t.oncomplete = () => resolve(out);
    t.onerror = () => reject(t.error);
    t.onabort = () => reject(t.error);
  });
}

const req = (r) => new Promise((resolve, reject) => { r.onsuccess = () => resolve(r.result); r.onerror = () => reject(r.error); });

export async function put(store, record) {
  return tx(store, "readwrite", (s, m) => (s ? req(s.put(record)) : m.set(record.name, record)));
}
export async function get(store, name) {
  return tx(store, "readonly", (s, m) => (s ? req(s.get(name)) : m.get(name)));
}
export async function remove(store, name) {
  return tx(store, "readwrite", (s, m) => (s ? req(s.delete(name)) : m.delete(name)));
}
export async function list(store) {
  const all = await tx(store, "readonly", (s, m) => (s ? req(s.getAll()) : [...m.values()]));
  return (all || []).sort((a, b) => a.name.localeCompare(b.name, undefined, { sensitivity: "base" }));
}
export const persistent = async () => !!(await db());

export async function askPersistence() {
  try { if (navigator.storage && navigator.storage.persist) return await navigator.storage.persist(); } catch (e) {}
  return false;
}

// ------------------------------------------------------------------ lenses
export async function saveLens(name, text) {
  await put("lenses", { name, text, saved: Date.now(), size: text.length });
}
export const loadLens = (name) => get("lenses", name);
export const deleteLens = (name) => remove("lenses", name);
export const listLenses = () => list("lenses");
export async function renameLens(oldName, newName) {
  const r = await get("lenses", oldName);
  if (!r) return false;
  await put("lenses", { ...r, name: newName });
  await remove("lenses", oldName);
  return true;
}

// ------------------------------------------------------------------ settings (localStorage, never required)
export function setting(key, fallback) {
  try {
    const v = localStorage.getItem("lensforge/" + key);
    return v === null ? fallback : JSON.parse(v);
  } catch (e) { return fallback; }
}
export function setSetting(key, value) {
  try { localStorage.setItem("lensforge/" + key, JSON.stringify(value)); } catch (e) {}
}

export function recent() { return setting("recent", []); }
export function addRecent(name) { setSetting("recent", [name, ...recent().filter((n) => n !== name)].slice(0, 10)); }
export function dropRecent(name) { setSetting("recent", recent().filter((n) => n !== name)); }
