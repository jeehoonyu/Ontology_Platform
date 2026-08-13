"""Record the third-party code that produced a measurement.

Conditions D1 and D2 of GOAL_REPRODUCIBILITY_2026-08-13.

Every gate in this repository records the git commit that produced it and the
migration head it ran against, and records nothing at all about the code that
actually executed. `sqlalchemy` compiles the queries `audit_query_bounds`
ratchets, `duckdb` runs the pipeline the scale gate times, `pyarrow` owns the
memory the read-path bounds measure. A minor release in any of them moves a
number this project would attribute to its own code.

Scope is the **transitive closure of the declared dependencies**, not the whole
environment. The environment these measurements were taken in is a shared global
interpreter carrying 101 distributions, including packages belonging to unrelated
projects. Digesting all of them would report drift whenever someone installed
something irrelevant, and a signal that cries wolf gets ignored -- the lesson the
enforcement goal already paid for. Digesting only the sixteen direct dependencies
would miss `starlette`, `greenlet` and `anyio`, which are exactly the kind of
thing that moves a benchmark.

  python oms/dependency_provenance.py
"""
from __future__ import annotations

import hashlib
import importlib.metadata as metadata
import re
import sys
from pathlib import Path
from typing import Dict, List, Set

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = REPO_ROOT / "oms" / "requirements.txt"

_REQUIREMENT_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")


def declared(requirements_file: Path | None = None) -> List[str]:
    """The direct dependencies this project declares, in file order."""
    path = requirements_file or REQUIREMENTS
    if not path.exists():
        return []
    names = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        found = _REQUIREMENT_NAME.match(line)
        if found:
            names.append(found.group(1))
    return names


def _normalise(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def closure(roots: List[str] | None = None) -> Set[str]:
    """Every distribution the declared dependencies pull in, transitively.

    Walked through installed metadata rather than resolved from the declarations,
    because what matters is what executed, not what was permitted to.
    """
    pending = list(roots if roots is not None else declared())
    seen: Set[str] = set()
    while pending:
        raw = pending.pop()
        name = _normalise(raw)
        if name in seen:
            continue
        try:
            distribution = metadata.distribution(raw)
        except metadata.PackageNotFoundError:
            continue
        seen.add(name)
        for requirement in distribution.requires or []:
            # "package (>=1.2) ; extra == 'foo'" -- extras are not installed
            # unless requested, so a requirement guarded by one is skipped.
            if ";" in requirement and "extra ==" in requirement.split(";", 1)[1]:
                continue
            found = _REQUIREMENT_NAME.match(requirement)
            if found:
                pending.append(found.group(1))
    return seen


def resolved(roots: List[str] | None = None) -> Dict[str, str]:
    """name -> version for the closure, as installed right now."""
    versions: Dict[str, str] = {}
    for name in closure(roots):
        try:
            versions[name] = metadata.version(name)
        except metadata.PackageNotFoundError:
            continue
    return dict(sorted(versions.items()))


def digest(versions: Dict[str, str] | None = None) -> str:
    """A short stable fingerprint of the closure, for cheap comparison."""
    versions = resolved() if versions is None else versions
    payload = "\n".join(f"{name}=={version}" for name, version in sorted(versions.items()))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def provenance() -> Dict[str, object]:
    """The block `write_evidence` embeds in every gate."""
    versions = resolved()
    return {
        "python": ".".join(str(part) for part in sys.version_info[:3]),
        "declared": len(declared()),
        "closure": len(versions),
        "digest": digest(versions),
        "versions": versions,
    }


def unpinned(requirements_file: Path | None = None) -> List[str]:
    """Declared requirements that do not fix an exact version.

    Condition D1. A floor says what is permitted; it does not say what ran, and
    a measurement taken against `fastapi>=0.110.0` was in fact taken against
    0.136.3 -- twenty-six minor releases of unrecorded difference.
    """
    path = requirements_file or REQUIREMENTS
    if not path.exists():
        return []
    loose = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if "==" not in line:
            loose.append(line)
    return loose


def main() -> int:
    block = provenance()
    print("Dependency provenance\n")
    print(f"  python            {block['python']}")
    print(f"  declared          {block['declared']}")
    print(f"  closure           {block['closure']} distributions")
    print(f"  digest            {block['digest']}")
    loose = unpinned()
    print(f"  unpinned declared {len(loose)}")
    for line in loose:
        print(f"    {line}")
    return 1 if loose else 0


if __name__ == "__main__":
    sys.exit(main())
