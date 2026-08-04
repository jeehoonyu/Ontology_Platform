"""Verify the standalone pull executor without a live API or OCI daemon."""

import os

from app import plugin_executor


os.environ["PLUGIN_SANDBOX_IMAGE"] = "registry.example/plugin@sha256:" + "a" * 64


class FakeApi:
    def __init__(self, *, fail=False):
        self.calls = []
        self.fail = fail
        self.claimed = False

    def request(self, method, path, body=None):
        self.calls.append((method, path, body))
        if path == "/jobs/claim":
            if self.claimed:
                return {"job": None}
            self.claimed = True
            return {"job": {"id": "job-1", "lease_token": "lease-1"}}
        if path == "/api/v1/plugins/workers/work":
            return {"execution_id": "run-1"}
        return {}


config = plugin_executor.ExecutorConfig(
    api_url="http://api:8000", token="secret", worker_name="executor-1", project_id="default",
    heartbeat_seconds=0.01, poll_seconds=0.01,
)
api = FakeApi()
executor = plugin_executor.PluginExecutor(config, api=api)
original = plugin_executor.execute_plugin_work
plugin_executor.execute_plugin_work = lambda _work: ({"value": 1}, {"mode": "oci", "network": "none"}, 12)
executor.register()
executor.heartbeat_worker()
worker_updates = [body for _, path, body in api.calls if path.endswith("/heartbeat") or path.endswith("executor-1")]
assert all(update["labels"]["egress_proxy"] == "disabled" for update in worker_updates)
assert executor.run_once() is True
assert any(path == "/api/v1/plugins/workers/complete" and body["output"] == {"value": 1} for _, path, body in api.calls)
assert executor.stop_event.is_set() is False

api = FakeApi(fail=True)
executor = plugin_executor.PluginExecutor(config, api=api)


def failed(_work):
    raise plugin_executor.PluginRunError("sandbox unavailable", retriable=True, sandbox={"mode": "oci"}, duration_ms=3)


plugin_executor.execute_plugin_work = failed
assert executor.run_once() is True
assert any(path == "/api/v1/plugins/workers/fail" and body["retriable"] is True for _, path, body in api.calls)
plugin_executor.execute_plugin_work = original

os.environ["PLUGIN_EXECUTOR_TOKEN"] = "test-token"
assert plugin_executor.ExecutorConfig.from_env().api_url == "http://127.0.0.1:8000"
os.environ.pop("PLUGIN_EXECUTOR_TOKEN")
os.environ.pop("PLUGIN_SANDBOX_IMAGE")
print("Standalone plugin executor verified: capability registration, leased work, completion, failure, and independent lifecycle signals.")
