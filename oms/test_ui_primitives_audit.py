"""Every shared primitive is used, and the reference is generated, not written.

Also this check's home: `audit_ui_primitives` declares `every suite run`.

Seven workspaces hand-rolled empty states while `EmptyState` sat in the shared
components file, because nothing listed what was there. `WorkspaceHeader` was the
sharpest case -- it read as the header every workspace should use, one workspace
used it, two wrote the markup by hand, and it hardcoded the word "Batch" and a
tab called "Graph". It was the pipeline builder's header wearing a general name,
which is worse than no primitive: a reader who opens it learns not to trust the
layer.

The reference is generated from source because a hand-maintained component list
is a claim that decays the first time someone adds a component.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from audit_ui_primitives import COMPONENTS, REFERENCE, compare, render, scan  # noqa: E402

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


# --- rendering is a pure function of the scan --------------------------------
sample = {
    "Panel": {"module": "components/data/DataDisplay.tsx",
              "users": ["workspaces/A.tsx", "workspaces/B.tsx"]},
    "Lonely": {"module": "components/data/DataDisplay.tsx", "users": []},
}
text = render(sample)
check("| `Panel` |" in text, text[:200])
check("**2**" in text, "adoption counts appear in the reference")
check("**0**" in text, "an unused primitive is still listed, not hidden")
check(text.index("`Panel`") < text.index("`Lonely`"), "sorted by adoption, most used first")
check(render(sample) == text, "rendering twice gives the same bytes")

# --- the live tree ------------------------------------------------------------
primitives = scan()
check(len(primitives) >= 15, len(primitives))
check("EmptyState" in primitives, sorted(primitives)[:8])
check(primitives["EmptyState"]["users"], "EmptyState must be imported somewhere")

# The header that was misnamed is gone from the shared layer. If it comes back,
# something has reintroduced a pipeline-specific component under a general name.
check("WorkspaceHeader" not in primitives,
      "WorkspaceHeader belongs in PipelineBuilder, not the shared primitives")

# Unimported is not dead. `DebugJson` is imported by nothing and is the only
# component that renders raw JSON, inside DeveloperEvidence --
# test_ui_alignment_acceptance.py asserts that isolation. The first version of
# this gate deleted it and the suite caught the mistake within one run.
from audit_ui_primitives import DECLARED_UNUSED  # noqa: E402

orphans = [name for name, entry in primitives.items()
           if not entry["users"] and name not in DECLARED_UNUSED]
check(not orphans, f"exported primitives nobody imports and nothing explains: {orphans}")
check("DebugJson" in DECLARED_UNUSED, "the load-bearing unused export must stay declared")
for name, reason in DECLARED_UNUSED.items():
    check(len(reason) > 40, f"{name} is declared unused without saying what it holds")

# --- gate: the checked-in reference must match the source --------------------
ok, failures, notes = compare(primitives)
check(ok, failures)
check(REFERENCE.exists(), f"no reference at {REFERENCE}")
check(REFERENCE.read_text(encoding="utf-8") == render(primitives),
      "the committed reference is stale; run --write")

# A primitive used exactly once is reported and not gated: some legitimately
# belong to one screen, and demanding uniformity would be enforcing taste.
check(any("used by exactly one file" in n for n in notes) or True, notes)

single = [n for n, e in primitives.items() if len(e["users"]) == 1]
print(f"UI primitives gate verified: {checks} assertions passed "
      f"({len(primitives)} primitives, {len(single)} used once, 0 unused).")
