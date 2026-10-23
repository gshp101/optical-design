"""Background computation.

Analyses, merit evaluation, optimisation and tolerancing run on a *copy* of
the lens in a thread pool so the editors stay responsive.  Results come back
through Qt signals (queued to the GUI thread).  Set ``SYNC = True`` (the
tests do) to run everything inline.
"""

from __future__ import annotations

import os
import traceback

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

SYNC = bool(os.environ.get("LENSFORGE_QT_SYNC"))


class _Signals(QObject):
    done = Signal(object, object)       # (tag, result)
    failed = Signal(object, str)        # (tag, message)
    progress = Signal(object, object)   # (tag, payload)


class Job(QRunnable):
    """Runs ``fn(progress)`` where ``progress(payload)`` emits :attr:`signals.progress`."""

    def __init__(self, fn, tag=None):
        super().__init__()
        self.fn, self.tag = fn, tag
        self.signals = _Signals()
        self.setAutoDelete(False)

    def run(self):
        try:
            res = self.fn(lambda payload: self.signals.progress.emit(self.tag, payload))
        except Exception as e:  # noqa: BLE001 - reported to the UI
            if os.environ.get("LENSFORGE_QT_DEBUG"):
                traceback.print_exc()
            self.signals.failed.emit(self.tag, f"{type(e).__name__}: {e}")
            return
        self.signals.done.emit(self.tag, res)


_live = set()  # running jobs, kept alive until their result has been delivered


class _Relay(QObject):
    """Lives in the GUI thread: receives a job's signals (queued) and calls the callbacks there."""

    def __init__(self, job, on_done, on_failed, on_progress):
        super().__init__()
        self.job, self.on_done, self.on_failed, self.on_progress = job, on_done, on_failed, on_progress

    def done(self, tag, result):
        try:
            self.on_done(tag, result)
        finally:
            _live.discard(self.job)

    def failed(self, tag, msg):
        try:
            if self.on_failed is not None:
                self.on_failed(tag, msg)
        finally:
            _live.discard(self.job)

    def progress(self, tag, payload):
        if self.on_progress is not None:
            self.on_progress(tag, payload)


def submit(fn, on_done, on_failed=None, on_progress=None, tag=None) -> Job:
    """Run ``fn(progress)`` in the thread pool; callbacks run in the GUI thread."""
    job = Job(fn, tag)
    job.relay = _Relay(job, on_done, on_failed, on_progress)
    job.signals.done.connect(job.relay.done)
    job.signals.failed.connect(job.relay.failed)
    job.signals.progress.connect(job.relay.progress)
    _live.add(job)
    if SYNC:
        job.run()
    else:
        QThreadPool.globalInstance().start(job)
    return job


def wait_all(msecs: int = 60000) -> bool:
    return QThreadPool.globalInstance().waitForDone(msecs)
