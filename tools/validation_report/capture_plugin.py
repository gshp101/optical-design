"""pytest plugin used by run.py: record every numeric comparison a test makes (pytest.approx,
numpy.testing.assert_allclose and plain `assert error < bound`) and each test's outcome, into $CAPTURE_OUT."""
import json, math, os, re
import numpy as np
import pytest
from _pytest import python_api

RECORDS = {}
_current = [None]


def _rec(kind, err, tol, expected):
    nid = _current[0]
    if nid is None:
        return
    try:
        err, tol = float(err), float(tol)
    except Exception:
        return
    if not math.isfinite(err):
        return
    try:
        expected = float(expected)
    except Exception:
        expected = float("nan")
    RECORDS.setdefault(nid, []).append({"kind": kind, "err": err, "tol": tol, "expected": expected})


_orig_eq = python_api.ApproxScalar.__eq__


def _eq(self, actual):
    res = _orig_eq(self, actual)
    try:
        if isinstance(self.expected, (int, float, np.floating, np.integer)) and not isinstance(self.expected, bool):
            a = float(actual)
            _rec("approx", abs(a - float(self.expected)), self.tolerance, self.expected)
    except Exception:
        pass
    return res


python_api.ApproxScalar.__eq__ = _eq

_orig_allclose = np.testing.assert_allclose


def _allclose(actual, desired, rtol=1e-7, atol=0, *a, **k):
    try:
        A = np.asarray(actual, float)
        D = np.broadcast_to(np.asarray(desired, float), A.shape)
        diff = np.abs(A - D)
        allowed = atol + rtol * np.abs(D)
        ok = np.isfinite(diff)
        if ok.any():
            ratio = np.where(allowed[ok] > 0, diff[ok] / np.where(allowed[ok] > 0, allowed[ok], 1), np.where(diff[ok] > 0, np.inf, 0))
            i = int(np.argmax(ratio)) if np.isfinite(ratio).any() else 0
            _rec("allclose", diff[ok][i], allowed[ok][i], D[ok][i])
    except Exception:
        pass
    return _orig_allclose(actual, desired, rtol, atol, *a, **k)


np.testing.assert_allclose = _allclose

NUM = r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?|inf"
V = rf"(?:np\.float(?:64|32)\()?({NUM})\)?"
LT = re.compile(rf"^(?:assert )?{V} (<|<=) {V}$")


def pytest_assertion_pass(item, lineno, orig, expl):
    first = expl.splitlines()[0].strip() if expl else ""
    m = LT.match(first)
    if m:
        a, b = float(m.group(1)), float(m.group(3))
        # "err < tol" with a positive bound; skip lower bounds like 0 < x
        if b > 0 and a >= 0 and "<" in m.group(2):
            _rec("assert", a, b, float("nan"))


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    _current[0] = item.nodeid
    yield
    _current[0] = None


OUTCOMES = {}


def pytest_runtest_logreport(report):
    if report.when == "call" or (report.when == "setup" and report.outcome != "passed"):
        OUTCOMES[report.nodeid] = {"outcome": report.outcome, "duration": report.duration}


def pytest_sessionfinish(session):
    out = os.environ.get("CAPTURE_OUT", "capture.json")
    with open(out, "w") as fh:
        json.dump({"records": RECORDS, "outcomes": OUTCOMES}, fh)

DEBUG = []
