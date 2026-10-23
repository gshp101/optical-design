"""Glass selection: nearest catalog glasses, model-glass snapping and glass substitution."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field as dc_field
from typing import Dict, List, Optional, Sequence, Tuple

from ..materials import Material, ModelGlass
from .dls import optimize
from .global_opt import _merit_or_inf, restore, snapshot
from .merit import MeritFunction
from .solves import apply_solves
from .variables import GLASS_PARAMS, VariableSet, variables as _system_variables


def catalog_glasses(library, catalogs: Optional[Sequence[str]] = None):
    """Yield (spec, material, nd, vd) for every refracting glass in the library."""
    wanted = None if catalogs is None else {c.upper() for c in catalogs}
    for cname, cat in library.catalogs.items():
        if wanted is not None and cname not in wanted:
            continue
        for g in cat:
            try:
                nd, vd = float(g.nd), float(g.vd)
            except Exception:  # outside the material's data range
                continue
            if nd <= 1.0 or not math.isfinite(vd):
                continue
            yield f"{cname}:{g.name}", g, nd, vd


def nearest_glasses(target, library, n: int = 5, catalogs: Optional[Sequence[str]] = None,
                    nd_weight: float = 100.0, vd_weight: float = 1.0) -> List[Tuple[str, float, float, float]]:
    """Catalog glasses closest to ``target`` (a material, a spec or an (nd, vd) pair) in the
    nd-Vd diagram, distance = sqrt((nd_weight dnd)^2 + (vd_weight dVd)^2).
    Returns [(spec, distance, nd, vd)] sorted by distance."""
    if isinstance(target, tuple):
        nd0, vd0 = target
    else:
        m = target if isinstance(target, Material) else library.resolve(target)
        nd0, vd0 = (m.nd_value, m.vd_value) if isinstance(m, ModelGlass) else (m.nd, m.vd)
    out = []
    for spec, g, nd, vd in catalog_glasses(library, catalogs):
        d = math.hypot(nd_weight * (nd - nd0), vd_weight * (vd - vd0))
        out.append((spec, d, nd, vd))
    out.sort(key=lambda t: t[1])
    return out[:n]


def glass_surfaces(system) -> List[int]:
    """Surfaces followed by a refracting glass (not air, not a mirror)."""
    out = []
    for i in range(1, system.image_index):
        s = system.surfaces[i]
        if s.is_coordinate_break:
            continue
        m = system.library.resolve(s.material)
        if not m.is_mirror and m.nd != 1.0:
            out.append(i)
    return out


def _drop_glass_vars(system, vs: VariableSet, surfaces):
    return VariableSet(v for v in vs if not (v.surface in surfaces and v.param in GLASS_PARAMS))


def snap_to_catalog(system, surfaces: Optional[Sequence[int]] = None, catalogs: Optional[Sequence[str]] = None,
                    **kw) -> Dict[int, str]:
    """Replace model glasses by their nearest catalog glass (and remove their glass variables)."""
    lib = system.library
    out = {}
    surfaces = glass_surfaces(system) if surfaces is None else surfaces
    for i in surfaces:
        m = lib.resolve(system.surfaces[i].material)
        if not isinstance(m, ModelGlass):
            continue
        spec = nearest_glasses(m, lib, 1, catalogs, **kw)[0][0]
        system.surfaces[i].material = spec
        out[i] = spec
    vs = _system_variables(system)
    vs[:] = _drop_glass_vars(system, vs, set(out))
    return out


@dataclass
class SubstitutionResult:
    system: object
    merit: float
    initial_merit: float
    choices: Dict[int, str]
    trials: List[Tuple[int, str, float]] = dc_field(default_factory=list)
    seconds: float = 0.0

    def __repr__(self):
        ch = ", ".join(f"S{k}: {v}" for k, v in self.choices.items())
        return (f"SubstitutionResult(merit {self.initial_merit:.6g} -> {self.merit:.6g}; {ch}; "
                f"{len(self.trials)} glasses tried, {self.seconds:.1f} s)")


def glass_substitution(system, merit: MeritFunction, variables: Optional[VariableSet] = None,
                       surfaces: Optional[Sequence[int]] = None,
                       candidates: Optional[Dict[int, Sequence[str]] | Sequence[str]] = None,
                       catalogs: Optional[Sequence[str]] = None, nearest: Optional[int] = None,
                       cycles: int = 10, passes: int = 2, verbose: bool = False) -> SubstitutionResult:
    """Choose glasses by trial substitution with re-optimisation (in place).

    For each surface in ``surfaces`` (default: every glass), each candidate
    glass is tried, the other variables are re-optimised for ``cycles`` DLS
    cycles and the best glass is kept; this coordinate search is repeated for
    ``passes`` passes or until nothing changes.  ``candidates`` is a list of
    glass specs for all surfaces or a dict per surface; by default all glasses
    of ``catalogs`` (or the library), restricted to the ``nearest`` n to the
    current glass if given.  Model glasses are a good way to start: optimise
    nd/Vd as variables, then let this pick real glasses near them.
    """
    t0 = time.time()
    lib = system.library
    surfaces = glass_surfaces(system) if surfaces is None else list(surfaces)
    vs_all = VariableSet(variables if variables is not None else _system_variables(system))
    vs = _drop_glass_vars(system, vs_all, set(surfaces))

    def cand_for(i):
        if isinstance(candidates, dict):
            return list(candidates.get(i, []))
        if candidates is not None:
            return list(candidates)
        if nearest:
            return [c[0] for c in nearest_glasses(system.surfaces[i].material, lib, nearest, catalogs)]
        return [c[0] for c in catalog_glasses(lib, catalogs)]

    initial = _merit_or_inf(system, merit)
    if any(isinstance(lib.resolve(system.surfaces[i].material), ModelGlass) for i in surfaces):
        snap_to_catalog(system, surfaces, catalogs)
    best = optimize(system, merit, vs, cycles=cycles).merit if vs else _merit_or_inf(system, merit)
    best_snap = snapshot(system)
    trials = []
    for _ in range(passes if len(surfaces) > 1 else 1):
        changed = False
        for i in surfaces:
            cur = system.surfaces[i].material
            for spec in cand_for(i):
                if spec == cur:
                    continue
                restore(system, best_snap)
                system.surfaces[i].material = spec
                if not math.isfinite(_merit_or_inf(system, merit)):
                    continue
                try:
                    m = optimize(system, merit, vs, cycles=cycles).merit if vs else _merit_or_inf(system, merit)
                except RuntimeError:
                    continue
                trials.append((i, spec, m))
                if verbose:
                    print(f"S{i} {spec:>20}: merit {m:.8g}")
                if m < best * (1 - 1e-9):
                    best, best_snap, changed = m, snapshot(system), True
            restore(system, best_snap)
        if not changed:
            break
    restore(system, best_snap)
    apply_solves(system)
    vs_all_sys = _system_variables(system)
    vs_all_sys[:] = _drop_glass_vars(system, vs_all_sys, set(surfaces))
    choices = {i: str(system.surfaces[i].material) for i in surfaces}
    return SubstitutionResult(system, best, initial, choices, trials, time.time() - t0)
