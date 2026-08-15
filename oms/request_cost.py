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

import re
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List

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


def growth(before: Dict[str, Any], after: Dict[str, Any], rows_added: int) -> float:
    """Queries added per row added -- the number that says whether cost follows data.

    Zero is the only good answer. Anything else is a route that costs more as
    the product is used more, which no absolute threshold catches early: it
    passes on an empty test database and fails in front of a customer.
    """
    if rows_added <= 0:
        return 0.0
    return round((after["queries"] - before["queries"]) / rows_added, 3)
