"""Shared fonts.

Asking Qt for a family by a name that doesn't exist (e.g. "Monospace" on
macOS or Windows) makes it populate its font-alias table, which is slow
and logs a ``qt.qpa.fonts`` warning.  Ask the platform for its fixed-pitch
font instead.
"""
from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase


def fixed_font(size_from: QFont | None = None) -> QFont:
    """The system's fixed-pitch font, optionally at the point size of ``size_from``."""
    f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
    if size_from is not None and size_from.pointSizeF() > 0:
        f.setPointSizeF(size_from.pointSizeF())
    return f
