"""Toolbar/menu icons, drawn as small inline SVGs (24 x 24) so no image files are needed.

Every menu command has its own icon (``tests/test_qt_app.py`` checks that each command has one
and that no two commands share one). Keys follow help_text: menu paths, analysis registry keys
and sample lens names.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .help_text import ANALYSIS_PREFIX, SAMPLE_PREFIX, analysis_key

INK = "#1f5f99"     # outlines
GLASS = "#a8d4f0"   # lens fill
RED = "#d0453c"
GREEN = "#2e9e5b"
ORANGE = "#e08a00"
PURPLE = "#7a4fb5"
GREY = "#8a96a3"

# ------------------------------------------------------------------ building blocks
AXES = '<path d="M4 3v17h17"/>'
PAGE = '<path d="M5.5 2.5h9l4 4v15h-13z" fill="#fff"/><path d="M14.5 2.5v4h4"/>'
TABLE = ('<rect x="3" y="4" width="18" height="16" rx="1" fill="#fff"/>'
         '<path d="M3 9h18M3 14.5h18M9 4v16"/>')


def lens(cx=12.0, h=8.0, w=3.0, fill=GLASS):
    """Biconvex lens centred at (cx, 12), half-height h, half-thickness w."""
    return (f'<path d="M{cx} {12 - h}C{cx + w * 1.8} {12 - h / 2} {cx + w * 1.8} {12 + h / 2} {cx} {12 + h}'
            f'C{cx - w * 1.8} {12 + h / 2} {cx - w * 1.8} {12 - h / 2} {cx} {12 - h}z" fill="{fill}"/>')


def plus(x, y, c=GREEN, r=3.2):
    return (f'<circle cx="{x}" cy="{y}" r="{r + 0.8}" fill="#fff" stroke="none"/>'
            f'<path d="M{x - r} {y}h{2 * r}M{x} {y - r}v{2 * r}" stroke="{c}" stroke-width="2.2"/>')


def cross(x, y, c=RED, r=3.0):
    return (f'<circle cx="{x}" cy="{y}" r="{r + 1.2}" fill="#fff" stroke="none"/>'
            f'<path d="M{x - r} {y - r}l{2 * r} {2 * r}M{x + r} {y - r}l{-2 * r} {2 * r}" stroke="{c}" '
            'stroke-width="2.2"/>')


def letter(x, y, t, c=INK, size=9, weight="bold"):
    return (f'<text x="{x}" y="{y}" font-family="DejaVu Sans, Arial, sans-serif" font-size="{size}" '
            f'font-weight="{weight}" fill="{c}" stroke="none" text-anchor="middle">{t}</text>')


def floppy(extra=""):
    return ('<path d="M4 4h13l3 3v13H4z" fill="#fff"/><path d="M7.5 4v5h8V4"/>'
            '<rect x="7" y="13" width="10" height="7" fill="' + GLASS + '"/>' + extra)


ICONS = {
    # ------------------------------------------------------------------ File
    "File > New": PAGE + plus(16.5, 17),
    "File > Open": ('<path d="M3 6.5h6l2 2h9v11H3z" fill="#f6d78b"/>'
                    '<path d="M3 19.5l3-8h17l-3 8" fill="#fbe7b4"/>'),
    "File > Save": floppy(),
    "File > Save As": floppy(f'<path d="M14 21l1-3.5 6-6 2.5 2.5-6 6z" fill="{ORANGE}" stroke="{INK}"/>'),
    "File > Insert Lens": (lens(8, 7, 2.4) + '<path d="M2 12h20" stroke="' + GREY + '" stroke-dasharray="2 2"/>'
                           + f'<path d="M17 4v9m-3.5-3.5L17 13l3.5-3.5" stroke="{GREEN}" stroke-width="2.2"/>'
                           + f'<path d="M14 19h6" stroke="{GREEN}" stroke-width="2.2"/>'),
    "File > Inspect Lens File": (PAGE + '<path d="M8 7h5M8 10h3"/>'
                                 + f'<circle cx="13.5" cy="15" r="3.6" fill="{GLASS}"/>'
                                 + f'<path d="M16.2 17.7l4.3 4.3" stroke="{ORANGE}" stroke-width="2.6"/>'),
    "File > System Explorer": ('<path d="M4 6h16M4 12h16M4 18h16"/>'
                               f'<circle cx="8" cy="6" r="2.2" fill="{ORANGE}"/><circle cx="15" cy="12" r="2.2" '
                               f'fill="{GREEN}"/><circle cx="10" cy="18" r="2.2" fill="{RED}"/>'),
    "File > Fields": (f'<path d="M3 20V4" stroke="{GREY}"/><path d="M3 20l18-8M3 12l18 0M3 5l18 7"/>'
                      f'<circle cx="3.5" cy="20" r="1.8" fill="{GREEN}"/><circle cx="3.5" cy="12" r="1.8" '
                      f'fill="{ORANGE}"/><circle cx="3.5" cy="5" r="1.8" fill="{RED}"/>'),
    "File > Wavelengths": (f'<path d="M2 8c2-4 4-4 6 0s4 4 6 0 4-4 6 0" stroke="{RED}" stroke-width="1.8"/>'
                           f'<path d="M2 13c1.3-3 2.7-3 4 0s2.7 3 4 0 2.7-3 4 0 2.7 3 4 0" stroke="{GREEN}" '
                           'stroke-width="1.8"/><path d="M2 18c1-2 2-2 3 0s2 2 3 0 2-2 3 0 2 2 3 0 2-2 3 0 2 2 3 '
                           '0" stroke="#3b6fd8" stroke-width="1.8"/>'),
    "File > Input Rays": ('<path d="M2 5l18 7M2 12h18M2 19l18-7"/>'
                          f'<path d="M2 8.5l18 3.5M2 15.5l18-3.5" stroke="{RED}" stroke-dasharray="2 1.5"/>'
                          f'<circle cx="20.5" cy="12" r="1.8" fill="{ORANGE}"/>'),
    "File > Load Glass Catalog (AGF)": ('<path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z" fill="#fff"/>'
                                        '<path d="M5 18a2 2 0 0 1 2-2h12"/>'
                                        f'<path d="M9 13l3-6 3 6z" fill="{GLASS}"/>'),
    "File > Forget Loaded Glass Catalogs": ('<path d="M5 4h12a2 2 0 0 1 2 2v14H7a2 2 0 0 1-2-2z" fill="#fff"/>'
                                            '<path d="M5 18a2 2 0 0 1 2-2h12"/>'
                                            f'<path d="M9 8l6 6M15 8l-6 6" stroke="{RED}" stroke-width="2"/>'),
    "File > Export Prescription": (PAGE + '<path d="M8 10h6M8 13h6M8 16h3"/>'
                                   f'<path d="M14 18h8m-3-3 3 3-3 3" stroke="{GREEN}" stroke-width="2"/>'),
    "File > Exit": ('<path d="M13 3H5v18h8"/><path d="M5 3l6 2v16l-6 0" fill="' + GLASS + '"/>'
                    f'<path d="M14 12h8m-3-3 3 3-3 3" stroke="{RED}" stroke-width="2"/>'),

    # ------------------------------------------------------------------ Edit
    "Edit > Undo": '<path d="M9 3.5L4 8.5l5 5" stroke-width="2"/><path d="M4 8.5h10a5.5 5.5 0 0 1 0 11H9" stroke-width="2"/>',
    "Edit > Redo": '<path d="M15 3.5l5 5-5 5" stroke-width="2"/><path d="M20 8.5H10a5.5 5.5 0 0 0 0 11h5" stroke-width="2"/>',
    "Edit > Undo History": ('<circle cx="13" cy="12" r="8" fill="#fff"/><path d="M13 7v5l3.5 2"/>'
                            f'<path d="M2 9l3 3 3-3" stroke="{ORANGE}" stroke-width="2"/>'),
    "Edit > Insert Surface": TABLE + plus(16, 6.6, r=2.8),
    "Edit > Insert Surface After": TABLE + plus(16, 17.3, r=2.8),
    "Edit > Delete Surface": TABLE + cross(16, 11.8),
    "Edit > Delete Surfaces": (TABLE + f'<rect x="3.6" y="9.6" width="16.8" height="10" fill="#f6c6c2" stroke="none"/>'
                               + '<path d="M3 14.5h18M9 9v11"/>' + cross(16.5, 14.5, r=2.6)
                               + f'<path d="M1.5 9.5v10" stroke="{RED}" stroke-width="1.6"/>'),
    "Edit > Toggle Variable": ('<rect x="3" y="5" width="18" height="14" rx="2" fill="#fff"/>'
                               + letter(12, 16.5, "V", ORANGE, 11)),
    "Edit > Choose Material": (f'<path d="M3 20L10 4l7 16z" fill="{GLASS}"/>'
                               f'<path d="M14 11l8-2" stroke="{RED}"/><path d="M14.5 12.5l7.5 0" stroke="{GREEN}"/>'
                               '<path d="M15 14l7 2" stroke="#3b6fd8"/>'),
    "Edit > Surface Properties": ('<path d="M7 3c4 5 4 13 0 18" stroke-width="2"/>'
                                  f'<circle cx="16" cy="12" r="5.5" fill="#fff" stroke="{INK}"/>'
                                  + letter(16, 15.5, "i", INK, 9)),
    "Edit > Quick Focus (paraxial)": ('<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2.5" '
                                      f'fill="{RED}" stroke="{RED}"/><path d="M12 1.5v4M12 18.5v4M1.5 12h4M18.5 12h4"/>'),
    "Edit > Fix Semi-Diameters at Current Values": (lens(8, 9, 2.5) + f'<path d="M8 3v18" stroke="{ORANGE}"/>'
                                                    f'<rect x="14" y="11" width="8" height="7" rx="1" fill="{ORANGE}"/>'
                                                    '<path d="M15.5 11V9a2.5 2.5 0 0 1 5 0v2"/>'),
    "Edit > Make All Semi-Diameters Automatic": (lens(8, 9, 2.5) + f'<path d="M8 3v18" stroke="{GREEN}"/>'
                                                 + letter(18, 16, "A", GREEN, 11)),

    # ------------------------------------------------------------------ Analysis window commands
    "Analysis > Tab All Analysis Windows": ('<path d="M3 8h18v12H3z" fill="#fff"/><path d="M3 8V4h6v4M9 8V5h6v3"/>'
                                            f'<path d="M15 8V5h6v3" stroke="{ORANGE}"/>'),
    "Analysis > Close All Analysis Windows": ('<rect x="6" y="3" width="15" height="12" fill="#fff"/>'
                                              '<rect x="3" y="7" width="15" height="12" fill="#fff"/>'
                                              + cross(17, 17)),

    # ------------------------------------------------------------------ Tools
    "Tools > Optimization": ('<path d="M2 5c4 0 5 14 10 14s6-9 10-11" stroke-width="1.8"/>'
                             f'<circle cx="12" cy="17" r="2.6" fill="{RED}" stroke="{RED}"/>'
                             f'<path d="M5.5 6.5l3 6" stroke="{GREEN}" stroke-width="2"/>'),
    "Tools > Tolerancing": (letter(12, 18, "±", INK, 20, "normal")
                            + f'<path d="M4 21h16" stroke="{ORANGE}" stroke-width="2"/>'),
    "Tools > Python Shell": ('<rect x="2.5" y="4" width="19" height="16" rx="2" fill="#263238" stroke="#263238"/>'
                             '<path d="M6 9l3 3-3 3" stroke="#7fe08a" stroke-width="2"/>'
                             '<path d="M11 16h6" stroke="#ffd54f" stroke-width="2"/>'),
    "Tools > Merit Function Editor": TABLE + f'<path d="M12 12l2 2 5-5" stroke="{GREEN}" stroke-width="2.2"/>',
    "Tools > Variables and Solves > Make All Curvatures Variable": ('<path d="M4 3c5 5 5 13 0 18M9 3c5 5 5 13 0 18" '
                                                                    'stroke-width="1.8"/>'
                                                                    + letter(18, 16, "V", ORANGE, 11)),
    "Tools > Variables and Solves > Make All Air Spaces Variable": ('<path d="M3 3v18M11 3v18" stroke-width="1.8"/>'
                                                                    '<path d="M3.5 12h7m-2-2 2 2-2 2m-3-4-2 2 2 2" '
                                                                    f'stroke="{GREY}"/>' + letter(17.5, 16, "V", ORANGE, 11)),
    "Tools > Variables and Solves > Remove All Variables": letter(10, 17, "V", ORANGE, 14) + cross(17, 15),
    "Tools > Variables and Solves > Remove All Solves": letter(10, 17, "S", PURPLE, 14) + cross(17, 15),

    # ------------------------------------------------------------------ View
    "View > Show Toolbar": ('<rect x="3" y="4" width="18" height="16" rx="1" fill="#fff"/>'
                            f'<rect x="3" y="4" width="18" height="5" fill="{GLASS}"/>'
                            '<path d="M6 6.5h2M10 6.5h2M14 6.5h2"/>'),
    "View > Customize Toolbar": ('<rect x="3" y="4" width="18" height="16" rx="1" fill="#fff"/>'
                                 f'<rect x="3" y="4" width="18" height="5" fill="{GLASS}"/>'
                                 f'<path d="M10 21l1-3.5 6-6 2.5 2.5-6 6z" fill="{ORANGE}"/>'),

    # ------------------------------------------------------------------ Help
    "Help > Help Contents": (f'<circle cx="12" cy="12" r="9.5" fill="{INK}"/>' + letter(12, 16.5, "?", "#fff", 13)),
    "Help > What's This?": ('<path d="M4 3v15l4-4 3 6 2.5-1-3-6h5.5z" fill="#fff"/>'
                            + letter(18.5, 11, "?", RED, 11)),
    "Help > Keyboard Shortcuts": ('<rect x="2" y="6" width="20" height="13" rx="2" fill="#fff"/>'
                                  '<path d="M5 10h1M8 10h1M11 10h1M14 10h1M17 10h2M5 13h1M8 13h1M11 13h1M14 13h1'
                                  'M17 13h2M7 16h10" stroke-width="1.8"/>'),
    "Help > About": ('<circle cx="12" cy="12" r="9.5" fill="#fff"/>' + letter(12, 17, "i", INK, 13)),
}
ICONS["View > Undo History"] = ICONS["Edit > Undo History"]  # the same command in two menus

ANALYSIS_ICONS = {
    "layout": (lens(9, 8, 2.4) + '<path d="M2 5h7l12 7M2 12h19M2 19h7l12-7" stroke-width="1.2"/>'
               f'<path d="M2 8h7l12 4M2 16h7l12-4" stroke="{RED}" stroke-width="1.2"/>'),
    "footprint": ('<circle cx="12" cy="12" r="9" fill="#fff"/>'
                  + "".join(f'<circle cx="{x}" cy="{y}" r="0.9" fill="{GREEN}" stroke="none"/>'
                            for x in (8, 12, 16) for y in (8, 12, 16))
                  + f'<circle cx="13" cy="10" r="6" stroke="{RED}" stroke-dasharray="2 1.5"/>'),
    "sag": (f'<path d="M3 20h18" stroke="{GREY}"/><path d="M3 20c6-1 9-6 12-15" stroke-width="2"/>'
            f'<path d="M19 5v15m-2-13 2-2 2 2m-4 11 2 2 2-2" stroke="{ORANGE}"/>'),
    "ray_fan": (f'<path d="M3 12h18M12 3v18" stroke="{GREY}"/>'
                '<path d="M3 4c4 0 5 8 9 8s5-8 9-8" stroke-width="1.8"/>'
                f'<path d="M3 20c4-2 6-8 9-8s5 6 9 8" stroke="{RED}" stroke-width="1.4"/>'),
    "opd_fan": (f'<path d="M3 12h18M12 3v18" stroke="{GREY}"/>'
                '<path d="M3 5c3 14 6 7 9 7s6 7 9-7" stroke-width="1.8"/>'
                + letter(6, 21, "λ", ORANGE, 8)),
    "spot": "".join(f'<circle cx="{x}" cy="{y}" r="1.1" fill="{c}" stroke="none"/>'
                    for x, y, c in ((12, 12, INK), (9, 10, INK), (15, 10, INK), (10, 15, INK), (14, 14, INK),
                                    (12, 7, GREEN), (7, 13, GREEN), (17, 13, GREEN), (12, 17, RED),
                                    (8.5, 7.5, RED), (16, 7, RED), (5, 10, GREEN), (19, 16, RED), (11, 20, GREEN)))
            + '<circle cx="12" cy="12" r="9.5" stroke-dasharray="1.5 2" stroke="' + GREY + '"/>',
    "through_focus_spot": "".join(f'<circle cx="{x}" cy="12" r="{r}" stroke="{INK}" stroke-dasharray="1 1.4"/>'
                                  f'<circle cx="{x}" cy="12" r="0.9" fill="{RED}" stroke="none"/>'
                                  for x, r in ((4.5, 3.5), (12, 1.6), (19.5, 3.5))),
    "rms_vs_field": (AXES + '<path d="M4 17c6 0 11-2 16-12" stroke-width="1.8"/>'
                     f'<circle cx="9" cy="16" r="1.4" fill="{ORANGE}"/><circle cx="15" cy="12.5" r="1.4" '
                     f'fill="{ORANGE}"/><circle cx="19.5" cy="6" r="1.4" fill="{ORANGE}"/>'),
    "wavefront": (f'<circle cx="12" cy="12" r="9.5" fill="#3b6fd8" stroke="{INK}"/>'
                  f'<circle cx="12" cy="12" r="6.5" fill="{GREEN}" stroke="none"/>'
                  '<circle cx="12" cy="12" r="3.5" fill="#f2d32c" stroke="none"/>'
                  f'<circle cx="12" cy="12" r="1.4" fill="{RED}" stroke="none"/>'),
    "interferogram": ('<circle cx="12" cy="12" r="9.5" fill="#fff"/>'
                      '<path d="M6 4.5c2 5 2 10 0 15M10 2.7c2 6 2 12.6 0 18.6M14 2.7c-2 6-2 12.6 0 18.6'
                      'M18 4.5c-2 5-2 10 0 15" stroke="#222" stroke-width="1.8"/>'),
    "zernike": (f'<path d="M3 13h18" stroke="{GREY}"/>'
                f'<path d="M5 13V5M9 13v4M13 13V9M17 13v6" stroke="{INK}" stroke-width="3"/>'
                f'<path d="M20 13v-2" stroke="{ORANGE}" stroke-width="3"/>'),
    "zernike_text": PAGE + letter(12, 18, "Z", INK, 11),
    "psf": ('<circle cx="12" cy="12" r="9.5" stroke="' + GREY + '" stroke-width="0.9"/>'
            '<circle cx="12" cy="12" r="6.5" stroke="' + GREY + '" stroke-width="1.2"/>'
            f'<circle cx="12" cy="12" r="3.2" fill="#f2d32c" stroke="{ORANGE}"/>'
            f'<circle cx="12" cy="12" r="1.3" fill="{RED}" stroke="none"/>'),
    "psf_cross": (f'<path d="M3 20h18" stroke="{GREY}"/>'
                  '<path d="M3 19.5c3 0 4.5-.5 5.5-3S10.5 3 12 3s2.5 11 3.5 13.5 2.5 3 5.5 3" stroke-width="1.8"/>'
                  f'<path d="M12 3v17" stroke="{RED}" stroke-dasharray="1.5 1.5"/>'),
    "mtf": (AXES + '<path d="M4 4c6 1 10 7 16 14" stroke-width="1.8"/>'
            f'<path d="M4 4c5 3 8 9 15 15" stroke="{RED}" stroke-dasharray="2 1.5"/>'),
    "through_focus_mtf": (AXES + '<path d="M4 18c4 0 5-12 8-12s4 12 8 12" stroke-width="1.8"/>'
                          f'<path d="M12 4v16" stroke="{ORANGE}" stroke-dasharray="1.5 1.5"/>'),
    "mtf_vs_field": (AXES + '<path d="M4 6c6 0 11 1 16 4" stroke-width="1.8"/>'
                     f'<path d="M4 11c6 0 11 2 16 6" stroke="{GREEN}" stroke-width="1.8"/>'
                     f'<path d="M4 14c6 1 10 3 16 5" stroke="{RED}" stroke-dasharray="2 1.5"/>'),
    "encircled_energy": (AXES + '<path d="M4 19c4 0 4-14 9-14h8" stroke-width="1.8"/>'
                         f'<circle cx="17" cy="14" r="3.5" stroke="{ORANGE}" fill="#fff"/>'
                         f'<circle cx="17" cy="14" r="1" fill="{ORANGE}" stroke="none"/>'),
    "field_curvature": (f'<path d="M3 20h8M3 3v17" stroke="{GREY}"/>'
                        '<path d="M3 20c3-5 4-11 4-17" stroke-width="1.8"/>'
                        f'<path d="M3 20c1.5-5 2-11 1.5-17" stroke="{RED}" stroke-dasharray="2 1.2"/>'
                        f'<path d="M14 3v17h7" stroke="{GREY}"/><path d="M14 20c3-3 4-9 5-17" stroke="{GREEN}" '
                        'stroke-width="1.8"/>'),
    "grid_distortion": (f'<path d="M4 4h16v16H4zM4 12h16M12 4v16" stroke="{GREY}" stroke-dasharray="1.5 1.5"/>'
                        '<path d="M5 5q7 3 14 0q-3 7 0 14q-7-3-14 0q3-7 0-14z" stroke-width="1.6"/>'
                        '<path d="M5.5 12h13M12 5.5v13" stroke-width="1.2"/>'),
    "lateral_color": (AXES + f'<path d="M4 20l16-14" stroke="{RED}" stroke-width="1.6"/>'
                      f'<path d="M4 20l16-9" stroke="{GREEN}" stroke-width="1.6"/>'
                      '<path d="M4 20l16-4" stroke="#3b6fd8" stroke-width="1.6"/>'),
    "longitudinal": (f'<path d="M3 20h18M12 3v17" stroke="{GREY}"/>'
                     '<path d="M12 20c0-6 2-9 5-15" stroke-width="1.8"/>'
                     f'<path d="M10 20c0-6 1-9 2-15" stroke="{RED}" stroke-width="1.6"/>'
                     '<path d="M14 20c0-6 3-9 7-15" stroke="#3b6fd8" stroke-width="1.6"/>'),
    "focal_shift": (AXES + '<path d="M8 4c10 4 10 12 0 16" stroke-width="1.8"/>'
                    f'<path d="M8 4h0" stroke="{RED}" stroke-width="3"/>'
                    f'<circle cx="15.5" cy="12" r="1.5" fill="{GREEN}" stroke="none"/>'),
    "seidel": (f'<path d="M3 20h18" stroke="{GREY}"/>'
               f'<path d="M5 20v-8M12 20v-14M19 20v-5" stroke="{INK}" stroke-width="3"/>'
               f'<path d="M5 12V9M12 6V4M19 15v-6" stroke="{ORANGE}" stroke-width="3"/>'
               f'<path d="M5 9V7M19 9V6" stroke="{GREEN}" stroke-width="3"/>'),
    "seidel_text": PAGE + letter(12, 18.5, "Σ", INK, 11),
    "pupil_aberration": ('<circle cx="12" cy="12" r="9.5" fill="#fff"/>'
                         '<path d="M7 7l2 1M17 7l-2 1M7 17l2-1M17 17l-2-1M12 5v2M12 19v-2M5 12h2M19 12h-2" '
                         f'stroke="{RED}" stroke-width="1.6"/><circle cx="12" cy="12" r="1.2" fill="{INK}"/>'),
    "relative_illumination": (AXES + '<path d="M4 6c7 0 12 3 16 11" stroke-width="1.8"/>'
                              f'<circle cx="16" cy="6" r="2.2" fill="#f2d32c" stroke="{ORANGE}"/>'
                              f'<path d="M16 1.5v1.2M16 9.3v1.2M11.5 6h1.2M19.3 6h1.2" stroke="{ORANGE}"/>'),
    "vignetting": (f'<circle cx="10" cy="12" r="7.5" fill="{GLASS}"/>'
                   f'<circle cx="15" cy="12" r="7.5" stroke="{RED}" stroke-dasharray="2 1.5"/>'
                   f'<path d="M12.5 5a7.5 7.5 0 0 1 0 14a7.5 7.5 0 0 1 0-14z" fill="{INK}" stroke="none" opacity="0.6"/>'),
    "polarization_pupil": ('<circle cx="12" cy="12" r="9.5" fill="#fff"/>'
                           + "".join(f'<ellipse cx="{x}" cy="{y}" rx="2" ry="0.8" transform="rotate({a} {x} {y})" '
                                     f'stroke="{PURPLE}"/>' for x, y, a in ((8, 8, 30), (16, 8, -30), (12, 12, 0),
                                                                           (8, 16, -30), (16, 16, 30)))),
    "transmission": (f'<rect x="9" y="3" width="6" height="18" fill="{GLASS}"/>'
                     f'<path d="M1.5 12h7" stroke="{ORANGE}" stroke-width="3"/>'
                     f'<path d="M15 12h5m-2.5-2.5L20 12l-2.5 2.5" stroke="{ORANGE}" stroke-width="1.5"/>'),
    "prescription": PAGE + '<path d="M8 10h7M8 13h7M8 16h7M11.5 9v8"/>',
    "system_report": PAGE + f'<path d="M8.5 18v-3M11.5 18v-6M14.5 18v-4" stroke="{GREEN}" stroke-width="2"/>',
    "ray_trace": (TABLE + f'<path d="M2 21l9-5 11-11" stroke="{RED}" stroke-width="1.8"/>'),
    "user_rays": (lens(12, 8, 2.4) + '<path d="M2 12h20" stroke="' + GREY + '"/>'
                  f'<path d="M2 6l10 1 9 8" stroke="{RED}" stroke-dasharray="2.2 1.5" stroke-width="1.6"/>'
                  + plus(5, 18, ORANGE, 2.4)),
    "cardinal_points": ('<path d="M2 12h20"/><path d="M8 7v10M14 7v10" stroke-dasharray="1.5 1.5"/>'
                        f'<circle cx="4" cy="12" r="1.6" fill="{RED}"/><circle cx="20" cy="12" r="1.6" fill="{RED}"/>'
                        + letter(8, 5.5, "H", INK, 6) + letter(14, 5.5, "H′", INK, 6)),
    "dispersion": (f'<path d="M3 20L9 6l6 14z" fill="{GLASS}"/><path d="M1 13h5" stroke="#999"/>'
                   f'<path d="M12 12l10-6" stroke="{RED}"/><path d="M12.4 13l9.6-3" stroke="{ORANGE}"/>'
                   f'<path d="M12.8 14l9.2 0" stroke="{GREEN}"/><path d="M13.2 15l8.8 3" stroke="#3b6fd8"/>'
                   f'<path d="M13.6 16l8.4 5" stroke="{PURPLE}"/>'),
}

SAMPLE_ICONS = {
    "Singlet": lens(12, 9, 3),
    "Cemented Achromat": ('<path d="M10 3c3.5 3 3.5 15 0 18c-1.8-3-1.8-15 0-18z" fill="' + GLASS + '"/>'
                          '<path d="M10 3c-1.8 3-1.8 15 0 18h5c-1-3-1-15 0-18z" fill="#6aa9d6"/>'),
    "Parabolic Mirror": ('<path d="M18 3c-4 4-4 14 0 18" stroke-width="2.4"/>'
                         f'<path d="M2 6h14.5L6 12M2 18h14.5L6 12" stroke="{RED}" stroke-width="1.2"/>'),
    "Classical Cassegrain": ('<path d="M19 3c-3 4-3 14 0 18" stroke-width="2.4"/><path d="M8 9c-1 2-1 4 0 6" '
                             f'stroke-width="2.4"/><path d="M2 5h15.5L8 9.5l13 2.5" stroke="{RED}" stroke-width="1.1"/>'),
    "Cooke Triplet (optimised)": (lens(5, 8, 1.8) + '<path d="M12 5.5c-1.5 3-1.5 10 0 13h1.6c1.5-3 1.5-10 0-13z" '
                                  'fill="#6aa9d6"/>' + lens(20, 8, 1.8)),
    "Scripted Singlet": lens(8, 8, 2.6) + letter(18, 15, "{}", PURPLE, 10),
    "Diffraction Grating Demo": ('<path d="M7 3v18" stroke-width="2.4" stroke-dasharray="1 1"/>'
                                 f'<path d="M1 12h6" stroke="#999"/><path d="M7 12l15-8" stroke="{RED}"/>'
                                 f'<path d="M7 12h15" stroke="{GREY}"/><path d="M7 12l15 8" stroke="#3b6fd8"/>'),
    "Spot Size Merit Example": (lens(7, 8, 2.2) + '<path d="M2 5h5l11 7M2 19h5l11-7" stroke-width="1.1"/>'
                                f'<circle cx="19" cy="12" r="2.6" stroke="{RED}" stroke-width="1.4"/>'
                                f'<circle cx="19" cy="12" r="0.8" fill="{RED}" stroke="none"/>'),
}


def svg(item_id: str) -> Optional[str]:
    """The SVG markup of a command's icon, or None."""
    body = ICONS.get(item_id)
    if body is None and item_id.startswith(SAMPLE_PREFIX):
        body = SAMPLE_ICONS.get(item_id[len(SAMPLE_PREFIX):])
    if body is None and item_id.startswith(ANALYSIS_PREFIX):
        body = ANALYSIS_ICONS.get(analysis_key(item_id))
    if body is None:
        return None
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="24" height="24" fill="none" '
            f'stroke="{INK}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">{body}</svg>')


