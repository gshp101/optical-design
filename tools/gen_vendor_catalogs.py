"""Regenerate ``lensforge/vendor_catalogs.py`` from the glass makers' own data sheets.

The sheets are the Excel downloads published by OHARA, HOYA, CDGM, Sumita and
Hikari, as redistributed in the BSD-licensed ``opticalglass`` package on PyPI
(``pip download --no-deps opticalglass``; unzip the wheel; pass its
``opticalglass/data`` directory)::

    python tools/gen_vendor_catalogs.py path/to/opticalglass/data > lensforge/vendor_catalogs.py

Each glass is checked: the index computed from its dispersion coefficients at
the d line must match the sheet's nd to 5e-5, otherwise the glass is skipped
(and reported on stderr).  Needs ``openpyxl``.
"""

from __future__ import annotations

import math
import os
import sys

import openpyxl
from openpyxl.utils import column_index_from_string as col

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from lensforge.materials import FORMULAS  # noqa: E402

LAMBDA_D = 0.5875618


def _num(v):
    if v is None or v == "":
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _rows(ws, first):
    for row in ws.iter_rows(min_row=first, values_only=True):
        yield lambda c, row=row: row[col(c) - 1] if col(c) - 1 < len(row) else None


def ohara(data):
    out = []
    sheets = [openpyxl.load_workbook(os.path.join(data, f), read_only=True, data_only=True).worksheets
              for f in ("ohara-catalog-20250312-S-6dec.xlsx", "OHARA.xlsx")]
    # 6-digit sheet of recommended glasses first; the 5-digit file adds the low-Tg (moulding) glasses.
    for ws in sheets[0] + [w for w in sheets[1] if "low tg" in w.title.lower()]:
        status = "low Tg" if "low tg" in ws.title.lower() else "preferred"
        for g in _rows(ws, 3):
            name = g("B")
            c = [_num(g(x)) for x in ("BI", "BL", "BJ", "BM", "BK", "BN")]  # A1 B1 A2 B2 A3 B3
            if not isinstance(name, str) or None in c:
                continue
            out.append((name.strip(), 2, c, _num(g("Q")), _num(g("AA")), 0.365, 2.325, status))
    return out


def hoya(data):
    out = []
    ws = openpyxl.load_workbook(os.path.join(data, "HOYA20260401.xlsx"), read_only=True, data_only=True).worksheets[0]
    for g in _rows(ws, 5):
        name = g("C")
        pairs = [(_num(g(m)), _num(g(p))) for m, p in (("AE", "AF"), ("AG", "AH"), ("AI", "AJ"),
                                                         ("AK", "AL"), ("AM", "AN"), ("AO", "AP"))]
        if not isinstance(name, str) or any(m is None or p is None for m, p in pairs):
            continue
        c = [m * 10.0 ** p for m, p in pairs]  # A0..A5 of the Schott power series
        mark = str(g("A") or "").replace("※", "").strip()
        status = {"◎": "preferred", "〇": "preferred", "Ref.": "reference"}.get(mark, "standard")
        out.append((name.strip(), 1, c, _num(g("E")), _num(g("F")), 0.365, 1.5296, status))
    return out


def cdgm(data):
    out = []
    wb = openpyxl.load_workbook(os.path.join(data, "CDGM202409.xlsx"), read_only=True, data_only=True)
    for ws in wb.worksheets:
        if ws.title.strip().lower() not in ("optical glass", "i line glass"):
            continue  # the infrared sheet uses a different formula
        status = "i-line" if ws.title.lower().startswith("i line") else "preferred"
        for g in _rows(ws, 3):
            name = g("A")
            if not isinstance(name, str):
                continue
            k = [_num(g(x)) for x in ("AB", "AC", "AD", "AE", "AF", "AG")]  # K1 L1 K2 L2 K3 L3
            a = [_num(g(x)) for x in ("AH", "AI", "AJ", "AK", "AL", "AM")]  # A0..A5
            if None not in k:
                f, c = 2, k
            elif None not in a:
                f, c = 1, a
            else:
                continue
            lo = 0.30215 if _num(g("V")) else 0.31318 if _num(g("U")) else 0.36501
            out.append((name.strip(), f, c, _num(g("N")), _num(g("X")), lo, 2.32542, status))
    return out


