"""Input ray settings (pure Python, no Qt).

The rays launched by the ray-based analyses (layout, spot diagrams, fans,
footprints) plus a list of user-defined rays are stored on the lens as
``system.input_rays`` (a plain dict), so they are copied with the lens, are
undoable, and are saved in the ``"ui"`` section of the ``.lens.json`` file
(the core lensforge loader ignores that section).
"""

from __future__ import annotations

import copy

DEFAULTS = {
    "layout_rays": 7,            # rays per fan in the layout
    "layout_plane": "y",         # "y" (Y-Z fan) or "x" (X-Z fan)
    "layout_fields": "all",      # "all" or list of field indices
    "layout_waves": "primary",   # "primary", "all" or list of wavelength indices
    "spot_pattern": "hexapolar",  # hexapolar, square, dithered, random
    "spot_rings": 6,             # rings (hexapolar) or grid size (square / dithered / random)
    "spot_reference": "chief",   # chief or centroid
    "fan_points": 41,            # pupil points per ray / OPD fan
    "footprint_rays": 64,        # pupil-edge rays per beam on footprint diagrams
    "user_rays": [],             # list of {"hx", "hy", "px", "py", "wave"} (wave: index, -1 = primary)
}

PATTERNS = ["hexapolar", "square", "dithered", "random"]


def get(system) -> dict:
    """The lens's input ray settings, with defaults filled in."""
    out = copy.deepcopy(DEFAULTS)
    out.update(copy.deepcopy(getattr(system, "input_rays", None) or {}))
    return out


def set(system, settings: dict):  # noqa: A001 - mirrors get()
    clean = {k: copy.deepcopy(v) for k, v in settings.items() if k in DEFAULTS}
    system.input_rays = clean


def fields(system, spec):
    if spec == "all" or spec is None:
        return list(range(len(system.fields)))
    return [int(i) for i in spec if 0 <= int(i) < len(system.fields)] or [0]


def waves(system, spec):
    """Wavelength values (um) for a "primary" / "all" / index list spec."""
    if spec == "primary" or spec is None:
        return [system.primary]
    if spec == "all":
        return [w.value for w in system.wavelengths]
    return [system.wavelengths[int(i)].value for i in spec if 0 <= int(i) < len(system.wavelengths)] or [
        system.primary]


def user_ray_wavelength(system, ray) -> float:
    w = int(ray.get("wave", -1))
    return system.primary if w < 0 or w >= len(system.wavelengths) else system.wavelengths[w].value
