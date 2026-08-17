"""The cost recorder attributes statements to the request that ran them.

This is a test of the instrument, not of the product, and it exists because the
instrument was wrong in a way that produced a published finding.

The first recorder attached a listener to the engine for the duration of one
request and appended every statement it saw to one list. That is correct while
one request runs at a time. Under concurrency each request collects every other
request's work, and the error is not small: 48 concurrent calls to
`/project/readiness`, whose true cost is 169 statements, recorded between 2,184
and 9,823 each -- a sum of 195,377 against a real total near 8,112. Twenty-four
worker threads, twenty-four times the truth.

That inflation was read as an N+1 defect and written into a goal document as
"`/project/readiness` repeats a count 192 times under real traffic". No such
loop exists. The route costs 169 statements with a worst repeat of 4, whether it
runs alone or with twenty-three others in flight.

The fix is a context variable: Starlette copies the calling context into the
worker thread that runs a sync endpoint, so a variable set in the middleware is
readable from the listener and names the right request. A thread-local would not
survive the hop, and a module-level list does not survive concurrency at all.

The assertion below is the one that matters: with the database already warm, every
concurrent request must record *exactly* what the same request records alone.
Anything else means the instrument is measuring the process rather than the call.
"""
import json
import os
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir.name, 'cost_concurrency.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from measure_suite_cost import install  # noqa: E402
from request_cost import collecting, counting, summarize  # noqa: E402

WORKERS = 24
REQUESTS = 48
ROUTE = "/project/readiness"

sink = Path(_tmpdir.name) / "costs.jsonl"
sink.write_text("", encoding="utf-8")
install(app, engine, sink)
client = TestClient(app)


def recorded():
    return [json.loads(line) for line in sink.read_text(encoding="utf-8").splitlines() if line.strip()]


# A first call reconciles the runtime schema, which is real one-time work and
# would otherwise be indistinguishable from a mis-attribution. Discard it: the
# claim under test is about attribution, so the measurement has to hold the rest
# of the world still.
response = client.get(ROUTE)
assert response.status_code == 200, response.status_code
warm = recorded()
assert len(warm) == 1, warm
sink.write_text("", encoding="utf-8")

sequential = client.get(ROUTE)
assert sequential.status_code == 200, sequential.status_code
alone = recorded()
assert len(alone) == 1, alone
baseline_queries = alone[0]["queries"]
baseline_repeat = alone[0]["worst_repeat"]
assert baseline_queries > 0, alone
sink.write_text("", encoding="utf-8")

with ThreadPoolExecutor(max_workers=WORKERS) as pool:
    statuses = list(pool.map(lambda _index: client.get(ROUTE).status_code, range(REQUESTS)))
assert all(status == 200 for status in statuses), statuses

rows = recorded()
assert len(rows) == REQUESTS, len(rows)
assert all(row["route"] == ROUTE for row in rows), {row["route"] for row in rows}

# The whole point. One request's cost does not depend on how many others are in
# flight, so neither may its measurement.
observed_queries = sorted({row["queries"] for row in rows})
assert observed_queries == [baseline_queries], (
    f"{REQUESTS} concurrent requests recorded {observed_queries} statements; "
    f"the same request alone records {baseline_queries}. The recorder is "
    f"attributing other requests' work to this one.")

observed_repeats = sorted({row["worst_repeat"] for row in rows})
assert observed_repeats == [baseline_repeat], (
    f"worst repeat under concurrency {observed_repeats}, alone {baseline_repeat}")

# `collecting` is the middleware's tool, not the caller's, and the reason is the
# same mechanism that makes it correct. A context set here does not reach the
# thread the test client runs the application on, so a caller who opens a
# collection around `client.get(...)` records nothing at all. That is the right
# behaviour -- silence rather than another request's statements -- but it is a
# sharp edge, so it is pinned rather than left to be rediscovered.
with collecting() as outside:
    client.get(ROUTE)
assert outside == [], (
    f"a collection opened outside the application recorded {len(outside)} statements; "
    f"it should record none, and a caller wanting a count should use `counting`")

# And nothing leaks into a collection after it closes.
assert outside == [], outside
client.get("/health/live")
assert outside == [], "statements leaked into a closed collection"
assert summarize(outside)["queries"] == 0, summarize(outside)

# `counting` is still the right tool for a single-threaded caller, and still
# means what it meant: everything the engine does inside the block.
with counting(engine) as collected:
    client.get(ROUTE)
assert len(collected) == baseline_queries, (len(collected), baseline_queries)

client.close()
print(f"Request cost attribution verified: {REQUESTS} concurrent requests over {WORKERS} "
      f"threads each recorded {baseline_queries} statements (x{baseline_repeat}), "
      f"identical to the same request run alone.")
