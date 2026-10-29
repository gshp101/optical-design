"""The open lens: one OpticalSystem, its file name, and an undo stack.

Every edit made through the UI goes through :meth:`LensDocument.modify`,
which snapshots the system before and after the change and pushes one undo
command.  Views never cache ``document.system``: undo replaces the object, so
they always read it from the document and redraw on :attr:`changed`.
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Callable, Optional

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QUndoCommand, QUndoStack

import lensforge as lf
from lensforge import optimize as opt


def finalize(system):
    """Re-apply solves after an edit, as a lens data editor does."""
    if getattr(system, "solves", None):
        try:
            opt.apply_solves(system)
        except Exception:  # a solve that cannot be met leaves the old value
            pass


class _SnapshotCommand(QUndoCommand):
    def __init__(self, doc: "LensDocument", text: str, before, after):
        super().__init__(text)
        self.doc, self.before, self.after = doc, before, after
        self._first = True

    def redo(self):
        if self._first:  # the change is already applied
            self._first = False
            return
        self.doc._set_system(self.after.copy())

    def undo(self):
        self.doc._set_system(self.before.copy())


class LensDocument(QObject):
    #: emitted after every change of the lens (edits, undo, redo, open)
    changed = Signal()
    #: emitted when the file name or the modified flag changes
    titleChanged = Signal()
    #: emitted with a message when an edit is rejected
    error = Signal(str)
    #: emitted after a different lens replaced the old one (open, new, sample)
    opened = Signal()

    def __init__(self, system=None, parent=None):
        super().__init__(parent)
        self.system = system if system is not None else new_system()
        self.path: Optional[str] = None
        self.undo_stack = QUndoStack(self)
        self.undo_stack.cleanChanged.connect(self._clean_changed)
        self.revision = 0  # increases on every change (analysis windows use it to drop stale results)

    def _clean_changed(self, _clean):
        self.titleChanged.emit()

    # -- editing --------------------------------------------------------------
    def modify(self, text: str, fn: Callable[[object], None]) -> bool:
        """Apply ``fn(system)`` as one undoable edit.  Returns False (and emits
        :attr:`error`) if ``fn`` raises; the lens is then left unchanged."""
        before = self.system.copy()
        try:
            fn(self.system)
            finalize(self.system)
        except Exception as e:  # restore and report
            self.system = before
            msg = str(e) or type(e).__name__
            if os.environ.get("LENSFORGE_QT_DEBUG"):
                traceback.print_exc()
            self.error.emit(f"{text}: {msg}")
            self._bump()
            return False
        if _same(before, self.system):  # nothing changed: no undo step
            return True
        self.undo_stack.push(_SnapshotCommand(self, text, before, self.system.copy()))
        self._bump()
        return True

    def replace(self, text: str, new_system) -> None:
        """Replace the whole lens (optimisation result, sample, ...) as one undoable edit."""
        before = self.system.copy()
        self.system = new_system
        if _same(before, new_system):
            return
        self.undo_stack.push(_SnapshotCommand(self, text, before, new_system.copy()))
        self._bump()

    def _set_system(self, system):
        self.system = system
        self._bump()

    def _bump(self):
        self.revision += 1
        self.changed.emit()

    def refresh(self):
        """Tell every view to recompute, e.g. after a glass catalog was loaded."""
        self._bump()

    # -- files ------------------------------------------------------------------
    def open(self, path: str):
        system = lf.load(path)
        if not path.lower().endswith((".zmx", ".zos")):
            with open(path, encoding="utf-8") as f:
                ui = json.load(f).get("ui", {})
            if ui.get("input_rays"):
                system.input_rays = ui["input_rays"]
        finalize(system)
        self.system = system
        self.path = path if not path.lower().endswith((".zmx", ".zos")) else None
        if self.path is None:
            self._import_name = os.path.splitext(os.path.basename(path))[0]
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._bump()
        self.opened.emit()
        self.titleChanged.emit()

    def save(self, path: Optional[str] = None):
        path = path or self.path
        if not path:
            raise ValueError("No file name")
        d = self.system.to_dict()
        if getattr(self.system, "input_rays", None):
            d["ui"] = {"input_rays": self.system.input_rays}  # front-end settings; ignored by lensforge.load
        with open(path, "w", encoding="utf-8") as f:
            json.dump(d, f, indent=2)
        self.path = path
        self.undo_stack.setClean()
        self.titleChanged.emit()

    def reset(self, system, path: Optional[str] = None):
        """Start over with ``system`` (File > New, samples); clears undo."""
        finalize(system)
        self.system = system
        self.path = path
        self.undo_stack.clear()
        self.undo_stack.setClean()
        self._bump()
        self.opened.emit()
        self.titleChanged.emit()

    @property
    def modified(self) -> bool:
        return not self.undo_stack.isClean()

    @property
    def display_name(self) -> str:
        if self.path:
            return os.path.basename(self.path)
        return getattr(self, "_import_name", None) or self.system.name or "Untitled"


def _same(a, b) -> bool:
    if getattr(a, "input_rays", None) != getattr(b, "input_rays", None):
        return False
    try:
        return a.to_dict() == b.to_dict()
    except Exception:  # unserialisable content (USER operands): assume changed
        return False


def new_system():
    """The empty lens of File > New: object at infinity, a stop, the image."""
    s = lf.OpticalSystem("New lens")
    s.set_aperture("EPD", 10.0)
    s.set_fields([0.0])
    s.set_wavelengths([0.5875618])
    s.add_surface(radius=float("inf"), thickness=0.0, stop=True)
    return s
