"""The open lens of the web app: one OpticalSystem, its name in browser storage, and undo.

The Qt-free counterpart of lensforge_qt/document.py. Every edit goes through
:meth:`WebDocument.modify`, which snapshots the system before and after the change and pushes
one undo step; views always read :attr:`WebDocument.system` and redraw after a change.
"""

from __future__ import annotations

import json
import os
import traceback
from typing import Callable, List, Optional, Tuple

import lensforge as lf
from lensforge_qt.edits import finalize, new_system, same_lens


class WebDocument:
    def __init__(self, system=None):
        self.system = system if system is not None else new_system()
        self.path: Optional[str] = None   # name of the lens in browser storage (None: never saved there)
        self.import_name: Optional[str] = None
        self.undo_stack: List[Tuple[str, object, object]] = []  # (text, before, after)
        self.index = 0          # steps 0..index-1 are applied
        self.clean_index = 0    # index at the last save / open
        self.revision = 0       # increases on every change
        self.last_error = ""

    # -- editing --------------------------------------------------------------------
    def modify(self, text: str, fn: Callable[[object], None]) -> bool:
        """Apply ``fn(system)`` as one undoable edit. Returns False (and sets :attr:`last_error`)
        if ``fn`` raises; the lens is then left unchanged."""
        before = self.system.copy()
        try:
            fn(self.system)
            finalize(self.system)
        except Exception as e:  # restore and report
            self.system = before
            if os.environ.get("LENSFORGE_WEB_DEBUG"):
                traceback.print_exc()
            self.last_error = f"{text}: {str(e) or type(e).__name__}"
            self.revision += 1
            return False
        if same_lens(before, self.system):  # nothing changed: no undo step
            return True
        self._push(text, before, self.system.copy())
        return True

    def replace(self, text: str, new_system) -> None:
        """Replace the whole lens (optimisation result, Monte Carlo lens ...) as one undoable edit."""
        before = self.system.copy()
        self.system = new_system
        if not same_lens(before, new_system):
            self._push(text, before, new_system.copy())

    def _push(self, text, before, after):
        del self.undo_stack[self.index:]
        if self.clean_index > self.index:
            self.clean_index = -1  # the saved state can no longer be reached
        self.undo_stack.append((text, before, after))
        self.index += 1
        self.revision += 1

    def undo(self) -> bool:
        if self.index == 0:
            return False
        self.index -= 1
        self.system = self.undo_stack[self.index][1].copy()
        self.revision += 1
        return True

    def redo(self) -> bool:
        if self.index >= len(self.undo_stack):
            return False
        self.system = self.undo_stack[self.index][2].copy()
        self.index += 1
        self.revision += 1
        return True

    def undo_to(self, index: int):
        """Go to the state after ``index`` steps (0 = the lens as opened)."""
        index = max(0, min(int(index), len(self.undo_stack)))
        while self.index > index:
            self.undo()
        while self.index < index:
            self.redo()

    @property
    def undo_text(self) -> str:
        return self.undo_stack[self.index - 1][0] if self.index > 0 else ""

    @property
    def redo_text(self) -> str:
        return self.undo_stack[self.index][0] if self.index < len(self.undo_stack) else ""

    def refresh(self):
        """Tell every view to recompute (e.g. after a glass catalog was loaded)."""
        self.revision += 1

    # -- files ----------------------------------------------------------------------------
    def reset(self, system, path: Optional[str] = None, import_name: Optional[str] = None):
        """Start over with ``system`` (new, open, sample); clears undo."""
        finalize(system)
        self.system = system
        self.path = path
        self.import_name = import_name
        self.undo_stack = []
        self.index = self.clean_index = 0
        self.revision += 1

    def load_text(self, text: str, filename: str):
        """A lens from the text of a .json or .zmx file (with the front end's Input Rays settings)."""
        tmp = os.path.join("/tmp", "lensforge_web_" + os.path.basename(filename or "lens.json"))
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        try:
            system = lf.load(tmp)
        finally:
            try:
                os.remove(tmp)
            except OSError:
                pass
        if not filename.lower().endswith((".zmx", ".zos")):
            ui = json.loads(text).get("ui", {})
            if ui.get("input_rays"):
                system.input_rays = ui["input_rays"]
        return system

    def to_text(self) -> str:
        """The lens as .lens.json text (the Input Rays settings under "ui", as the Qt app writes it)."""
        d = self.system.to_dict()
        if getattr(self.system, "input_rays", None):
            d["ui"] = {"input_rays": self.system.input_rays}
        return json.dumps(d, indent=2)

    def set_clean(self):
        self.clean_index = self.index

    @property
    def modified(self) -> bool:
        return self.index != self.clean_index

    @property
    def display_name(self) -> str:
        if self.path:
            return self.path
        return self.import_name or self.system.name or "Untitled"
