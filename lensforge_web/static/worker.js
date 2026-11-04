// The lens engine: Pyodide running lensforge in a Web Worker, so long computations never freeze the page.
// Messages in:  {type: "init", stop: SharedArrayBuffer|null}  {type: "call", id, method, args}
// Messages out: {type: "status", text, fraction}  {type: "ready", info}  {type: "result", id, json}
//               {type: "progress", data}  {type: "failed", error}
importScripts("config.js");
const CFG = self.LENSFORGE_CONFIG || {};
let dispatch = null;
let stopFlag = null;

self.lf_report = (s) => postMessage({ type: "progress", data: JSON.parse(s) });
self.lf_stop = () => (stopFlag ? Atomics.load(stopFlag, 0) === 1 : false);

function status(text, fraction) { postMessage({ type: "status", text, fraction }); }

async function init(msg) {
  const url = msg.pyodide || CFG.pyodide;
  if (msg.stop) stopFlag = new Int32Array(msg.stop);
  status("Loading Python (Pyodide)...", 0.05);
  importScripts(url + "pyodide.js");
  const py = await loadPyodide({ indexURL: url });
  status("Loading NumPy and matplotlib...", 0.35);
  let n = 0;
  await py.loadPackage(["numpy", "matplotlib"], {
    messageCallback: (m) => { n += 1; status(m, Math.min(0.8, 0.35 + n * 0.03)); },
    errorCallback: (m) => status(m, null),
  });
  status("Loading lensforge...", 0.85);
  const resp = await fetch("py/lensforge.zip?b=" + (CFG.build || ""));
  if (!resp.ok) throw new Error("py/lensforge.zip: HTTP " + resp.status);
  py.unpackArchive(await resp.arrayBuffer(), "zip", { extractDir: "/home/pyodide/lfweb" });
  status("Starting the lens engine...", 0.92);
  py.runPython(`
import os, sys, json
os.environ["MPLBACKEND"] = "Agg"
sys.path.insert(0, "/home/pyodide/lfweb")
import js
from lensforge_web import session as _lfw

class _JSStop:
    def is_set(self):
        return bool(js.lf_stop())

_s = _lfw.session()
_s.report = lambda data: js.lf_report(json.dumps(_lfw._clean(data)))
_s.stop = _JSStop()
import matplotlib
matplotlib.use("Agg")
`);
  dispatch = py.globals.get("_lfw").dispatch;
  const info = JSON.parse(dispatch("about", "{}")).result;
  postMessage({ type: "ready", info });
}

self.onmessage = async (e) => {
  const msg = e.data;
  if (msg.type === "init") {
    try { await init(msg); } catch (err) { postMessage({ type: "failed", error: String(err && err.message || err) }); }
    return;
  }
  if (msg.type === "call") {
    let json;
    try { json = dispatch(msg.method, JSON.stringify(msg.args || {})); }
    catch (err) { json = JSON.stringify({ error: "Python error: " + String(err && err.message || err) }); }
    postMessage({ type: "result", id: msg.id, json });
  }
};
