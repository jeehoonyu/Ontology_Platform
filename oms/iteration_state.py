"""Read what this project still owes itself, from the files that already say it.

Eleven goal documents hold thirty conditions. Five of them record whether they
were ever satisfied. The eight conditions of the request-cost goal — a goal that
is finished, five defects fixed and a ratchet built and held — contain the word
"Met" zero times. The work happened and the record of what it discharged did not,
so the only way to know what is open is to re-read eleven documents.

This module reads three things that are already on disk and turns them into one
answer:

  **conditions** — parsed from `docs/GOAL_*.md` in either shape they are written
  in, the table (`| **C1** | ... |`) or the bullet (`- **G1 — ...**`), with an
  explicit state where the document gives one.

  **cadence** — what `check_registry.py` claims about when a check runs, against
  the pre-push hook that would have to honour it. Four checks declare `every
  push` and are not in the hook; two existing audits both reported green while
  that was true, because neither compares a declaration to a mechanism.

  **baselines** — the nine files holding the ratchets, and how old each is.
  `audit_evidence_corpus` already argues that something with no provenance
  "cannot be shown to be stale, so it never expires"; the ratchet baselines are
  evidence by any reasonable definition and were exempt from their own rule.

Nothing here runs a check or a suite. It reads static files in well under a
second, which is what makes it usable as the thing you type before deciding what
to do next.
"""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS = REPO_ROOT / "docs"
PRE_PUSH = REPO_ROOT / "scripts" / "hooks" / "pre-push"

OPEN = "open"
MET = "met"
BLOCKED = "blocked"
UNRECORDED = "unrecorded"

# The two shapes conditions are written in. Both are read; only one is accepted
# for new documents, which is what makes the format an interface rather than a
# preference.
_BULLET = re.compile(r"^- \*\*(?P<id>[A-Z]+\d+) — (?P<title>.+?)\*\*(?P<rest>.*?)"
                     r"(?=^- \*\*[A-Z]+\d+ — |^#|\Z)", re.M | re.S)
_TABLE = re.compile(r"^\|\s*\*\*(?P<id>[A-Z]+\d+)\*\*\s*\|(?P<cells>.+?)\|\s*$", re.M)
# A third shape, used by the two oldest goals: the condition is a heading and
# the state is written into it. `### B2 — No route can materialize ... — **met**`.
# Widening the parser rather than restructuring those documents was deliberate:
# their narrative sections are the most valuable thing in them, and a condition
# that is identifiable and carries a state already satisfies the interface.
_HEADING = re.compile(r"^#{2,4} (?P<id>(?:[A-Z]+\d+|Tier [A-C])) — (?P<title>.+?)$", re.M)

# A state written explicitly, in either shape: `**Met**`, `**Open**`, `**Blocked**`.
_STATE = re.compile(r"\*\*(Met|Open|Blocked)\*\*", re.I)


@dataclass
class Condition:
    document: str
    identifier: str
    title: str
    state: str
    detail: str = ""

    @property
    def key(self) -> str:
        return f"{self.document}:{self.identifier}"


@dataclass
class Baseline:
    name: str
    recorded_at: Optional[str]
    migration_head: Optional[str]
    age_days: Optional[float]
    stale_after: Optional[str] = None
    overdue: Optional[str] = None


