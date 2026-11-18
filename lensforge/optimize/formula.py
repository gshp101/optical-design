"""Formulas over lens data cells, used by the :class:`~lensforge.optimize.solves.Formula` solve.

A formula is an arithmetic expression, in Python syntax, whose terms can be
other cells of the lens data editor.  It is the general form of a pickup:
``T(3) = 2 * T2 - 0.5`` or ``R(5) = -(R2 + R4) / 2``.

Cell references
    ``R3`` radius, ``C3`` curvature, ``T3`` thickness, ``K3`` conic,
    ``SD3`` semi-diameter (the automatic value if the cell is automatic),
    ``N3`` refractive index after the surface (primary wavelength),
    ``PAR3_2`` the surface's Par 2 column (as in the lens data editor).
    The function forms ``R(3)``, ``T(s - 1)``, ``PAR(3, 2)`` ... take the
    surface number as an expression in ``s`` (the surface the formula is
    on) and integers, so ``T(s - 1)`` always means "the thickness before".
    ``PARAM(3, "coefficients[2]")`` reads any optimisation parameter name.
Numbers and functions
    ``pi``, ``e``, ``+ - * / ** %``, ``abs min max sqrt exp log log10 sin
    cos tan asin acos atan atan2 degrees radians floor ceil round hypot``
    and ``a if condition else b`` with comparisons and ``and / or / not``.

Only these names are allowed: a formula cannot call anything else.
"""

from __future__ import annotations

import ast
import math
import re
from typing import Callable, List, Optional, Tuple

#: LDE parameter columns ("Par 1" ... "Par 8") for each surface kind
N_PAR = 8
_ORD = ["2nd", "4th", "6th", "8th", "10th", "12th", "14th", "16th"]


def parameter_columns(surface) -> List[Tuple[str, str]]:
    """(label, parameter name) for the Par 1..N_PAR columns of ``surface``."""
    k = surface.kind
    if k == "EVENASPH":
        return [(f"{_ORD[i]} Order Term", f"coefficients[{i}]") for i in range(N_PAR)]
    if k == "ODDASPH":
        return [(f"Order {i + 1} Term", f"coefficients[{i}]") for i in range(N_PAR)]
    if k == "TOROIDAL":
        return [("Radius X", "radius_x")] + [(f"{_ORD[i]} Order Term", f"coefficients[{i}]") for i in range(N_PAR - 1)]
    if k == "XYPOLY":
        return [("Norm Radius", "norm_radius")]
    if k == "BINARY2":
        return ([("Diffract Order", "diffraction_order"), ("Norm Radius", "norm_radius")]
                + [(f"Coeff p^{2 * (i + 1)}", f"coefficients[{i}]") for i in range(N_PAR - 2)])
    if k == "DGRATING":
        return [("Lines/um", "lines_per_um"), ("Diff Order", "diffraction_order")]
    if k == "PARAXIAL":
        return [("Focal Length", "focal_length")]
    if k == "COORDBRK":
        return [("Decenter X", "decenter_x"), ("Decenter Y", "decenter_y"), ("Tilt About X", "tilt_x"),
                ("Tilt About Y", "tilt_y"), ("Tilt About Z", "tilt_z"), ("Order", "order")]
    return []


# ---------------------------------------------------------------------------
# Reading and writing cells by lens-data-editor key
# ---------------------------------------------------------------------------

def get_cell(system, surface: int, key: str) -> float:
    """Numeric value of a cell: ``key`` is "radius", "curvature", "thickness", "conic",
    "semi_diameter", "radius_x" or a parameter name such as "coefficients[2]"."""
    s = system.surfaces[surface]
    if key == "radius_x":
        return math.inf if s.curvature_x == 0 else 1.0 / s.curvature_x
    if key == "semi_diameter" and s.semi_diameter is None:
        sd = system.copy().update_semi_diameters()
        return float(sd[surface])
    from .variables import get_param
    return float(get_param(system, surface, key))


def set_cell(system, surface: int, key: str, value: float):
    """Set a numeric cell (see :func:`get_cell` for the keys)."""
    s = system.surfaces[surface]
    value = float(value)
    if key == "radius_x":
        s.curvature_x = 0.0 if (math.isinf(value) or value == 0) else 1.0 / value
        return
    if key == "radius":
        s.radius = value
        return
    if key in ("diffraction_order", "order"):
        value = int(round(value))
        setattr(s, key, value)
        return
    from .variables import set_param
    set_param(system, surface, key, value)


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

#: one-letter (or SD / N / PAR) cell functions -> cell key
CELL_FUNCS = {"R": "radius", "C": "curvature", "T": "thickness", "K": "conic", "SD": "semi_diameter",
              "N": "index"}
_SHORT = re.compile(r"^(SD|PAR|R|C|T|K|N)(\d+)(?:_(\d+))?$")

MATH = {
    "abs": abs, "min": min, "max": max, "round": round,
    **{n: getattr(math, n) for n in ("sqrt", "exp", "log", "log10", "sin", "cos", "tan", "asin", "acos", "atan",
                                     "atan2", "degrees", "radians", "floor", "ceil", "hypot")},
}
CONSTANTS = {"pi": math.pi, "e": math.e, "inf": math.inf}

