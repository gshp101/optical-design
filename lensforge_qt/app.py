"""Application entry point: ``python -m lensforge_qt [lensfile]``."""

from __future__ import annotations

import argparse
import sys


def main(argv=None):
    ap = argparse.ArgumentParser(prog="lensforge_qt", description="lensforge optical design (Qt desktop)")
    ap.add_argument("lens", nargs="?", help=".json or .zmx lens file to open")
    ap.add_argument("--sample", help="open a sample lens: singlet, achromat, parabola, cassegrain, triplet")
    ap.add_argument("--analyses", default="layout",
                    help="comma-separated analysis windows to open (e.g. layout,spot,mtf; 'none' for none)")
    a = ap.parse_args(argv)

    import matplotlib
    matplotlib.use("QtAgg")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("lensforge")
    app.setOrganizationName("lensforge")
    app.setStyle("Fusion")
    if sys.platform == "win32":
        # without its own app id, Windows groups the window under python.exe and shows Python's icon
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("lensforge.desktop")

    from .icons import app_icon

    app.setWindowIcon(app_icon())

    from .main_window import MainWindow, _sample_list

    w = MainWindow(a.lens)
    if a.sample and not a.lens:
        key = a.sample.lower()
        for name, fn in _sample_list():
            if key in name.lower() or (key == "parabola" and "Parabolic" in name):
                w.doc.reset(fn())
                break
        else:
            print(f"unknown sample {a.sample!r}", file=sys.stderr)
    if a.analyses and a.analyses != "none":
        for k in a.analyses.split(","):
            if k.strip():
                w.open_analysis(k.strip())
    w.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
