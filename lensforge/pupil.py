"""Pupil sampling patterns (normalised coordinates inside the unit circle)."""

from __future__ import annotations

import numpy as np


def pupil_grid(pattern: str = "hexapolar", n: int = 6, seed: int = 0):
    """Return (px, py) arrays sampling the unit pupil.

    pattern: "hexapolar" (n rings), "square" (n x n grid clipped to the circle),
    "random" (n**2 uniform points), "dithered" (jittered square grid),
    "ring" (n points on the edge), "cross" (n points on each axis fan).
    """
    p = pattern.lower()
    if p == "hexapolar":
        xs, ys = [0.0], [0.0]
        for i in range(1, n + 1):
            r = i / n
            th = np.linspace(0, 2 * np.pi, 6 * i, endpoint=False)
            xs.extend(r * np.sin(th))
            ys.extend(r * np.cos(th))
        return np.array(xs), np.array(ys)
    if p in ("square", "grid", "dithered"):
        v = (np.arange(n) + 0.5) / n * 2 - 1
        x, y = np.meshgrid(v, v)
        x, y = x.ravel(), y.ravel()
        if p == "dithered":
            rng = np.random.default_rng(seed)
            x = x + (rng.random(x.size) - 0.5) * 2 / n
            y = y + (rng.random(y.size) - 0.5) * 2 / n
        m = x * x + y * y <= 1.0
        return x[m], y[m]
    if p == "random":
        rng = np.random.default_rng(seed)
        r = np.sqrt(rng.random(n * n))
        th = rng.random(n * n) * 2 * np.pi
        return r * np.cos(th), r * np.sin(th)
    if p == "ring":
        th = np.linspace(0, 2 * np.pi, n, endpoint=False)
        return np.cos(th), np.sin(th)
    if p == "cross":
        v = np.linspace(-1, 1, n)
        z = np.zeros(n)
        return np.concatenate([v, z]), np.concatenate([z, v])
    raise ValueError(f"Unknown pupil pattern {pattern!r}")
