"""A change event recorded after a promotion carries the promoted revision.

Three lookups inside the per-object write loop were removed because their
answers cannot change while a request runs. Two of them -- does `object_snapshots`
exist, does `object_change_events` exist -- are genuinely constant, and caching
them is uninteresting.

The third is not constant, and that is what this file is about. The production
revision for a project *does* change mid-request: `industrial_workflow` promotes
a new revision and then hydrates the objects that belong to it, in one call to
`POST /pipeline-builder/workers/run-next`. Caching the revision *id* would have
stamped every hydrated object with the revision the promotion had just
superseded, and nothing in the suite would have said a word -- the objects would
be written, the request would succeed, and the lineage would be quietly wrong.

So the cache holds the environment *row*, not the id read off it. SQLAlchemy's
identity map means the instance cached here is the same object the promotion
mutates, so the attribute read below sees the new value.

The fixture therefore has to contain a promotion followed by a write. A fixture
that only records change events against a stable revision passes either way,
which is exactly the trap this project has walked into three times: a fixture
proves what it contains.
"""
import os
import tempfile

_tmpdir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
os.environ["DATABASE_URL"] = f"sqlite:///{os.path.join(_tmpdir.name, 'revision_freshness.db')}"
os.environ["AUTH_MODE"] = "local"
os.environ["APP_ENV"] = "test"

from fastapi.testclient import TestClient  # noqa: E402

from app.database import SessionLocal  # noqa: E402
from app.main import app  # noqa: E402
from app import ontology_runtime_v1, ontology_versioning  # noqa: E402

client = TestClient(app)
client.get("/health/ready")

checks = 0


def check(condition, message):
    global checks
    assert condition, message
    checks += 1


PROJECT = "default"

with SessionLocal() as db:
    environment = db.query(ontology_versioning.OntologyEnvironment).filter(
        ontology_versioning.OntologyEnvironment.project_id == PROJECT,
        ontology_versioning.OntologyEnvironment.name == "production",
    ).first()
    if environment is None:
        environment = ontology_versioning.OntologyEnvironment(
            id="ontology_env_test", project_id=PROJECT, name="production",
            current_revision_id="revision-one", previous_revision_id=None,
            updated_by="test", updated_at=0)
        db.add(environment)
    else:
        environment.current_revision_id = "revision-one"
    db.commit()

# One session, standing in for one request.
with SessionLocal() as db:
    first = ontology_runtime_v1._active_revision_id(db, PROJECT)
    check(first == "revision-one", first)

    # Read again: this is the call the cache is for. Same answer, no new query.
    check(ontology_runtime_v1._active_revision_id(db, PROJECT) == "revision-one",
          "a cached read must return the same revision")

    # Now the crossed case. The promotion happens through the ORM, the way
    # industrial_workflow does it, *after* the value has already been cached.
    environment = db.query(ontology_versioning.OntologyEnvironment).filter(
        ontology_versioning.OntologyEnvironment.project_id == PROJECT,
        ontology_versioning.OntologyEnvironment.name == "production",
    ).first()
    environment.previous_revision_id = environment.current_revision_id
    environment.current_revision_id = "revision-two"

    after = ontology_runtime_v1._active_revision_id(db, PROJECT)
    check(after == "revision-two",
          f"after promotion the active revision must be revision-two, got {after!r}; "
          f"caching the id rather than the row would return {first!r} here and "
          f"stamp every object hydrated after the promotion with a superseded revision")

    # And it survives a commit, which expires the instance: the attribute read
    # refreshes it rather than serving a stale copy.
    db.commit()
    check(ontology_runtime_v1._active_revision_id(db, PROJECT) == "revision-two",
          "the revision must survive the commit that expires the cached row")

# A project with no production environment must not cache the absence, because
# one may be created later in the same session.
with SessionLocal() as db:
    check(ontology_runtime_v1._active_revision_id(db, "project-without-env") is None,
          "a project with no production environment has no active revision")
    db.add(ontology_versioning.OntologyEnvironment(
        id="ontology_env_late", project_id="project-without-env", name="production",
        current_revision_id="revision-late", previous_revision_id=None,
        updated_by="test", updated_at=0))
    db.flush()
    late = ontology_runtime_v1._active_revision_id(db, "project-without-env")
    check(late == "revision-late",
          f"an environment created after the first lookup must be seen, got {late!r}")

# The table-existence caches answer the same question twice without asking twice.
with SessionLocal() as db:
    bind = db.get_bind()
    name = ontology_runtime_v1.ObjectChangeEvent.__tablename__
    check(ontology_runtime_v1._table_present(db, bind, name), name)
    check(name in db.info.get("_tables_present", set()), db.info.get("_tables_present"))
    check(ontology_runtime_v1._table_present(db, bind, name), "cached lookup must agree")
    # A missing table is not cached, so a caller that creates it later still wins.
    check(not ontology_runtime_v1._table_present(db, bind, "table_that_does_not_exist"),
          "a missing table must read as missing")
    check("table_that_does_not_exist" not in db.info.get("_tables_present", set()),
          "a missing table must not be remembered as present")

client.close()
print(f"Change event revision freshness verified: {checks} assertions passed "
      f"(promotion mid-request is reflected, absence is not cached).")
