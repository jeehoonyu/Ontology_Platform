"""Production requests must rely on migrations instead of request-time schema DDL."""

import os

from app import imports_ops, investigations, ops_control, platform_core, reliability_ops


class NoBindSession:
    def get_bind(self):
        raise AssertionError("Production request attempted runtime schema DDL")


previous = os.environ.get("APP_ENV")
os.environ["APP_ENV"] = "production"
try:
    session = NoBindSession()
    for ensure in (
        imports_ops._ensure_tables,
        investigations._ensure_tables,
        ops_control._ensure_tables,
        platform_core._ensure_tables,
        reliability_ops._ensure_tables,
    ):
        ensure(session)
finally:
    if previous is None:
        os.environ.pop("APP_ENV", None)
    else:
        os.environ["APP_ENV"] = previous

print("Production runtime DDL guard verified: request-time table creation is disabled across five service modules.")