@dataclass
class Report:
    conditions: List[Condition] = field(default_factory=list)
    cadence_gaps: List[str] = field(default_factory=list)
    baselines: List[Baseline] = field(default_factory=list)
    unparsed: List[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def conditions_in(text: str, document: str) -> List[Condition]:
    """Every condition in one goal document, in whichever shape it uses."""
    found: List[Condition] = []
    for match in _BULLET.finditer(text):
        body = match.group("rest")
        state = _STATE.search(body)
        found.append(Condition(
            document=document,
            identifier=match.group("id"),
            title=_clean(match.group("title"))[:90],
            state=state.group(1).lower() if state else UNRECORDED,
            detail=_clean(body)[:120],
        ))
    for match in _HEADING.finditer(text):
        state = _STATE.search(match.group("title"))
        title = _STATE.sub("", match.group("title")).strip(" —-")
        found.append(Condition(
            document=document,
            identifier=match.group("id").replace(" ", ""),
            title=_clean(title)[:90],
            state=state.group(1).lower() if state else UNRECORDED,
            detail=_clean(match.group("title"))[:120],
        ))
    for match in _TABLE.finditer(text):
        cells = [cell.strip() for cell in match.group("cells").split("|")]
        state = _STATE.search(match.group(0))
        found.append(Condition(
            document=document,
            identifier=match.group("id"),
            title=_clean(cells[0])[:90] if cells else "",
            state=state.group(1).lower() if state else UNRECORDED,
            detail=_clean(" | ".join(cells[1:]))[:120],
        ))
    return found


def read_conditions(docs: Path | None = None) -> List[Condition]:
    docs = docs or DOCS
    found: List[Condition] = []
    for path in sorted(docs.glob("GOAL_*.md")):
        found.extend(conditions_in(path.read_text(encoding="utf-8"), path.name))
    return found


def cadence_gaps() -> List[str]:
    """Does each check have an automated home that matches what it claims?

    The first version of this asked only whether an `every push` check appeared
    in the pre-push hook, and reported four that did not. That reading was wrong
    and the evidence corrected it: all four are executed by suite tests --
    `test_check_homes.py` exists for exactly that purpose and is itself C2 of
    `GOAL_2026-08-13.md`. They are not unrun; they are mis-declared, which is a
    smaller problem and still a real one, because the registry is what a reader
    consults to learn when a check runs.

    So two verdicts, not one:

      *unhomed* -- nothing automated runs it, anywhere. Serious.
      *mis-declared* -- it runs, but not where its cadence says. Correctable by
      editing one word, and worth failing over, because a declaration nothing
      compares against is a claim with no proof.
    """
    import sys

    sys.path.insert(0, str(REPO_ROOT / "oms"))
    from check_registry import DECLARATIONS

    if not PRE_PUSH.exists():
        return ["scripts/hooks/pre-push is missing entirely"]
    hook = PRE_PUSH.read_text(encoding="utf-8")
    on_push = set(re.findall(r"(audit_[a-z_]+|validate_[a-z_]+)", hook))

    # `check_registry.suite_executions` already draws this line, and draws it
    # better: an import, not a mention. Every benchmark here has a contract test
    # that reads its source with `read_text`, and counting those as a home is what
    # made this surface look covered when it was not. This file had its own
    # containment scan, which was a weaker duplicate of that -- a mention would
    # have satisfied it.
    from check_registry import suite_executions

    homed = suite_executions()

    gaps: List[str] = []
    for name, declaration in sorted(DECLARATIONS.items()):
        cadence = declaration.get("cadence", "")
        in_suite = name in homed
        if cadence == "every push":
            if name in on_push:
                continue
            if in_suite:
                gaps.append(f"{name}: declares `every push`, runs in the suite -- "
                            f"declare `every suite run`")
            else:
                gaps.append(f"{name}: declares `every push` and nothing automated runs it")
        elif cadence == "every suite run":
            if not in_suite:
                gaps.append(f"{name}: declares `every suite run` and no suite test runs it")
        elif cadence.startswith("manual"):
            # `manual` is an honest answer and the only one that has to justify
            # itself: it must say what it needs. Twenty-seven checks previously
            # said `per release candidate`, `on demand`, `before enabling
            # downstream consumers` or `when the connector changes` -- four
            # phrasings naming no event that happens in this repository, which
            # read like a schedule and behaved like a hope.
            if cadence == "manual":
                gaps.append(f"{name}: declares `manual` without saying what it needs")
        else:
            gaps.append(f"{name}: cadence {cadence!r} names no mechanism -- use "
                        f"`every push`, `every suite run`, or `manual: needs ...`")
    return gaps


def _age_days(stamp: str) -> Optional[float]:
    for shape in ("%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d"):
        try:
            when = datetime.strptime(stamp, shape)
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=timezone.utc)
        return round((datetime.now(timezone.utc) - when).total_seconds() / 86400, 1)
    return None


