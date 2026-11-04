// The lens engine (Pyodide in worker.js) behind a call queue: one Python call at a time, user commands
// before background work (analysis updates, merit values), and a Stop flag shared with Python.
const CFG = self.LENSFORGE_CONFIG || {};

let worker = null;
let nextId = 1;
const waiting = new Map();
const queue = [];          // {method, args, priority, resolve, reject, key}
let busy = null;
let stopBuffer = null;
const listeners = { progress: [], state: [], status: [] };

export const PRIORITY = { user: 0, normal: 1, background: 2 };
export const canStop = () => !!stopBuffer;

export function on(kind, fn) { listeners[kind].push(fn); }
function emit(kind, data) { for (const fn of listeners[kind]) fn(data); }

export function start() {
  return new Promise((resolve, reject) => {
    worker = new Worker("worker.js" + (CFG.build ? "?b=" + CFG.build : ""));
    if (self.crossOriginIsolated && typeof SharedArrayBuffer !== "undefined") stopBuffer = new SharedArrayBuffer(4);
    worker.onmessage = (e) => {
      const m = e.data;
      if (m.type === "status") emit("status", m);
      else if (m.type === "ready") resolve(m.info);
      else if (m.type === "failed") reject(new Error(m.error));
      else if (m.type === "progress") emit("progress", m.data);
      else if (m.type === "result") {
        const w = waiting.get(m.id);
        waiting.delete(m.id);
        busy = null;
        let out;
        try { out = JSON.parse(m.json); } catch (err) { out = { error: "bad reply from Python: " + err }; }
        if (out.state) emit("state", out.state);
        w.resolve(out);
        pump();
      }
    };
    worker.onerror = (e) => reject(new Error(e.message || "the lens engine could not start"));
    const params = new URLSearchParams(location.search);
    worker.postMessage({ type: "init", stop: stopBuffer, pyodide: params.get("pyodide") || CFG.pyodide });
  });
}

function pump() {
  if (busy || !queue.length) return;
  queue.sort((a, b) => a.priority - b.priority || a.seq - b.seq);
  const job = queue.shift();
  busy = job;
  const id = nextId++;
  waiting.set(id, job);
  if (stopBuffer) Atomics.store(new Int32Array(stopBuffer), 0, 0);
  worker.postMessage({ type: "call", id, method: job.method, args: job.args });
}

let seq = 0;
/** Raw call: resolves with {result, state?, error?}. A queued call with the same `key` is replaced. */
export function callRaw(method, args = {}, { priority = PRIORITY.user, key } = {}) {
  return new Promise((resolve) => {
    if (key) {
      const i = queue.findIndex((q) => q.key === key);
      if (i >= 0) { queue[i].resolve({ superseded: true }); queue.splice(i, 1); }
    }
    queue.push({ method, args, priority, resolve, key, seq: seq++ });
    pump();
  });
}

/** Call and return the result; throws Error(message) when Python raised. */
export async function call(method, args = {}, opts = {}) {
  const out = await callRaw(method, args, opts);
  if (out.error) { const e = new Error(out.error); e.pythonType = out.error_type; throw e; }
  return out.result;
}

export function requestStop() {
  if (stopBuffer) Atomics.store(new Int32Array(stopBuffer), 0, 1);
  return !!stopBuffer;
}

export const isBusy = () => !!busy;
export const busyMethod = () => (busy ? busy.method : null);