_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow, ast.Mod, ast.FloorDiv)
_UNARY = (ast.UAdd, ast.USub, ast.Not)
_CMP = (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)


class FormulaError(ValueError):
    pass


class Ref:
    """A cell reference found in a formula (``surface`` is None while it depends on ``s``)."""

    def __init__(self, kind, surface_node, extra=None, short=None):
        self.kind = kind                    # "R", "C", "T", "K", "SD", "N", "PAR" or "PARAM"
        self.surface_node = surface_node    # AST node of the surface number expression
        self.extra = extra                  # PAR column number or PARAM name
        self.short = short                  # the Name node for the R3 / PAR3_2 forms


def _check_surface_expr(node, text):
    """Surface numbers may use integers, ``s`` and + - * // only."""
    for n in ast.walk(node):
        if isinstance(n, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Load)) or isinstance(n, _BINOPS + _UNARY):
            continue
        if isinstance(n, ast.Constant) and isinstance(n.value, int) and not isinstance(n.value, bool):
            continue
        if isinstance(n, ast.Name) and n.id == "s":
            continue
        raise FormulaError(f"a surface number may only use integers and s: {ast.get_source_segment(text, node)!r}")


def parse(text: str):
    """Check ``text`` and return ``(tree, refs)``; raises :class:`FormulaError` if it is not a valid formula."""
    if not str(text).strip():
        raise FormulaError("the formula is empty")
    try:
        tree = ast.parse(str(text).strip(), mode="eval")
    except SyntaxError as e:
        raise FormulaError(f"syntax error: {e.msg}") from None
    src = str(text).strip()
    refs: List[Ref] = []
    skip = set()

    def visit(n):
        if id(n) in skip:
            return
        if isinstance(n, ast.Call):
            if not isinstance(n.func, ast.Name) or n.keywords:
                raise FormulaError("only the listed functions can be called")
            f = n.func.id
            if f in CELL_FUNCS:
                if len(n.args) != 1:
                    raise FormulaError(f"{f}() takes one surface number, e.g. {f}(3)")
                _check_surface_expr(n.args[0], src)
                refs.append(Ref(f, n.args[0]))
                skip.update(id(x) for x in ast.walk(n.args[0]))
                skip.add(id(n.func))
            elif f in ("PAR", "PARAM"):
                if len(n.args) != 2:
                    raise FormulaError(f"{f}() takes a surface number and a "
                                       + ("column number, e.g. PAR(3, 2)" if f == "PAR"
                                          else "parameter name, e.g. PARAM(3, \"coefficients[1]\")"))
                _check_surface_expr(n.args[0], src)
                a = n.args[1]
                if f == "PAR" and not (isinstance(a, ast.Constant) and isinstance(a.value, int)
                                       and 1 <= a.value <= N_PAR):
                    raise FormulaError(f"PAR column must be a number from 1 to {N_PAR}")
                if f == "PARAM" and not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                    raise FormulaError("PARAM needs the parameter name in quotes")
                refs.append(Ref(f, n.args[0], a.value))
                skip.update(id(x) for x in ast.walk(n.args[0]))
                skip.update((id(a), id(n.func)))
            elif f not in MATH:
                raise FormulaError(f"unknown function {f}()")
            else:
                skip.add(id(n.func))
        elif isinstance(n, ast.Name):
            m = _SHORT.match(n.id)
            if m:
                kind, num, col = m.group(1), int(m.group(2)), m.group(3)
                if kind == "PAR":
                    if col is None or not 1 <= int(col) <= N_PAR:
                        raise FormulaError(f"write the Par column as PAR{num}_2 (columns 1 to {N_PAR})")
                    refs.append(Ref("PAR", None, int(col), short=n))
                elif col is not None:
                    raise FormulaError(f"unknown name {n.id}")
                else:
                    refs.append(Ref(kind, None, short=n))
            elif n.id not in CONSTANTS and n.id != "s":
                raise FormulaError(f"unknown name {n.id!r} (cells are written R3, T2, K4, SD1, N2, PAR3_2)")
        elif isinstance(n, ast.Constant):
            if not isinstance(n.value, (int, float)) or isinstance(n.value, bool):
                raise FormulaError("only numbers are allowed (and a quoted name inside PARAM)")
        elif isinstance(n, ast.BinOp):
            if not isinstance(n.op, _BINOPS):
                raise FormulaError("operator not allowed")
        elif isinstance(n, ast.UnaryOp):
            if not isinstance(n.op, _UNARY):
                raise FormulaError("operator not allowed")
        elif isinstance(n, ast.Compare):
            if not all(isinstance(o, _CMP) for o in n.ops):
                raise FormulaError("comparison not allowed")
        elif not isinstance(n, (ast.Expression, ast.IfExp, ast.BoolOp, ast.And, ast.Or, ast.Load) + _BINOPS
                            + _UNARY + _CMP):
            raise FormulaError(f"{type(n).__name__} is not allowed in a formula")
        for c in ast.iter_child_nodes(n):
            visit(c)

    visit(tree)
    return tree, refs


