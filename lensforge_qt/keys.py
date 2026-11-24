"""Platform keyboard shortcuts: the keys a Mac uses where a PC keyboard has a key a Mac lacks.

Mac keyboards have no Insert key, so the "insert a row" commands use the Numbers / Excel for Mac
convention there: Option+Up inserts above (before), Option+Down below (after). The PC key still
works on a Mac (an external PC keyboard). Qt-free: the web front end uses the same table
(lensforge_web.menus sends it to the page).
"""

from __future__ import annotations

import sys
from typing import List, Optional

IS_MAC = sys.platform == "darwin"

#: PC shortcut (Qt spelling) -> the Mac one (Qt spelling: Alt is Option, Ctrl is Command)
MAC_EQUIVALENTS = {
    "Insert": "Alt+Up",
    "Ctrl+Insert": "Alt+Down",
}


def shortcuts(sc: Optional[str], mac: Optional[bool] = None) -> List[str]:
    """The shortcuts to bind for ``sc``: on a Mac its Mac key first (the one menus show), then ``sc``."""
    if not sc:
        return []
    mac = IS_MAC if mac is None else mac
    return [MAC_EQUIVALENTS[sc], sc] if mac and sc in MAC_EQUIVALENTS else [sc]


def primary(sc: Optional[str], mac: Optional[bool] = None) -> Optional[str]:
    """The shortcut menus and tooltips show for ``sc`` on this platform."""
    s = shortcuts(sc, mac)
    return s[0] if s else None
