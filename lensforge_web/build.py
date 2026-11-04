"""Assemble the static web site: ``python -m lensforge_web.build [out_dir]``.

The site is plain files, so any static host serves it (GitHub Pages, ``python -m lensforge_web``):

* ``index.html``, ``app.css``, ``js/*.js``, ``worker.js``, ``sw.js`` from ``lensforge_web/static``;
* ``py/lensforge.zip``: the Python the page runs in Pyodide (``lensforge``, the Qt-free modules of
  ``lensforge_qt`` and ``lensforge_web``) plus the sample lens files of File > Sample Lenses;
* ``examples/``: every example lens of the repository, listed in ``examples/index.json`` (the
  Examples tab of File > Open);
* ``config.js``: where Pyodide is loaded from and the build id (cache busting).
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STATIC = os.path.join(HERE, "static")
EXAMPLES = os.path.join(ROOT, "examples")

PYODIDE_VERSION = "0.29.5"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/"

#: modules of lensforge_qt that do not import Qt (the web session uses them)
QT_FREE = ["__init__", "edits", "analyses", "rays", "help_text", "mfe_help", "icon_svgs", "commands",
           "opt_runner", "ns_table"]
WEB_MODULES = ["__init__", "menus", "document", "session"]


def _python_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        for dirpath, dirnames, files in os.walk(os.path.join(ROOT, "lensforge")):
            dirnames[:] = sorted(d for d in dirnames if d != "__pycache__")
            for f in sorted(files):
                if f.endswith(".py"):
                    p = os.path.join(dirpath, f)
                    z.write(p, os.path.relpath(p, ROOT))
        for m in QT_FREE:
            z.write(os.path.join(ROOT, "lensforge_qt", m + ".py"), f"lensforge_qt/{m}.py")
        for m in WEB_MODULES:
            z.write(os.path.join(HERE, m + ".py"), f"lensforge_web/{m}.py")
        # the sample lens files File > Sample Lenses reads (lensforge_qt.commands.sample_list)
        for rel in ("output/cooke_triplet.lens.json", "best_singlet.lens.json", "grating_demo.lens.json",
                    "spot_size_merit.lens.json"):
            p = os.path.join(EXAMPLES, rel)
            if os.path.exists(p):
                z.write(p, f"examples/{rel}")
    return buf.getvalue()


def _examples(out):
    """Copy the example lenses and write examples/index.json: [{path, group, name}]."""
    index = []
    dest = os.path.join(out, "examples")
    for dirpath, dirnames, files in os.walk(EXAMPLES):
        dirnames.sort()
        rel_dir = os.path.relpath(dirpath, EXAMPLES)
        for f in sorted(files):
            if not f.endswith(".json") or f.endswith(".ns.json"):
                continue
            rel = os.path.normpath(os.path.join(rel_dir, f)).replace(os.sep, "/")
            os.makedirs(os.path.join(dest, os.path.dirname(rel)), exist_ok=True)
            shutil.copy2(os.path.join(dirpath, f), os.path.join(dest, rel))
            group = "Examples" if rel_dir == "." else rel_dir.replace(os.sep, " / ")
            if group == "output":
                group = "Examples"
            name = f[:-len(".lens.json")] if f.endswith(".lens.json") else f[:-5]
            index.append({"path": rel, "group": group, "name": name})
    with open(os.path.join(dest, "index.json"), "w", encoding="utf-8") as fh:
        json.dump(index, fh, indent=0)
    return len(index)


def build(out_dir=None, pyodide_url: str = PYODIDE_CDN, quiet: bool = False) -> str:
    """Write the site to ``out_dir`` (default: ``web-dist`` in the repository) and return its path."""
    out = os.path.abspath(out_dir or os.path.join(ROOT, "web-dist"))
    if os.path.isdir(out):
        shutil.rmtree(out)
    shutil.copytree(STATIC, out)
    os.makedirs(os.path.join(out, "py"), exist_ok=True)
    data = _python_zip()
    with open(os.path.join(out, "py", "lensforge.zip"), "wb") as f:
        f.write(data)
    h = hashlib.sha256(data)
    for dirpath, _, files in sorted(os.walk(STATIC)):
        for fn in sorted(files):
            with open(os.path.join(dirpath, fn), "rb") as f:
                h.update(f.read())
    build_id = h.hexdigest()[:12]
    n = _examples(out)
    import lensforge
    from lensforge_qt.icon_svgs import APP_ICON
    with open(os.path.join(out, "app-icon.svg"), "w", encoding="utf-8") as f:
        f.write(APP_ICON)
    with open(os.path.join(out, "config.js"), "w", encoding="utf-8") as f:
        f.write("// written by lensforge_web/build.py\n"
                f"self.LENSFORGE_CONFIG = {json.dumps({'pyodide': pyodide_url, 'build': build_id, 'version': lensforge.__version__})};\n")
    if not quiet:
        print(f"lensforge web site: {out} ({len(data) // 1024} KB of Python, {n} example lenses, build {build_id})")
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out_dir", nargs="?", help="output directory (default: web-dist)")
    ap.add_argument("--pyodide", default=PYODIDE_CDN, help=f"Pyodide URL (default {PYODIDE_CDN})")
    a = ap.parse_args(argv)
    build(a.out_dir, a.pyodide)


if __name__ == "__main__":
    main()