def _short_surface(ref):
    return int(_SHORT.match(ref.short.id).group(2))


def ref_surface(ref, s: int) -> int:
    """Surface number a reference points at, for a formula on surface ``s``."""
    if ref.short is not None:
        return _short_surface(ref)
    v = eval(compile(ast.Expression(ref.surface_node), "<formula>", "eval"), {"__builtins__": {}}, {"s": s})
    return int(v)


def ref_key(system, ref, surface: int) -> Optional[str]:
    """Cell key read by a reference (None for the index, which is not a cell)."""
    if ref.kind in CELL_FUNCS:
        return None if ref.kind == "N" else CELL_FUNCS[ref.kind]
    if ref.kind == "PARAM":
        return ref.extra
    cols = parameter_columns(system.surfaces[surface])
    if ref.extra > len(cols):
        raise FormulaError(f"surface {surface} ({system.surfaces[surface].kind}) has no Par {ref.extra} column")
    return cols[ref.extra - 1][1]


def references(system, text: str, s: int) -> List[Tuple[int, Optional[str]]]:
    """(surface, cell key) of every cell the formula reads (key None: the surface's index)."""
    _, refs = parse(text)
    out = []
    for r in refs:
        i = ref_surface(r, s)
        _check_index(system, i)
        out.append((i, ref_key(system, r, i)))
    return out


def _check_index(system, i):
    if not 0 <= i < len(system.surfaces):
        raise FormulaError(f"surface {i} does not exist (the lens has surfaces 0 to {len(system.surfaces) - 1})")


def evaluate(system, text: str, s: int) -> float:
    """Value of the formula ``text`` on surface ``s`` of ``system``."""
    tree, refs = parse(text)

    def read(ref, i):
        _check_index(system, i)
        if ref.kind == "N":
            return float(system.media(system.primary)[0][i])
        return get_cell(system, i, ref_key(system, ref, i))

    # replace each reference by a call to a lookup function
    env = dict(CONSTANTS)
    env.update(MATH)
    env["s"] = s
    by_node = {}
    for k, r in enumerate(refs):
        name = f"__ref{k}"
        if r.short is not None:
            by_node[id(r.short)] = name
            env[name] = read(r, _short_surface(r))
        else:
            env[name] = (lambda r: lambda i, *_: read(r, int(i)))(r)

    class Swap(ast.NodeTransformer):
        def visit_Name(self, n):
            if id(n) in by_node:
                return ast.copy_location(ast.Name(by_node[id(n)], ast.Load()), n)
            return n

        def visit_Call(self, n):
            if isinstance(n.func, ast.Name) and n.func.id in CELL_FUNCS or (
                    isinstance(n.func, ast.Name) and n.func.id in ("PAR", "PARAM")):
                k = next(j for j, r in enumerate(refs) if r.surface_node is n.args[0])
                return ast.copy_location(ast.Call(ast.Name(f"__ref{k}", ast.Load()), [n.args[0]], []), n)
            self.generic_visit(n)
            return n

    tree = ast.fix_missing_locations(Swap().visit(tree))
    try:
        v = eval(compile(tree, "<formula>", "eval"), {"__builtins__": {}}, env)
    except FormulaError:
        raise
    except ZeroDivisionError:
        raise FormulaError("division by zero") from None
    except (ValueError, OverflowError, TypeError) as e:
        raise FormulaError(str(e)) from None
    if isinstance(v, bool):
        v = float(v)
    return float(v)


def renumber(text: str, fn: Callable[[int], Optional[int]], s_old: int, s_new: int) -> Optional[str]:
    """Rewrite the surface numbers in ``text`` after surfaces were inserted or deleted.

    ``fn(old) -> new`` (None if deleted); the formula moves from ``s_old`` to ``s_new``.
    Returns the new text, or None if a referenced surface was deleted.  Written numbers
    (``T3``, ``R(3)``) are renumbered; expressions in ``s`` are left alone when they still
    point at the same cell, otherwise rewritten as a number."""
    src = str(text).strip()
    _, refs = parse(src)
    lines = src.splitlines(keepends=True)
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln))

    def offset(line, col):
        # ast offsets are UTF-8 byte offsets within the line
        return starts[line - 1] + len(lines[line - 1].encode()[:col].decode())

    edits = []
    for r in refs:
        if r.short is not None:
            old = _short_surface(r)
            new = fn(old)
            if new is None:
                return None
            if new != old:
                m = _SHORT.match(r.short.id)
                name = m.group(1) + str(new) + (f"_{m.group(3)}" if m.group(3) else "")
                edits.append((offset(r.short.lineno, r.short.col_offset),
                              offset(r.short.end_lineno, r.short.end_col_offset), name))
            continue
        old = ref_surface(r, s_old)
        new = fn(old)
        if new is None:
            return None
        if ref_surface(r, s_new) != new:
            n = r.surface_node
            edits.append((offset(n.lineno, n.col_offset), offset(n.end_lineno, n.end_col_offset), str(new)))
    for a, b, t in sorted(edits, reverse=True):
        src = src[:a] + t + src[b:]
    return src
