"""Help > Help Contents: browse and search the help for every menu command."""

from __future__ import annotations

import base64
import html

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLineEdit, QSplitter, QTextBrowser, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import icons
from .help_text import OVERVIEW, lookup

ID_ROLE = Qt.UserRole


def _icon_html(item_id: str, size: int = 40) -> str:
    markup = icons.svg(item_id)
    if not markup:
        return ""
    buf = QBuffer()
    buf.open(QIODevice.WriteOnly)
    icons.render(markup, size).save(buf, "PNG")
    data = base64.b64encode(bytes(buf.data())).decode()
    return f'<img src="data:image/png;base64,{data}" width="{size}" height="{size}">'


def command_html(item_id: str, action=None) -> str:
    """The help page of one command."""
    h = lookup(item_id)
    title = html.escape(item_id.split(" > ")[-1])
    where = html.escape(item_id.replace(" > ", " ▸ "))
    sc = action.shortcut().toString() if action is not None else ""
    head = (f'<table><tr><td>{_icon_html(item_id)}</td><td style="padding-left:10px">'
            f'<h2 style="margin:0">{title}</h2><span style="color:#666">{where}'
            f'{"&nbsp;&nbsp;·&nbsp;&nbsp;Shortcut: <b>" + html.escape(sc) + "</b>" if sc else ""}'
            f'</span></td></tr></table>')
    if h is None:
        return head + "<p><i>No help has been written for this command yet.</i></p>"
    summary, details = h
    return f"{head}<p><b>{summary}</b></p><p>{details}</p>"


def menu_html(name: str, entries) -> str:
    """A menu's page: every command in it with its summary."""
    rows = "".join(f'<tr><td valign="top">{_icon_html(iid, 20)}</td><td valign="top"><b>'
                   f'{html.escape(iid.split(" > ", 1)[1].replace(" > ", " ▸ "))}</b></td>'
                   f'<td valign="top" style="padding-left:8px">{(lookup(iid) or ("",))[0]}</td></tr>'
                   for iid in entries)
    return f"<h2>{html.escape(name)} menu</h2><table cellspacing='4'>{rows}</table>"


class HelpBrowser(QDialog):
    """Tree of menu commands (left), the selected command's help (right), with a filter."""

    def __init__(self, items, parent=None):
        super().__init__(parent)
        self.setWindowTitle("lensforge Help")
        self.resize(940, 640)
        self.actions_by_id = {iid: a for iid, _, a in items}
        self.by_menu = {}
        for iid, path, _ in items:
            self.by_menu.setdefault(path[0], []).append(iid)

        self.filter = QLineEdit(placeholderText="Search help...")
        self.filter.setClearButtonEnabled(True)
        self.filter.textChanged.connect(self._apply_filter)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(self._show)
        self.page = QTextBrowser()
        self.page.setOpenExternalLinks(False)

        top = QTreeWidgetItem(self.tree, ["Overview"])
        top.setData(0, ID_ROLE, ":overview")
        nodes = {}
        for iid, path, action in items:
            parent = self.tree.invisibleRootItem()
            for depth in range(1, len(path)):
                key = path[:depth]
                if key not in nodes:
                    nodes[key] = QTreeWidgetItem(parent, [path[depth - 1]])
                    nodes[key].setData(0, ID_ROLE, ":menu:" + " > ".join(key))
                parent = nodes[key]
            leaf = QTreeWidgetItem(parent, [path[-1]])
            leaf.setData(0, ID_ROLE, iid)
            leaf.setIcon(0, action.icon())
            h = lookup(iid)
            if h:
                leaf.setToolTip(0, h[0])
        self.tree.expandToDepth(0)

        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.addWidget(self.filter)
        left.addWidget(self.tree)
        lw = QWidget()
        lw.setLayout(left)
        split = QSplitter()
        split.addWidget(lw)
        split.addWidget(self.page)
        split.setSizes([300, 640])
        lay = QHBoxLayout(self)
        lay.addWidget(split)
        self.tree.setCurrentItem(top)

    def _show(self, item, _prev=None):
        if item is None:
            return
        key = item.data(0, ID_ROLE)
        if key == ":overview":
            self.page.setHtml(OVERVIEW)
        elif key.startswith(":menu:"):
            path = key[len(":menu:"):]
            entries = [i for ids in self.by_menu.values() for i in ids if i.startswith(path + " > ")]
            self.page.setHtml(menu_html(path, entries))
        else:
            self.page.setHtml(command_html(key, self.actions_by_id.get(key)))

    def show_command(self, item_id: str):
        """Select a command's page (used by tests and by F1 on a menu item)."""
        it = self._find(self.tree.invisibleRootItem(), item_id)
        if it is not None:
            self.tree.setCurrentItem(it)
        return it is not None

    def _find(self, node, item_id):
        for i in range(node.childCount()):
            c = node.child(i)
            if c.data(0, ID_ROLE) == item_id:
                return c
            f = self._find(c, item_id)
            if f is not None:
                return f
        return None

    def _apply_filter(self, text):
        text = text.strip().lower()

        def visit(node):
            shown = False
            for i in range(node.childCount()):
                c = node.child(i)
                key = c.data(0, ID_ROLE) or ""
                if key.startswith(":"):
                    ok = visit(c) or not text
                else:
                    h = lookup(key) or ("", "")
                    ok = not text or text in key.lower() or text in h[0].lower() or text in h[1].lower()
                c.setHidden(not ok)
                shown |= ok
            return shown

        visit(self.tree.invisibleRootItem())
        if text:
            self.tree.expandAll()
            first = self._first_visible_leaf(self.tree.invisibleRootItem())
            if first is not None:
                self.tree.setCurrentItem(first)

    def _first_visible_leaf(self, node):
        for i in range(node.childCount()):
            c = node.child(i)
            if c.isHidden():
                continue
            if not (c.data(0, ID_ROLE) or ":").startswith(":"):
                return c
            f = self._first_visible_leaf(c)
            if f is not None:
                return f
        return None
