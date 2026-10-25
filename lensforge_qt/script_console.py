"""Python script console: run lensforge code against the open lens.

The script sees ``lens`` (the open OpticalSystem), ``lf`` (lensforge), ``opt``
(lensforge.optimize) and ``np``.  Changes it makes to ``lens`` become one
undoable edit; ``print`` output goes to the output pane.
"""

from __future__ import annotations

import contextlib
import io
import traceback

import numpy as np
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QSplitter, QVBoxLayout, QWidget
from PySide6.QtCore import Qt

import lensforge as lf
from lensforge import optimize as opt

from .fonts import fixed_font

EXAMPLE = """# Python against the open lens: `lens`, `lf`, `opt`, `np` are defined.
# Changes to `lens` become one undoable edit (Ctrl+Enter runs).
print(lens.paraxial())
for i in range(len(lens.fields)):
    print(i, lf.spot_diagram(lens, i)["rms_radius"])
"""


class ScriptConsole(QWidget):
    def __init__(self, doc, parent=None):
        super().__init__(parent)
        self.doc = doc
        self.namespace = {}
        mono = fixed_font()
        self.editor = QPlainTextEdit(EXAMPLE)
        self.editor.setFont(mono)
        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        self.output.setFont(mono)
        run = QPushButton("Run (Ctrl+Enter)")
        run.clicked.connect(self.run)
        clear = QPushButton("Clear Output")
        clear.clicked.connect(self.output.clear)
        QShortcut(QKeySequence("Ctrl+Return"), self.editor, activated=self.run)
        split = QSplitter(Qt.Vertical)
        split.addWidget(self.editor)
        split.addWidget(self.output)
        row = QHBoxLayout()
        row.addWidget(QLabel("lens, lf, opt, np"))
        row.addStretch(1)
        row.addWidget(clear)
        row.addWidget(run)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.addWidget(split, 1)
        lay.addLayout(row)

    def run(self, code=None):
        code = self.editor.toPlainText() if not isinstance(code, str) else code
        buf = io.StringIO()
        failed = []

        def fn(lens):
            ns = dict(self.namespace, lens=lens, lf=lf, opt=opt, np=np)
            with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
                try:
                    exec(compile(code, "<script>", "exec"), ns)
                except Exception:  # noqa: BLE001 - the traceback is shown to the user
                    failed.append(traceback.format_exc(limit=-3))
            self.namespace = {k: v for k, v in ns.items() if k not in ("lens", "__builtins__")}
            if failed:
                raise RuntimeError("the script raised an exception; the lens was left unchanged")

        rev = self.doc.revision
        self.doc.modify("Script", fn)
        unchanged = self.doc.revision == rev
        out = buf.getvalue()
        if failed:
            out += failed[0]
        self.output.appendPlainText(out.rstrip() or ("(no output)" if unchanged else "(lens updated)"))
        return out
