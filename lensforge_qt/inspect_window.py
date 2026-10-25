"""File > Inspect Lens File: the system report of a lens file in its own window.

The file is read into a separate system, so the open design is not touched. The window is
non-modal: several can be open at once, next to the main window, to compare designs.
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import (QFileDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QVBoxLayout,
                               QWidget)

import lensforge as lf

from . import icons, workers
from .fonts import fixed_font


class InspectLensWindow(QWidget):
    """Reads ``path`` and shows :func:`lensforge.system_report` for it (computed in a worker)."""

    open_requested = Signal(str)  # "Open in Editor": the main window loads the file

    def __init__(self, path: str, parent=None):
        super().__init__(parent, Qt.Window)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.path = os.path.abspath(path)
        self.system = None
        self.setWindowTitle(f"Inspect: {os.path.basename(path)}")
        self.setWindowIcon(icons.icon("File > Inspect Lens File"))
        self.resize(820, 640)

        self.header = QLabel()
        self.header.setWordWrap(True)
        self.header.setTextInteractionFlags(Qt.TextSelectableByMouse)
        mono = fixed_font()
        self.text = QPlainTextEdit(readOnly=True)
        self.text.setFont(mono)
        self.text.setLineWrapMode(QPlainTextEdit.NoWrap)

        self.copy_btn = QPushButton("Copy")
        self.copy_btn.clicked.connect(lambda: QGuiApplication.clipboard().setText(self.text.toPlainText()))
        self.save_btn = QPushButton("Save...")
        self.save_btn.clicked.connect(self.save_text)
        self.open_btn = QPushButton("Open in Editor")
        self.open_btn.setToolTip("Open this file as the current lens (you are asked to save changes)")
        self.open_btn.clicked.connect(lambda: self.open_requested.emit(self.path))
        close = QPushButton("Close")
        close.clicked.connect(self.close)
        for b in (self.copy_btn, self.save_btn, self.open_btn):
            b.setEnabled(False)

        row = QHBoxLayout()
        row.addWidget(self.open_btn)
        row.addStretch(1)
        for b in (self.copy_btn, self.save_btn, close):
            row.addWidget(b)
        lay = QVBoxLayout(self)
        lay.addWidget(self.header)
        lay.addWidget(self.text, 1)
        lay.addLayout(row)
        self.load()

    def load(self):
        self.header.setText(f"<b>{self.path}</b>")
        try:
            self.system = lf.load(self.path)
        except Exception as e:  # noqa: BLE001 - unreadable file: say so in the window
            self.system = None
            self.text.setPlainText(f"Could not read {self.path}:\n{type(e).__name__}: {e}")
            return
        s = self.system
        info = f"{s.name or os.path.basename(self.path)}: {s.image_index - 1} surfaces"
        if s.notes.startswith("ZMX import ignored"):
            info += f"<br><span style='color:#a06000'>{s.notes}</span>"
        self.header.setText(f"<b>{self.path}</b><br>{info}")
        self.open_btn.setEnabled(True)
        self.text.setPlainText("Computing system report...")
        workers.submit(lambda progress, s=s.copy(): lf.system_report(s), self._done, self._failed)

    def _done(self, _tag, report):
        self.text.setPlainText(report)
        self.copy_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def _failed(self, _tag, msg):
        self.text.setPlainText(f"The system report failed:\n{msg}")

    def save_text(self):
        base = os.path.basename(self.path)
        for ext in (".lens.json", ".json", ".zmx"):
            if base.lower().endswith(ext):
                base = base[:-len(ext)]
                break
        start = os.path.join(os.path.dirname(self.path), f"{base}_report.txt")
        path, _ = QFileDialog.getSaveFileName(self, "Save system report", start, "Text (*.txt)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.text.toPlainText())
