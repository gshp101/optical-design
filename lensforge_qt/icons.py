"""Toolbar/menu icons for the Qt front end: the SVG markup of icon_svgs.py rendered to QIcons."""

from __future__ import annotations

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QIcon, QImage, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from .icon_svgs import *  # noqa: F401,F403 - ICONS, svg(), APP_ICON ... are part of this module's API
from .icon_svgs import APP_ICON, ns_svg, svg


def ns_icon(key: str) -> QIcon:
    """Icon of a Non-Sequential Editor toolbar button."""
    markup = ns_svg(key)
    ic = QIcon()
    for size in (16, 24, 32, 48):
        ic.addPixmap(QPixmap.fromImage(render(markup, size)))
    return ic


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


def app_icon() -> QIcon:
    """The LensForge window/taskbar icon, rendered at the usual platform sizes."""
    ic = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        ic.addPixmap(QPixmap.fromImage(render(APP_ICON, size)))
    return ic
