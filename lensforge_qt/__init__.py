"""Qt desktop front end for lensforge (PySide6 + matplotlib).

Run ``python -m lensforge_qt [lensfile]``.  The UI is a thin layer over the
public lensforge API; the core package stays free of any UI code.

Modules: ``document`` (open lens + undo), ``edits`` (Qt-free editing helpers),
``lde`` (Lens Data Editor), ``system_dialog`` (System Explorer), ``mfe``
(Merit Function Editor), ``analyses`` / ``analysis_window`` (dockable
analyses), ``opt_dialogs`` (optimisation, tolerancing), ``script_console``,
``main_window``.
"""

__all__ = ["main"]


def main(argv=None):
    from .app import main as _main
    return _main(argv)
