"""
The server ranks event severity the way the owner decided for the operations feed
(GOAL_HONEST_UI N7d): `warning` ranks with `warn`, `error` with `high`.

Both server maps lacked the two words, so an "error" event ranked with "info". A rule at
minimum high never fired for an exhausted job, a failed connection sync or an SLO breach
at severity error, and a subscription at minimum high never matched one.

Each block runs on its own and every failure is printed, so one run on the old code
shows each block failing for its own reason.

Run:
  python oms/test_ops_severity_rank.py
"""
import os
import re
import sys
import tempfile
from pathlib import Path

tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'severity.db')}"

from fastapi.testclient import TestClient  # noqa: E402
from app import ops_control, platform_core  # noqa: E402
from app.main import app  # noqa: E402

client = TestClient(app)
passed = 0
OWNER = {"info": 0, "low": 1, "medium": 2, "warn": 2, "warning": 2, "high": 3, "error": 3, "critical": 4}


def ok(resp, label, expect=200):
    global passed
    success = resp.status_code == expect or (expect == 200 and 200 <= resp.status_code < 300)
    assert success, f"{label}: expected {expect}, got {resp.status_code} -> {resp.text[:800]}"
    passed += 1
    return resp.json() if resp.content else {}


def check(condition, message):
    global passed
    assert condition, message
    passed += 1


def rule(rule_id, source, min_severity):
    ok(client.post("/ops/alert-rules", json={"id": rule_id, "display_name": rule_id, "source": source, "min_severity": min_severity}), f"rule {rule_id}")


def ingest(source, severity, title):
    return ok(client.post("/ops/events/ingest", json={"source": source, "event_type": "severity_rank", "severity": severity, "title": title}), f"ingest {title}")


def alert_pairs(prefixes):
    alerts = ok(client.get("/ops/alerts"), "list alerts")
    return {(alert["rule_id"], alert["event_id"]) for alert in alerts if str(alert["rule_id"]).startswith(prefixes)}, alerts


def subscription_matches(sub_id, source, min_severity):
    ok(client.post("/events/subscriptions", json={"id": sub_id, "display_name": sub_id, "filters": {"source": source, "min_severity": min_severity}}), f"subscription {sub_id}", 201)
    return ok(client.post(f"/events/subscriptions/{sub_id}/evaluate"), f"evaluate {sub_id}")["match_count"]


def one_map():
    check(ops_control.SEVERITY_RANK == OWNER, f"the server's rank is not the owner's: {ops_control.SEVERITY_RANK}")
    check(getattr(platform_core, "SEVERITY_RANK", ops_control.SEVERITY_RANK) is ops_control.SEVERITY_RANK,
          "platform_core keeps its own copy of the severity rank, free to drift from ops_control's")
    rank = getattr(ops_control, "severity_rank", None)
    check(rank is not None, "ops_control has no severity_rank helper")
    check(rank(" Warning ", 9) == 2, f"severity_rank(' Warning ') is {rank(' Warning ', 9)}, not 2: words are not trimmed and lowercased")
    check(rank(None, 7) == 7, "severity_rank(None) does not rank as the caller's unknown default")


def frontend_matches():
    source = (Path(__file__).resolve().parent.parent / "frontend" / "src" / "workspaces" / "OpsWorkspace.tsx").read_text(encoding="utf-8")
    literals = re.findall(r"const SEVERITY_RANK[^=]*=\s*\{([^}]*)\}", source)
    check(len(literals) == 1, f"expected one `const SEVERITY_RANK = {{...}}` in OpsWorkspace.tsx, found {len(literals)}; if it was reformatted, update this pattern")
    feed = {word: int(value) for word, value in re.findall(r"(\w+)\s*:\s*(\d+)", literals[0])}
    check(feed == ops_control.SEVERITY_RANK, f"the operations feed ranks {feed}, the server {ops_control.SEVERITY_RANK}")


def alert_rules():
    # Rules are evaluated when an event is written, so ingest is the real path.
    rule("sev_e_high", "sevtest_e", "high")
    rule("sev_e_crit", "sevtest_e", "critical")
    rule("sev_e_cap_crit", "sevtest_e", "Critical")
    rule("sev_w_medium", "sevtest_w", "medium")
    rule("sev_w_high", "sevtest_w", "high")
    error = ingest("sevtest_e", "ERROR", "error event")
    warning = ingest("sevtest_w", "warning", "warning event")
    check(error["severity"] == "error", f"an ingested ERROR is stored as {error['severity']!r}")
    pairs, alerts = alert_pairs("sev_")
    expected = {("sev_e_high", error["id"]), ("sev_w_medium", warning["id"])}
    names = {error["id"]: "error", warning["id"]: "warning"}
    check(pairs == expected,
          "alerts raised: " + str(sorted((rule_id, names.get(event_id, event_id)) for rule_id, event_id in pairs))
          + "; expected sev_e_high on the error event and sev_w_medium on the warning event, and nothing else")
    raised = [alert for alert in alerts if alert["rule_id"] == "sev_e_high"]
    check(not raised or raised[0]["severity"] == "error", "the alert does not keep the event's own word")


def subscriptions():
    for source, severity in (("sevsub_e", "error"), ("sevsub_w", "warning")):
        ok(client.post("/events/publish", json={"source": source, "event_type": "severity_rank", "severity": severity, "title": f"sub {severity}", "evaluate_alerts": False}), f"publish {severity}")
    counts = {sub_id: subscription_matches(sub_id, source, minimum) for sub_id, source, minimum in (
        ("sub_e_high", "sevsub_e", "high"), ("sub_e_crit", "sevsub_e", "critical"),
        ("sub_w_medium", "sevsub_w", "medium"), ("sub_w_high", "sevsub_w", "high"))}
    check(counts == {"sub_e_high": 1, "sub_e_crit": 0, "sub_w_medium": 1, "sub_w_high": 0},
          f"subscription matches {counts}; expected error to reach high but not critical, and warning to reach medium but not high")


def unknown_words_keep_their_defaults():
    # Outside the owner's decision, so unchanged: an unknown rule threshold acts as high,
    # an unknown event word as info, and an unknown subscription threshold matches all.
    rule("unk_bogus_min", "sevtest_u", "bogus")
    rule("unk_info_min", "sevtest_n", "info")
    rule("unk_low_min", "sevtest_n", "low")
    high = ingest("sevtest_u", "high", "unknown threshold, high event")
    medium = ingest("sevtest_u", "medium", "unknown threshold, medium event")
    notice = ingest("sevtest_n", "notice", "unknown event word")
    pairs, _ = alert_pairs("unk_")
    check(("unk_bogus_min", high["id"]) in pairs and ("unk_bogus_min", medium["id"]) not in pairs,
          f"a rule with an unknown threshold no longer acts as high: {sorted(pairs)}")
    check(("unk_info_min", notice["id"]) in pairs and ("unk_low_min", notice["id"]) not in pairs,
          f"an event with an unknown word no longer ranks as info: {sorted(pairs)}")
    # On the warning event (rank 2), so a default of 3 would miss it; an error event ranks 3
    # and would match either way.
    check(subscription_matches("sub_bogus", "sevsub_w", "bogus") == 1,
          "a subscription with an unknown threshold no longer matches every event")


failures = []
for block in (one_map, frontend_matches, alert_rules, subscriptions, unknown_words_keep_their_defaults):
    try:
        block()
    except (AssertionError, AttributeError, TypeError, KeyError) as error:
        failures.append(f"{block.__name__}: {type(error).__name__}: {error}")

for failure in failures:
    print(f"FAIL {failure}")
if failures:
    sys.exit(1)
print(f"passed {passed}")