def sumita(data):
    out = []
    ws = openpyxl.load_workbook(os.path.join(data, "glassdata_ver14.01.03_en.xlsx"), read_only=True, data_only=True).worksheets[0]
    for g in _rows(ws, 3):
        name = g("C")
        c = [_num(g(x)) for x in ("AV", "AW", "AX", "AY", "AZ", "BA")]
        if not isinstance(name, str) or None in c:
            continue
        out.append((name.strip(), 1, c, _num(g("P")), _num(g("D")), 0.365, 1.548, "preferred"))
    return out


def hikari(data):
    out = []
    ws = openpyxl.load_workbook(os.path.join(data, "hikari_general_catalog_data.xlsx"), read_only=True, data_only=True).worksheets[0]
    for g in _rows(ws, 4):
        name = g("A")
        c = [_num(g(x)) or 0.0 for x in ("BD", "BE", "BF", "BG", "BH", "BI", "BJ", "BK", "BL")]
        if not isinstance(name, str) or not _num(g("BD")):
            continue
        out.append((name.strip(), 13, c, _num(g("Q")), _num(g("Y")), 0.365, 2.058, "preferred"))
    return out


VENDORS = [("OHARA", ohara, "OHARA optical glass catalog data, 2025-03-12 (6-digit) + low-Tg glasses"),
           ("HOYA", hoya, "HOYA optical glass data table, 2026-04-01"),
           ("CDGM", cdgm, "CDGM optical glass data, 2024-09 (optical and i-line glass)"),
           ("SUMITA", sumita, "Sumita optical glass data, ver. 14.01.03 (2025-11-05)"),
           ("HIKARI", hikari, "Hikari (Nikon) general catalog data, 2023-09-01")]


def main(data):
    print('"""Glass catalogs of other makers: OHARA, HOYA, CDGM, Sumita and Hikari.')
    print()
    print("Generated by tools/gen_vendor_catalogs.py from the makers' own Excel data")
    print("sheets (as redistributed in the BSD-licensed opticalglass package):")
    for cat, _, src in VENDORS:
        print(f"  {cat}: {src}")
    print()
    print("Every glass was checked: its formula reproduces the catalog nd to 5e-5.")
    print('"""')
    print()
    print("# catalog: {name: (AGF formula, coefficients, nd, vd, lambda_min, lambda_max, status)}")
    print("VENDOR_CATALOGS = {")
    total = 0
    for cat, fn, _ in VENDORS:
        seen = set()
        print(f"    {cat!r}: {{")
        for name, f, c, nd, vd, lo, hi, status in fn(data):
            name = "".join(name.split())  # Zemax-style names have no spaces (L-BSL 7 -> L-BSL7)
            if name.upper() in seen or nd is None or vd is None:
                continue
            try:
                n = float(FORMULAS[f](LAMBDA_D, list(c) + [0.0] * 4))
            except (ValueError, ZeroDivisionError):
                n = float("nan")
            if not abs(n - nd) < 5e-5:
                print(f"skip {cat} {name}: formula nd {n:.6f} vs catalog {nd:.6f}", file=sys.stderr)
                continue
            seen.add(name.upper())
            coeffs = ", ".join(repr(float(x)) for x in c)
            print(f"        {name!r}: ({f}, ({coeffs}), {nd!r}, {vd!r}, {lo!r}, {hi!r}, {status!r}),")
        print("    },")
        total += len(seen)
        print(f"{cat}: {len(seen)} glasses", file=sys.stderr)
    print("}")
    print(f"total {total}", file=sys.stderr)


if __name__ == "__main__":
    main(sys.argv[1])
