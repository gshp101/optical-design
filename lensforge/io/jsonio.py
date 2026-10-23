"""Native JSON lens format (``.lens.json``).  Plain JSON so a web front end can
read and write it directly."""

from __future__ import annotations

import json

from ..system import OpticalSystem


def dumps(system: OpticalSystem, indent: int = 2) -> str:
    return json.dumps(system.to_dict(), indent=indent)


def loads(text: str, library=None) -> OpticalSystem:
    return OpticalSystem.from_dict(json.loads(text), library)


def save(system: OpticalSystem, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(dumps(system))


def load(path: str, library=None) -> OpticalSystem:
    if path.lower().endswith((".zmx", ".zos")):
        from .zmx import load_zmx
        return load_zmx(path, library)
    with open(path, encoding="utf-8") as f:
        return loads(f.read(), library)