def read_baselines(docs: Path | None = None) -> List[Baseline]:
    docs = docs or DOCS
    found: List[Baseline] = []
    for path in sorted(docs.glob("*baseline*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            found.append(Baseline(path.name, None, None, None))
            continue
        provenance = payload.get("provenance") if isinstance(payload, dict) else None
        provenance = provenance if isinstance(provenance, dict) else {}
        stamp = provenance.get("recorded_at")
        head = provenance.get("migration_head")
        age = _age_days(stamp) if stamp else None
        # Two kinds of shelf life, because two kinds of evidence live here and
        # only one of them ages. A census of what routes cost is a statement
        # about a schema, so it expires when the migration head moves, not after
        # some number of days. A ceiling on how many conditions lack a state is
        # recomputed from the tree on every run, so it cannot go stale at all.
        # Writing "30 days" over both would have been a number invented to fill
        # a field.
        life = provenance.get("stale_after")
        overdue = None
        if life == "migration head" and head and head != _current_head():
            overdue = f"measured at {head}, head is now {_current_head()}"
        elif isinstance(life, str) and life.endswith(" days"):
            try:
                limit = float(life.split()[0])
            except ValueError:
                limit = None
            if limit is not None and age is not None and age > limit:
                overdue = f"{age} days old, declared life {life}"
        found.append(Baseline(
            name=path.name, recorded_at=stamp, migration_head=head,
            age_days=age, stale_after=life, overdue=overdue,
        ))
    return found


def _current_head() -> Optional[str]:
    try:
        import sys

        sys.path.insert(0, str(REPO_ROOT / "oms"))
        from audit_evidence_corpus import current_head

        return current_head()
    except Exception:
        return None


def build() -> Report:
    report = Report()
    report.conditions = read_conditions()
    report.cadence_gaps = cadence_gaps()
    report.baselines = read_baselines()
    for path in sorted(DOCS.glob("GOAL_*.md")):
        text = path.read_text(encoding="utf-8")
        if re.search(r"^#+ .*[Cc]onditions", text, re.M) and not conditions_in(text, path.name):
            report.unparsed.append(path.name)
    return report


def next_step(report: Report) -> str:
    """What to do next, by a stated ordering rather than by whoever is reading.

    The ordering is deliberate and narrow. Unrecorded state comes first because
    every later judgement is unreliable while it holds: a backlog you cannot read
    cannot be prioritised. Broken promises about cadence come next, because a
    check that claims to run and does not is worse than one that admits it is
    manual. Then undated evidence, then the open conditions themselves.
    """
    unrecorded = [c for c in report.conditions if c.state == UNRECORDED]
    if report.unparsed:
        return (f"Give {report.unparsed[0]} conditions in the parseable form -- "
                f"{len(report.unparsed)} document(s) declare conditions nothing can read.")
    if unrecorded:
        by_document: Dict[str, int] = {}
        for condition in unrecorded:
            by_document[condition.document] = by_document.get(condition.document, 0) + 1
        worst = max(by_document.items(), key=lambda item: item[1])
        return (f"Record the state of {worst[1]} condition(s) in {worst[0]} -- "
                f"{len(unrecorded)} condition(s) across {len(by_document)} document(s) do not "
                f"say whether they are done.")
    if report.cadence_gaps:
        return (f"Wire {report.cadence_gaps[0]} into pre-push or correct its declared cadence "
                f"-- {len(report.cadence_gaps)} check(s) claim `every push` and are not run.")
    undated = [b for b in report.baselines if not b.recorded_at]
    if undated:
        return (f"Date {undated[0].name} -- {len(undated)} baseline(s) cannot be shown to be "
                f"stale.")
    stale = sorted((b for b in report.baselines if b.age_days is not None),
                   key=lambda b: -(b.age_days or 0))
    if stale and (stale[0].age_days or 0) > 30:
        return f"Re-measure {stale[0].name} -- it is {stale[0].age_days} days old."
    still_open = [c for c in report.conditions if c.state in (OPEN, BLOCKED)]
    if still_open:
        first = still_open[0]
        return f"Take {first.identifier} from {first.document}: {first.title}"
    return "Nothing is open, undated, or unproven. State a new goal."
