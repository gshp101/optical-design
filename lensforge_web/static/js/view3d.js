// Rotatable 3-D line view (the 3D Layout analysis): the session sends the lines once (global x, y, z
// polylines with colours, the same data lensforge.plot.layout_3d draws) and this canvas projects them,
// so dragging and zooming are instant and never go back to Python.
//
// The view follows matplotlib's mplot3d convention, with the plot axes (z, x, y) of the lens:
// elevation / azimuth 0 / -90 is the YZ side view (z to the right, y up), 90 / -90 looks down on XZ.

const DEG = Math.PI / 180;

export class View3D {
  /** @param {HTMLElement} host element the canvas fills
   *  @param {(elev:number, azim:number) => void} onview called after the user turns the view */
  constructor(host, onview) {
    this.host = host;
    this.onview = onview;
    this.canvas = document.createElement("canvas");
    this.canvas.className = "view3d";
    this.canvas.title = "Drag: rotate. Mouse wheel or pinch: zoom. Shift-drag or right-drag: pan. Double-click: reset the view";
    host.prepend(this.canvas);
    this.scene = null;
    this.elev = 20;
    this.azim = -60;
    this.zoom = 1;
    this.pan = [0, 0];  // screen offset in CSS pixels
    this.pointers = new Map();
    this.install();
    new ResizeObserver(() => this.draw()).observe(host);
  }

  setScene(scene, keepView = true) {
    const first = !this.scene;
    this.scene = scene;
    if (first || !keepView) this.setView(scene.elevation, scene.azimuth);
    else this.draw();
  }

  /** Turn the view to (elev, azim) degrees and undo any zoom and pan. */
  setView(elev, azim, { zoom = 1, pan = [0, 0] } = {}) {
    this.elev = Math.max(-90, Math.min(90, elev));
    this.azim = azim;
    this.zoom = zoom;
    this.pan = pan.slice();
    this.draw();
  }

  /** Screen basis (right, up, toward the viewer) in plot axes (z, x, y of the lens). */
  basis() {
    const e = this.elev * DEG, a = this.azim * DEG;
    const right = [-Math.sin(a), Math.cos(a), 0];
    const up = [-Math.sin(e) * Math.cos(a), -Math.sin(e) * Math.sin(a), Math.cos(e)];
    return { right, up };
  }

