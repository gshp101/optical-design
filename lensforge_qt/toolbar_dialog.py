"""Customize Toolbar dialog: pick which menu items appear as toolbar buttons.

Items are identified by their menu path ("File > Open", "Analysis > Layout > 2D Layout"), which is
what gets stored in the settings, so a saved toolbar survives new menu items being added.
"""

from __future__ import annotations

from PySide6.QtCore import QItemSelectionModel, Qt
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QDialogButtonBox, QGridLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout)

SEPARATOR = "|"
SEPARATOR_TEXT = "──────  separator  ──────"
ID_ROLE = Qt.UserRole


def plain(text: str) -> str:
    """Menu text without mnemonics ("&&" stays a literal "&") or a trailing "..."."""
    text = text.replace("&&", "\0").replace("&", "").replace("\0", "&")
    return text[:-3] if text.endswith("...") else text


def menu_items(menubar, skip=()) -> list[tuple[str, tuple[str, ...], object]]:
    """Every command in the menu bar as (id, path, QAction), in menu order.

    Submenus in ``skip`` (e.g. Open Recent, whose entries change) are left out.
    """
    out = []

    def walk(menu, path):
        for a in menu.actions():
            if a.isSeparator():
                continue
            sub = a.menu()
            if sub is not None:
                if sub not in skip:
                    walk(sub, path + (plain(a.text()),))
                continue
            p = path + (plain(a.text()),)
            out.append((" > ".join(p), p, a))

    for top in menubar.actions():
        if top.menu() is not None and top.menu() not in skip:
            walk(top.menu(), (plain(top.text()),))
    return out


class ToolbarDialog(QDialog):
    """Two lists: every menu command (left, grouped like the menus) and the toolbar's buttons (right)."""

    def __init__(self, items, current, defaults, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Customize Toolbar")
        self.resize(760, 520)
        self.items = {iid: (path, action) for iid, path, action in items}
        self.defaults = list(defaults)

        self.filter = QLineEdit(placeholderText="Filter commands...")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.itemDoubleClicked.connect(lambda *_: self.add_selected())
        self._fill_tree(items)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.setDragDropMode(QAbstractItemView.InternalMove)
        self.list.itemDoubleClicked.connect(lambda *_: self.remove_selected())
        self.set_ids(current)

        self.b_add = QPushButton("Add  →")
        self.b_remove = QPushButton("←  Remove")
        self.b_sep = QPushButton("Add Separator")
        self.b_up = QPushButton("Move Up")
        self.b_down = QPushButton("Move Down")
        self.b_clear = QPushButton("Remove All")
        self.b_reset = QPushButton("Reset to Defaults")
        self.b_add.clicked.connect(self.add_selected)
        self.b_remove.clicked.connect(self.remove_selected)
        self.b_sep.clicked.connect(lambda: self.insert_ids([SEPARATOR]))
        self.b_up.clicked.connect(lambda: self.move(-1))
        self.b_down.clicked.connect(lambda: self.move(1))
        self.b_clear.clicked.connect(lambda: self.set_ids([]))
        self.b_reset.clicked.connect(lambda: self.set_ids(self.defaults))
        mid = QVBoxLayout()
        mid.addStretch(1)
        for b in (self.b_add, self.b_remove, self.b_sep):
            mid.addWidget(b)
        mid.addSpacing(16)
        for b in (self.b_up, self.b_down):
            mid.addWidget(b)
        mid.addSpacing(16)
        for b in (self.b_clear, self.b_reset):
            mid.addWidget(b)
        mid.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)

        g = QGridLayout(self)
        g.addWidget(QLabel("Menu commands:"), 0, 0)
        g.addWidget(QLabel("Toolbar buttons (in order):"), 0, 2)
        g.addWidget(self.filter, 1, 0)
        g.addWidget(self.tree, 2, 0)
        g.addLayout(mid, 1, 1, 2, 1)
        g.addWidget(self.list, 1, 2, 2, 1)
        g.addWidget(QLabel("Double-click a command to add or remove it; drag to reorder."), 3, 0, 1, 3)
        g.addWidget(bb, 4, 0, 1, 3)
        g.setColumnStretch(0, 1)
        g.setColumnStretch(2, 1)

    # ------------------------------------------------------------------ left: menu tree
    def _fill_tree(self, items):
        nodes = {}
        for iid, path, action in items:
            parent = self.tree.invisibleRootItem()
            for depth in range(1, len(path)):
                key = path[:depth]
                if key not in nodes:
                    node = QTreeWidgetItem(parent, [path[depth - 1]])
                    node.setFlags(Qt.ItemIsEnabled)
                    nodes[key] = node
                parent = nodes[key]
            leaf = QTreeWidgetItem(parent, [path[-1]])
            leaf.setData(0, ID_ROLE, iid)
            sc = action.shortcut().toString()
            if sc:
                leaf.setToolTip(0, sc)
        self.tree.expandToDepth(0)

    def _apply_filter(self, text):
        text = text.strip().lower()

        def visit(node):
            shown = False
            for i in range(node.childCount()):
                c = node.child(i)
                if c.data(0, ID_ROLE):
                    ok = not text or text in c.data(0, ID_ROLE).lower()
                else:
                    ok = visit(c)
                c.setHidden(not ok)
                shown |= ok
            return shown

        visit(self.tree.invisibleRootItem())
        if text:
            self.tree.expandAll()

    # ------------------------------------------------------------------ right: toolbar list
    def _list_item(self, iid):
        if iid == SEPARATOR:
            it = QListWidgetItem(SEPARATOR_TEXT)
            it.setForeground(Qt.gray)
        else:
            it = QListWidgetItem(iid)
        it.setData(ID_ROLE, iid)
        return it

    def ids(self) -> list[str]:
        return [self.list.item(i).data(ID_ROLE) for i in range(self.list.count())]

    def set_ids(self, ids):
        self.list.clear()
        for iid in ids:
            if iid == SEPARATOR or iid in self.items:
                self.list.addItem(self._list_item(iid))

    def insert_ids(self, ids):
        """Insert after the current row (or at the end); commands already on the toolbar are skipped."""
        have = set(self.ids())
        row = self.list.currentRow() + 1 if self.list.currentRow() >= 0 else self.list.count()
        self.list.clearSelection()
        for iid in ids:
            if iid != SEPARATOR and iid in have:
                continue
            it = self._list_item(iid)
            self.list.insertItem(row, it)
            self.list.setCurrentRow(row, QItemSelectionModel.NoUpdate)
            it.setSelected(True)
            row += 1

    def add_selected(self):
        self.insert_ids([it.data(0, ID_ROLE) for it in self.tree.selectedItems() if it.data(0, ID_ROLE)])

    def remove_selected(self):
        for it in self.list.selectedItems():
            self.list.takeItem(self.list.row(it))

    def move(self, step):
        rows = sorted((self.list.row(it) for it in self.list.selectedItems()), reverse=step > 0)
        if not rows or min(rows) + step < 0 or max(rows) + step >= self.list.count():
            return
        moved = []
        for r in rows:
            it = self.list.takeItem(r)
            self.list.insertItem(r + step, it)
            moved.append(it)
        self.list.setCurrentRow(rows[-1] + step, QItemSelectionModel.NoUpdate)
        for it in moved:
            it.setSelected(True)
