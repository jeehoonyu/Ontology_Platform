"""The assembled product API remains versioned or deliberately excluded."""
import os
import tempfile


tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(tmpdir.name, 'route_coverage.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from audit_route_coverage import classify, handlers, render  # noqa: E402


registrations, generated_sources, authoritative_sources = handlers()
dual, v1_only, generated, authoritative, unversioned = classify(
    registrations, generated_sources, authoritative_sources,
)

assert len(generated) >= 890, len(generated)
assert len(v1_only) >= 70, len(v1_only)
assert len(authoritative) >= 4, len(authoritative)
assert len(unversioned) <= 11, unversioned
assert all(
    route.split(" ", 1)[1].startswith(("/workspace", "/auth/", "/health/", "/metrics"))
    or route.split(" ", 1)[1] == "/"
    for routes in unversioned.values()
    for route in routes
), unversioned

document = render(dual, v1_only, generated, authoritative, unversioned)
assert "Generated same-handler aliases" in document
assert "Explicit v1 successors" in document
assert "test_api_v1_compatibility.py" in document

print(
    "API v1 route coverage ratchet held: "
    f"{len(generated)} generated handlers, {len(authoritative)} explicit successors, "
    f"{len(v1_only)} v1-only handlers, {len(unversioned)} deliberately unversioned."
)
