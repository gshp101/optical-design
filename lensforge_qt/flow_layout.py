"""A layout that lays its items out in rows and wraps them onto the next row when space runs out.

Used for the settings bar of analysis windows: a plain QHBoxLayout makes the window's minimum width
the sum of all its controls (well over 1000 pixels for MTF or PSF), so a docked analysis window
could not be made narrower and pushed the Lens Data Editor off screen. A flow layout's minimum width
is that of its widest single item; narrower windows just wrap the controls onto more rows.
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, QSize, Qt
from PySide6.QtWidgets import QHBoxLayout, QLayout, QSizePolicy, QWidget


class FlowLayout(QLayout):
    def __init__(self, parent=None, margin=2, hspacing=6, vspacing=2):
        super().__init__(parent)
        self._items = []
        self._h, self._v = hspacing, vspacing
        self.setContentsMargins(margin, margin, margin, margin)

    # -- QLayout interface -------------------------------------------------------
    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientation(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._do_layout(QRect(0, 0, width, 0), test=True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._do_layout(rect, test=False)

    def sizeHint(self):
        # preferred: everything on one row
        m = self.contentsMargins()
        vis = [it for it in self._items if not it.isEmpty()]
        w = sum(it.sizeHint().width() for it in vis) + self._h * max(0, len(vis) - 1)
        h = max((it.sizeHint().height() for it in vis), default=0)
        return QSize(w + m.left() + m.right(), h + m.top() + m.bottom())

    def minimumSize(self):
        # the widest single item: anything narrower than that cannot be laid out at all
        m = self.contentsMargins()
        s = QSize()
        for it in self._items:
            if not it.isEmpty():
                s = s.expandedTo(it.minimumSize())
        return s + QSize(m.left() + m.right(), m.top() + m.bottom())

    # -- layout ------------------------------------------------------------------
    def _do_layout(self, rect, test):
        m = self.contentsMargins()
        r = rect.adjusted(m.left(), m.top(), -m.right(), -m.bottom())
        x, y, row_h = r.x(), r.y(), 0
        row = []  # (item, x, size) of the current row, placed once its height is known

        def flush():
            for it, ix, sz in row:
                it.setGeometry(QRect(QPoint(ix, y + (row_h - sz.height()) // 2), sz))

        for it in self._items:
            if it.isEmpty():
                continue
            sz = it.sizeHint().boundedTo(QSize(max(1, r.width()), 1 << 20)).expandedTo(it.minimumSize())
            if row and x + sz.width() > r.right() + 1:
                if not test:
                    flush()
                row = []
                x = r.x()
                y += row_h + self._v
                row_h = 0
            row.append((it, x, sz))
            x += sz.width() + self._h
            row_h = max(row_h, sz.height())
        if not test:
            flush()
        return y + row_h - rect.y() + m.bottom()


def group(*widgets, spacing=3):
    """Keep *widgets* (a label and its control) together on one row of a :class:`FlowLayout`."""
    box = QWidget()
    lay = QHBoxLayout(box)
    lay.setContentsMargins(0, 0, 0, 0)
    lay.setSpacing(spacing)
    for w in widgets:
        lay.addWidget(w)
    box.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
    return box
