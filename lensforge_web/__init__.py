"""Web front end for lensforge: the Qt desktop app's interface in a browser page.

The page (``static/``) runs the lensforge Python core itself in the browser with Pyodide, inside a
Web Worker, so there is no server: any static web host (GitHub Pages, ``python -m lensforge_web``)
serves it. ``session`` is the Python side the page calls; ``menus`` holds the menu bar, help and
icons (shared with lensforge_qt); ``build`` assembles the static site.
"""

__all__ = ["build", "serve"]


def build(out_dir=None, **kw):
    from .build import build as _build
    return _build(out_dir, **kw)


def serve(argv=None):
    from .__main__ import main
    return main(argv)