def render(markup: str, size: int = 64) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(markup.encode())).render(p, QRectF(0, 0, size, size))
    p.end()
    return img


def icon(item_id: str) -> QIcon:
    """QIcon for a command (empty icon when there is none)."""
    markup = svg(item_id)
    ic = QIcon()
    if markup:
        for size in (16, 24, 32, 48, 64):
            ic.addPixmap(QPixmap.fromImage(render(markup, size)))
    return ic


# ------------------------------------------------------------------ application icon
# "Forge": a lens glowing like hot metal above an anvil (chosen by Joe, 2026-10-24).
APP_ICON = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" xmlns:c2pa="http://c2pa.org/manifest">'
    '<metadata>'
    '<c2pa:manifest>'
    '</c2pa:manifest>'
    '</metadata>'
    '<defs>'
    '<linearGradient id="g-bg" x1="0" y1="0" x2="0" y2="1">'
    '<stop offset="0" stop-color="#2a1a14"/>'
    '<stop offset="1" stop-color="#120b08"/>'
    '</linearGradient>'
    '<radialGradient id="g-hot" cx=".5" cy=".5">'
    '<stop offset="0" stop-color="#fff3c4"/>'
    '<stop offset=".45" stop-color="#ffb23a"/>'
    '<stop offset="1" stop-color="#e2541c"/>'
    '</radialGradient>'
    '<radialGradient id="g-halo">'
    '<stop offset="0" stop-color="#ff8a2a" stop-opacity=".55"/>'
    '<stop offset="1" stop-color="#ff8a2a" stop-opacity="0"/>'
    '</radialGradient>'
    '</defs>'
    '<rect width="256" height="256" rx="56" fill="url(#g-bg)"/>'
    '<circle cx="128" cy="100" r="92" fill="url(#g-halo)"/>'
    '<path d="M44 100H212" stroke="#ffcf7a" stroke-width="4" stroke-dasharray="10 9" opacity=".7"/>'
    '<path d="M128 38C158.6 69.0 158.6 131.0 128 162C97.4 131.0 97.4 69.0 128 38z" fill="url(#g-hot)" stroke="#fff0c8" stroke-width="3"/>'
    '<path d="M58 178H198L184 194H150V212H176V224H80V212H106V194H72z" fill="#4a3f3a" stroke="#6e625c" stroke-width="3" stroke-linejoin="round"/>'
    '<path d="M58 178H198" stroke="#9a8e86" stroke-width="5" stroke-linecap="round"/>'
    '</svg>'
)


def app_icon() -> QIcon:
    """The LensForge window/taskbar icon, rendered at the usual platform sizes."""
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(render(APP_ICON, size)))
    return ic
