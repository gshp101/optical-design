"""Regenerate docs/validation-report.html.

    pip install optiland==0.6.3   # optional: without it the live Optiland comparisons are skipped
    python tools/validation_report/run.py

Runs the truth-comparison tests with capture_plugin.py (which records every numeric comparison each test
makes), collects the Smith / glass / version data with collect.py, and writes the report with make_report.py.
The tests and their descriptions are listed in catalog.py; add an entry there when a new truth test is added.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(HERE))
TEST_FILES = ["test_aberration_reference.py", "test_mtf_reference.py", "test_analysis_quality.py",
              "test_paraxial.py", "test_raytrace.py", "test_grating.py", "test_ghost.py", "test_nonseq.py",
              "test_point_source.py", "test_optimize.py", "test_io_analysis.py", "test_vignetting_factors.py",
              "test_materials.py", "test_smith_examples.py"]


def main():
    out = os.path.join(REPO, "docs", "validation-report.html")
    with tempfile.TemporaryDirectory() as data:
        # the assertion-pass hook only works on freshly rewritten test modules
        shutil.rmtree(os.path.join(REPO, "tests", "__pycache__"), ignore_errors=True)
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", CAPTURE_OUT=os.path.join(data, "capture.json"),
                   PYTHONPATH=os.pathsep.join([HERE, os.environ.get("PYTHONPATH", "")]))
        cmd = [sys.executable, "-m", "pytest", "-q", "-p", "capture_plugin", "-p", "no:cacheprovider",
               "-o", "enable_assertion_pass_hook=true", "-W", "ignore", "-k", "not qt_ and not web_",
               *[os.path.join("tests", f) for f in TEST_FILES]]
        r = subprocess.run(cmd, cwd=REPO, env=env)
        if r.returncode not in (0, 1):
            sys.exit(r.returncode)
        subprocess.run([sys.executable, os.path.join(HERE, "collect.py"), data], cwd=REPO, check=True)
        subprocess.run([sys.executable, os.path.join(HERE, "make_report.py"), data, out], cwd=REPO, check=True)
    print("wrote", out)


if __name__ == "__main__":
    main()
