"""Count the database round-trips one request makes, and group the repeats.

Nothing in this repository measured this, and the cost of not measuring it was
concrete. `/health/ready` reflected the whole schema on every call -- 275
catalog round-trips, 220 ms at rest -- and that was found only because the
endpoint is the one the availability gate is *defined* on, so it eventually
failed a threshold by being slow to answer. Nine hundred and fifty other routes
have no such tripwire.

Two numbers matter and they are not the same:

  **queries** is the absolute count. Useful, but a route that legitimately
  touches six tables is not worse than one that touches five.

  **repeats** is one statement shape executed many times in a single request.
  That is the N+1 signature, and unlike the absolute count it does not need a
  threshold to be damning: a shape run once per row is a route whose cost
  follows the data, which is the second standing invariant of this project
  applied to a request instead of an object type.

Statements are normalised before grouping so that the same shape with different
literals counts as one shape. Without that, an N+1 against a database with
distinct ids looks like N distinct queries and hides in plain sight.
"""
from __future__ import annotations

import contextvars
import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

# Literals, bind parameters and whitespace vary between executions of one shape.
# Collapsing them is what turns "281 different queries" into "one query, 281
# times", which is the difference between a busy endpoint and a broken one.
_LITERAL = re.compile(r"'[^']*'|\b\d+\b|\?|:[A-Za-z_]\w*|%\([^)]*\)s")
_WHITESPACE = re.compile(r"\s+")
_IN_LIST = re.compile(r"\bIN\s*\([^)]*\)", re.IGNORECASE)


def normalize(statement: str) -> str:
    """One statement shape, with the parts that vary per execution removed."""
    collapsed = _IN_LIST.sub("IN (?)", statement)
    collapsed = _LITERAL.sub("?", collapsed)
    return _WHITESPACE.sub(" ", collapsed).strip()


# One listener per engine, routing each statement to whichever request is in
# scope. A listener that appends to a single list is correct only while one
# request runs at a time -- and the moment two do, each of them records the
# other's work. Measured: 48 concurrent requests whose true cost is 169
# statements each recorded between 2,184 and 9,823, a sum of 195,377 against a
# real total of 8,112. Twenty-four worker threads, twenty-four times the truth.
_ACTIVE: "contextvars.ContextVar[Optional[List[str]]]" = contextvars.ContextVar(
    "request_cost_active", default=None)


def attach(bind: Any) -> Any:
    """Install the context-routing listener on `bind`, and return it.

    Left installed for the life of the process. It costs nothing when no
    collection is in scope, because the context variable is then None.
    """
    from sqlalchemy import event

    def record(conn, cursor, statement, parameters, context, executemany):
        collected = _ACTIVE.get()
        if collected is not None:
            collected.append(statement)

    event.listen(bind, "before_cursor_execute", record)
    return record


@contextmanager
def collecting() -> Iterator[List[str]]:
    """Statements executed inside *this* context, not inside this process.

    A context variable rather than a plain list, because Starlette runs a sync
    endpoint on a worker thread and copies the caller's context into it. That is
    what makes the attribution survive concurrency; a thread-local would not,
    and a module-level list does not.
    """
    collected: List[str] = []
    token = _ACTIVE.set(collected)
    try:
        yield collected
    finally:
        _ACTIVE.reset(token)


@contextmanager
def counting(bind: Any) -> Iterator[List[str]]:
    """Collect every statement `bind` executes inside the block.

    The listener is removed on the way out. A counter that outlives its
    measurement quietly attributes one request's queries to the next one.
    """
    from sqlalchemy import event

    collected: List[str] = []

    def record(conn, cursor, statement, parameters, context, executemany):
        collected.append(statement)

    event.listen(bind, "before_cursor_execute", record)
    try:
        yield collected
    finally:
        event.remove(bind, "before_cursor_execute", record)


def summarize(statements: List[str], *, repeat_threshold: int = 2) -> Dict[str, Any]:
    """Absolute cost, distinct shapes, and the shapes that repeat.

    `repeat_threshold` is 2 because two executions of one shape in a single
    request is already the pattern; whether it matters is a question of how the
    count moves with the data, which the caller answers by measuring twice.
    """
    shapes: Dict[str, int] = {}
    for statement in statements:
        shape = normalize(statement)
        shapes[shape] = shapes.get(shape, 0) + 1
    repeats = [{"statement": shape, "count": count}
               for shape, count in sorted(shapes.items(), key=lambda item: -item[1])
               if count >= repeat_threshold]
    return {
        "queries": len(statements),
        "distinct_shapes": len(shapes),
        "repeats": repeats,
        "worst_repeat": repeats[0]["count"] if repeats else 0,
    }


def measure(client: Any, method: str, path: str, bind: Any, **kwargs: Any) -> Dict[str, Any]:
    """One request, measured. Returns the summary plus the response status."""
    with counting(bind) as collected:
        response = client.request(method, path, **kwargs)
    summary = summarize(collected)
    summary["status"] = response.status_code
    summary["path"] = path
    summary["method"] = method.upper()
    return summary


def shape(points: List[tuple]) -> Dict[str, Any]:
    """Does a route's cost follow the data? Needs at least three points.

    Two points cannot answer this, and believing otherwise produced a false
    finding the first time this was used. `/ui-state/ontology` measured 1 query
    on an empty database and 9 with eight object types, which reads as exactly
    one query per row. It is not: at sixteen and thirty-two object types it is
    still 9. The route has a branch that only runs when a row exists, and a
    branch is a step, not a slope.

    The difference is the whole point of the measurement. A step is a fixed cost
    that shows up once; a slope is a route that gets more expensive every time
    someone uses the product. Comparing empty against non-empty conflates them,
    and empty-against-non-empty is the comparison a test fixture makes by
    default.

    `points` is [(rows, queries), ...] in increasing row order. The slope is
    taken across the *non-empty* points, so the one-off cost of having any data
    at all is excluded from it.
    """
    ordered = sorted(points)
    if len(ordered) < 3:
        return {"verdict": "unknown", "slope": None,
                "why": "at least three points are needed to tell a step from a slope"}
    populated = [point for point in ordered if point[0] > 0]
    if len(populated) < 2:
        return {"verdict": "unknown", "slope": None,
                "why": "at least two non-empty points are needed"}
    first_rows, first_queries = populated[0]
    last_rows, last_queries = populated[-1]
    span = last_rows - first_rows
    slope = 0.0 if span <= 0 else round((last_queries - first_queries) / span, 4)
    stepped = ordered[0][0] == 0 and ordered[0][1] != populated[0][1]
    if slope > 0:
        verdict = "linear"
        why = f"{slope} queries per row across {first_rows}..{last_rows}"
    elif stepped:
        verdict = "step"
        why = (f"{populated[0][1] - ordered[0][1]} queries appear once data exists, "
               f"then flat to {last_rows} rows")
    else:
        verdict = "flat"
        why = f"unchanged from {first_rows} to {last_rows} rows"
    return {"verdict": verdict, "slope": slope, "why": why}