  install() {
    const c = this.canvas;
    c.addEventListener("contextmenu", (e) => e.preventDefault());
    c.addEventListener("pointerdown", (e) => {
      c.setPointerCapture(e.pointerId);
      this.pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
      this.dragMode = e.button === 2 || e.button === 1 || e.shiftKey ? "pan" : "rotate";
      this.moved = false;
    });
    c.addEventListener("pointermove", (e) => {
      const p = this.pointers.get(e.pointerId);
      if (!p) return;
      if (this.pointers.size === 2) {  // pinch: zoom by the change in finger distance
        const [a, b] = [...this.pointers.values()];
        const d0 = Math.hypot(a.x - b.x, a.y - b.y);
        p.x = e.clientX; p.y = e.clientY;
        const [a2, b2] = [...this.pointers.values()];
        const d1 = Math.hypot(a2.x - b2.x, a2.y - b2.y);
        if (d0 > 0) this.zoom *= d1 / d0;
        this.draw();
        return;
      }
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      if (!dx && !dy) return;
      this.moved = true;
      if (this.dragMode === "pan") this.pan = [this.pan[0] + dx, this.pan[1] + dy];
      else {
        this.azim = ((this.azim - dx * 0.5 + 540) % 360) - 180;
        this.elev = Math.max(-90, Math.min(90, this.elev + dy * 0.5));
      }
      this.draw();
    });
    const up = (e) => {
      if (!this.pointers.delete(e.pointerId)) return;
      if (this.moved && this.dragMode === "rotate" && this.onview) this.onview(this.elev, this.azim);
    };
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", (e) => {
      e.preventDefault();
      const f = e.deltaY < 0 ? 1.2 : 1 / 1.2;
      // zoom about the cursor: keep the point under it fixed
      const r = c.getBoundingClientRect();
      const mx = e.clientX - r.left - r.width / 2 - this.pan[0], my = e.clientY - r.top - r.height / 2 - this.pan[1];
      this.pan = [this.pan[0] - mx * (f - 1), this.pan[1] - my * (f - 1)];
      this.zoom *= f;
      this.draw();
    }, { passive: false });
    c.addEventListener("dblclick", () => {
      if (!this.scene) return;
      this.setView(this.scene.elevation, this.scene.azimuth);
      if (this.onview) this.onview(this.elev, this.azim);
    });
  }

  draw() {
    const c = this.canvas, s = this.scene;
    const rect = this.host.getBoundingClientRect();
    const W = Math.max(50, Math.round(rect.width)), H = Math.max(50, Math.round(rect.height));
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (c.width !== W * dpr || c.height !== H * dpr) { c.width = W * dpr; c.height = H * dpr; }
    c.style.width = W + "px";
    c.style.height = H + "px";
    const g = c.getContext("2d");
    g.setTransform(dpr, 0, 0, dpr, 0, 0);
    g.fillStyle = "#fff";
    g.fillRect(0, 0, W, H);
    if (!s) return;
    const { right, up } = this.basis();
    const [lo, hi] = s.bounds;
    // plot axes (z, x, y) of the lens; the bounds are in lens x, y, z
    const mid = [(lo[2] + hi[2]) / 2, (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2];
    const radius = Math.max(1e-9, 0.5 * Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]));
    const top = 22, legendW = 0;
    const k = this.zoom * 0.47 * Math.min(W - legendW, H - top) / radius;
    const cx = W / 2 + this.pan[0], cy = (H + top) / 2 + this.pan[1];
    const proj = (x, y, z) => {  // lens x, y, z -> canvas px
      const u = z - mid[0], v = x - mid[1], w = y - mid[2];
      return [cx + k * (u * right[0] + v * right[1] + w * right[2]), cy - k * (u * up[0] + v * up[1] + w * up[2])];
    };
    g.lineJoin = "round";
    g.lineCap = "round";
    for (const kind of ["ray", "edge", "surface"]) {  // glass outlines on top of the rays
      for (const ln of s.lines) {
        if (ln.k !== kind) continue;
        const p = ln.p;
        g.beginPath();
        for (let i = 0; i < p.length; i += 3) {
          const [X, Y] = proj(p[i], p[i + 1], p[i + 2]);
          if (i) g.lineTo(X, Y); else g.moveTo(X, Y);
        }
        g.strokeStyle = ln.c;
        g.lineWidth = Math.max(0.6, ln.w * 1.1);
        g.stroke();
      }
    }
    // title
    g.fillStyle = "#222";
    g.font = "12px system-ui, sans-serif";
    g.textAlign = "center";
    g.fillText(s.title || "", W / 2, 15);
    // legend
    g.textAlign = "left";
    g.font = "11px system-ui, sans-serif";
    s.legend.forEach(([col, lab], i) => {
      const y = top + 8 + i * 15;
      g.strokeStyle = col;
      g.lineWidth = 2;
      g.beginPath(); g.moveTo(8, y); g.lineTo(26, y); g.stroke();
      g.fillStyle = "#333";
      g.fillText(lab, 31, y + 4);
    });
    this.drawTriad(g, right, up, W, H);
  }

  /** The lens's x, y, z axes in the lower-left corner, turning with the view. */
  drawTriad(g, right, up, W, H) {
    const ox = 34, oy = H - 30, L = 20;
    const axes = [["z", [1, 0, 0], "#1f4fd6"], ["x", [0, 1, 0], "#d62728"], ["y", [0, 0, 1], "#2ca02c"]];
    g.font = "11px system-ui, sans-serif";
    g.textAlign = "center";
    for (const [name, a, col] of axes) {
      const dx = a[0] * right[0] + a[1] * right[1] + a[2] * right[2];
      const dy = a[0] * up[0] + a[1] * up[1] + a[2] * up[2];
      g.strokeStyle = col;
      g.lineWidth = 1.5;
      g.beginPath(); g.moveTo(ox, oy); g.lineTo(ox + L * dx, oy - L * dy); g.stroke();
      g.fillStyle = col;
      g.fillText(name, ox + (L + 7) * dx, oy - (L + 7) * dy + 4);
    }
    g.fillStyle = "#666";
    g.textAlign = "right";
    g.fillText(`elevation ${this.elev.toFixed(0)}°, azimuth ${this.azim.toFixed(0)}°` +
      (this.scene.units ? `, ${this.scene.units}` : ""), W - 8, H - 8);
  }

  dataURL() { return this.canvas.toDataURL("image/png"); }
}
