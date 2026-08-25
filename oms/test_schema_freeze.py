"""The freeze has to fail the build, not merely describe an intention.

Everything here is a way a freeze could look present and enforce nothing, which
is the only failure mode that matters: an unenforced freeze reads exactly like an
enforced one until seven days of evidence are already lost.
"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from validate_schema_freeze import evaluate, load_freeze  # noqa: E402
from tier_b_evidence import current_head

HEAD = current_head()
NOW = 1_800_000_000
passed = 0


def check(condition, label, payload=None):
    global passed
    assert condition, f"{label}: {payload}"
    passed += 1


def freeze(**overrides):
    payload = {
        "state": "open",
        "head": HEAD,
        "opened_at": NOW - 3600,
        "expires_at": NOW + 7 * 24 * 3600,
        "reason": "seven-day availability, RPO, and RTO window",
        "owner": "operations",
    }
    payload.update(overrides)
    return payload


code, message = evaluate(freeze(), HEAD, NOW)
check(code == 0, "the frozen head itself passes", message)
check("OPEN" in message and "remaining" in message,
      "and says how long the freeze has left", message)

code, message = evaluate(freeze(), "0043_something_new", NOW)
check(code == 1, "a new head during an open freeze fails the build", message)
check("voids it" in message and "operations" in message,
      "and names the consequence and the owner", message)

check(evaluate(None, "0043_something_new", NOW)[0] == 0,
      "no freeze file means no restriction")
check(evaluate(freeze(state="closed"), "0043_something_new", NOW)[0] == 0,
      "a closed freeze restricts nothing")

# An expired freeze must not silently stop enforcing. Left alone it would become
# a file that looks like protection and is not.
code, message = evaluate(freeze(expires_at=NOW - 3600), HEAD, NOW)
check(code == 1, "an expired freeze fails until it is closed deliberately", message)

# A freeze without an owner or an end date is not actionable: there is nobody to
# ask and no date it lifts.
with tempfile.TemporaryDirectory() as directory:
    for missing in ("owner", "reason", "expires_at", "head", "state"):
        path = Path(directory) / f"freeze-{missing}.json"
        incomplete = freeze()
        del incomplete[missing]
        path.write_text(json.dumps(incomplete), encoding="utf-8")
        try:
            load_freeze(path)
            raise AssertionError(f"a freeze missing {missing} was accepted")
        except SystemExit:
            passed += 1

    path = Path(directory) / "torn.json"
    path.write_text("{not json", encoding="utf-8")
    try:
        load_freeze(path)
        raise AssertionError("unparseable freeze was accepted")
    except SystemExit:
        passed += 1

    check(load_freeze(Path(directory) / "absent.json") is None,
          "an absent freeze file is simply no freeze")

# The committed freeze, if there is one, must be loadable and internally sound.
committed = load_freeze()
if committed is not None:
    check(int(committed["expires_at"]) > int(committed["opened_at"]),
          "the committed freeze ends after it starts", committed)
    check(str(committed["state"]).lower() in {"open", "closed"},
          "the committed freeze has a state the validator understands", committed)

print(f"Schema freeze enforcement verified: {passed} assertions passed.")
