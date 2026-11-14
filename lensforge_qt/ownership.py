"""Make sure Qt, not Python, owns the child widgets of our windows and dialogs.

Why this exists: PySide 6 loses track of ownership when a sub-layout is filled with widgets first
and only then added to a layout that already sits on a widget::

    lay = QVBoxLayout(self)
    row = QHBoxLayout()
    row.addWidget(QPushButton("Copy"))   # the button has no parent yet: Python owns it
    lay.addLayout(row)                   # Qt reparents the button, but PySide still thinks Python owns it

The button then has two owners: its C++ parent and its Python wrapper. While the app runs that is
harmless, but at interpreter shutdown PySide deletes every object it believes Python owns, and a
widget its parent already destroyed gets deleted a second time. That crashed the desktop app on
exit (SIGSEGV in ``QPushButtonWrapper::~QPushButtonWrapper`` under ``PySide::destroyQCoreApplication``).

:func:`hand_to_qt` walks a widget tree and gives every such child back to its parent, and
:func:`qt_owns_children` does that at the end of a class's ``__init__``. Calling
``setParent(parent)`` with the widget's own parent is a no-op for Qt (no hide, no change of tab order
or layout position) but makes PySide hand ownership to the parent.
"""

from __future__ import annotations

import functools

import shiboken6
from PySide6.QtWidgets import QWidget


def python_owned_children(root: QWidget) -> list:
    """Child widgets of *root* that have a Qt parent but that PySide still thinks Python owns."""
    out = []
    for w in root.findChildren(QWidget):
        if shiboken6.isValid(w) and not w.isWindow() and w.parentWidget() is not None and shiboken6.ownedByPython(w):
            out.append(w)
    return out


def hand_to_qt(root: QWidget) -> int:
    """Give every Python-owned child widget of *root* to its Qt parent; returns how many were fixed."""
    fixed = python_owned_children(root)
    for w in fixed:
        hidden = w.isHidden()
        w.setParent(w.parentWidget())
        if not hidden and w.isHidden():  # (defensive: same-parent setParent does not hide today)
            w.show()
    return len(fixed)


def qt_owns_children(cls):
    """Class decorator: run :func:`hand_to_qt` on the instance once its ``__init__`` has built it."""
    init = cls.__init__

    @functools.wraps(init)
    def __init__(self, *args, **kwargs):
        init(self, *args, **kwargs)
        hand_to_qt(self)  # (cheap and idempotent, so subclasses running it again is fine)

    cls.__init__ = __init__
    return cls
