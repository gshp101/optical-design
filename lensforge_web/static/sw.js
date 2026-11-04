// Adds the cross-origin isolation headers (COOP/COEP) to every response, on hosts such as GitHub
// Pages that cannot send them. With them the page can share memory with its worker, which is how
// the Stop button of an optimisation reaches Python while it runs. Nothing is cached here.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (e) => e.waitUntil(self.clients.claim()));
self.addEventListener("fetch", (e) => {
  const r = e.request;
  if (r.cache === "only-if-cached" && r.mode !== "same-origin") return;
  e.respondWith(fetch(r).then((res) => {
    if (res.status === 0) return res;  // opaque response: leave it alone
    const h = new Headers(res.headers);
    h.set("Cross-Origin-Embedder-Policy", "require-corp");
    h.set("Cross-Origin-Opener-Policy", "same-origin");
    if (!h.has("Cross-Origin-Resource-Policy")) h.set("Cross-Origin-Resource-Policy", "cross-origin");
    return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
  }).catch((err) => { console.error("LensForge service worker:", err); return Response.error(); }));
});
