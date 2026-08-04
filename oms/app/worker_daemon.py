"""Independently deployable durable-job worker process."""
from __future__ import annotations

import json
import os
import signal
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional


JOB_ENDPOINTS = {
    "pipeline": ("pipeline.preview", "pipeline.deliver", "pipeline.duckdb.preview", "pipeline.duckdb.deliver", "industrial.ontology_hydrate", "/pipeline-builder/workers/run-next"),
    "aip": ("aip.agent.invoke", "/aip/agents/workers/run-next"),
    "ingestion": ("ingestion.connector_sync", "ingestion.stream_replay", "/ingestion/workers/run-next"),
    "events": ("event.dispatch", "/api/v1/outbox/workers/run-next"),
    "events-kafka": ("event.kafka.dispatch", "/api/v1/outbox/kafka/workers/run-next"),
    "event-routing": ("event.stream.route", "/api/v1/event-stream-bindings/workers/run-next"),
    "stream-processing": ("stream.process", "/api/v1/streams/processors/workers/run-next"),
}
KNOWN_JOB_TYPES = {job_type for values in JOB_ENDPOINTS.values() for job_type in values[:-1]}


class WorkerApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Worker API returned HTTP {status}: {message}")
        self.status = status


@dataclass(frozen=True)
class WorkerConfig:
    api_url: str
    token: str
    worker_name: str
    project_id: Optional[str]
    supported_job_types: List[str]
    max_concurrency: int = 2
    lease_seconds: int = 120
    poll_interval_seconds: float = 1.0
    heartbeat_interval_seconds: float = 20.0
    request_timeout_seconds: int = 3700
    health_host: str = "0.0.0.0"
    health_port: int = 8091

    @classmethod
    def from_env(cls) -> "WorkerConfig":
        api_url = os.getenv("WORKER_API_URL", "http://127.0.0.1:8000").rstrip("/")
        parsed = urllib.parse.urlsplit(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("WORKER_API_URL must be an http or https URL")
        token = os.getenv("WORKER_TOKEN", "").strip()
        if not token:
            raise ValueError("WORKER_TOKEN is required")
        capabilities = [item.strip() for item in os.getenv(
            "WORKER_JOB_TYPES", ",".join(sorted(KNOWN_JOB_TYPES)),
        ).split(",") if item.strip()]
        unknown = sorted(set(capabilities) - KNOWN_JOB_TYPES)
        if unknown:
            raise ValueError(f"Unsupported WORKER_JOB_TYPES: {', '.join(unknown)}")
        if not capabilities:
            raise ValueError("WORKER_JOB_TYPES must include at least one supported type")
        return cls(
            api_url=api_url,
            token=token,
            worker_name=os.getenv("WORKER_NAME", "ontology-worker-1").strip(),
            project_id=os.getenv("WORKER_PROJECT_ID", "").strip() or None,
            supported_job_types=capabilities,
            max_concurrency=max(1, min(100, int(os.getenv("WORKER_CONCURRENCY", "2")))),
            lease_seconds=max(10, min(900, int(os.getenv("WORKER_LEASE_SECONDS", "120")))),
            poll_interval_seconds=max(0.05, float(os.getenv("WORKER_POLL_SECONDS", "1"))),
            heartbeat_interval_seconds=max(1.0, float(os.getenv("WORKER_HEARTBEAT_SECONDS", "20"))),
            request_timeout_seconds=max(10, int(os.getenv("WORKER_REQUEST_TIMEOUT_SECONDS", "3700"))),
            health_host=os.getenv("WORKER_HEALTH_HOST", "0.0.0.0"),
            health_port=max(1, min(65535, int(os.getenv("WORKER_HEALTH_PORT", "8091")))),
        )


class WorkerApi:
    def __init__(self, config: WorkerConfig):
        self.config = config

    def request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.api_url}{path}", data=payload, method=method,
            headers={
                "Authorization": f"Bearer {self.config.token}",
                "Accept": "application/json",
                **({"Content-Type": "application/json"} if payload is not None else {}),
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.config.request_timeout_seconds) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read(1000).decode("utf-8", errors="replace")
            raise WorkerApiError(exc.code, detail) from exc
        except urllib.error.URLError as exc:
            raise WorkerApiError(0, type(exc.reason).__name__) from exc
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WorkerApiError(502, "API returned invalid JSON") from exc
        return value if isinstance(value, dict) else {"result": value}


class WorkerDaemon:
    def __init__(self, config: WorkerConfig, api: Optional[WorkerApi] = None):
        self.config = config
        self.api = api or WorkerApi(config)
        self.stop_event = threading.Event()
        self.registered = False
        self.started_at = int(time.time())
        self._lock = threading.Lock()
        self._metrics: Dict[str, Any] = {
            "requests": 0, "jobs_seen": 0, "jobs_succeeded": 0, "jobs_failed": 0,
            "api_errors": 0, "last_error": None, "last_job_id": None, "last_heartbeat_at": None,
        }
        self._health_server: Optional[ThreadingHTTPServer] = None

    @property
    def endpoints(self) -> List[str]:
        enabled = set(self.config.supported_job_types)
        return [values[-1] for values in JOB_ENDPOINTS.values() if enabled.intersection(values[:-1])]

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return {
                "status": "DRAINING" if self.stop_event.is_set() else ("READY" if self.registered else "STARTING"),
                "worker_name": self.config.worker_name,
                "project_id": self.config.project_id,
                "supported_job_types": self.config.supported_job_types,
                "max_concurrency": self.config.max_concurrency,
                "started_at": self.started_at,
                **self._metrics,
            }

    def _record(self, **values: Any) -> None:
        with self._lock:
            for key, value in values.items():
                if key.endswith("_increment"):
                    metric = key[:-10]
                    self._metrics[metric] = int(self._metrics.get(metric, 0)) + int(value)
                else:
                    self._metrics[key] = value

    def register(self) -> Dict[str, Any]:
        response = self.api.request("PUT", f"/runtime/workers/{urllib.parse.quote(self.config.worker_name, safe='')}", {
            "project_id": self.config.project_id,
            "supported_job_types": self.config.supported_job_types,
            "max_concurrency": self.config.max_concurrency,
            "labels": {"runtime": "python-daemon", "health_port": str(self.config.health_port)},
        })
        self.registered = True
        return response

    def heartbeat(self) -> None:
        self.api.request("POST", f"/runtime/workers/{urllib.parse.quote(self.config.worker_name, safe='')}/heartbeat", {
            "labels": {"runtime": "python-daemon", "health": "ready"},
        })
        self._record(last_heartbeat_at=int(time.time()))

    def drain(self) -> None:
        if not self.registered:
            return
        try:
            self.api.request("POST", f"/runtime/workers/{urllib.parse.quote(self.config.worker_name, safe='')}/drain", {})
        except WorkerApiError as exc:
            self._record(api_errors_increment=1, last_error=str(exc))

    def _heartbeat_loop(self) -> None:
        while not self.stop_event.wait(self.config.heartbeat_interval_seconds):
            try:
                self.heartbeat()
            except WorkerApiError as exc:
                self._record(api_errors_increment=1, last_error=str(exc))

    def _execute_once(self, endpoint: str) -> bool:
        self._record(requests_increment=1)
        try:
            response = self.api.request("POST", endpoint, {
                "worker_id": self.config.worker_name,
                "lease_seconds": self.config.lease_seconds,
            })
        except WorkerApiError as exc:
            self._record(api_errors_increment=1, last_error=str(exc))
            if exc.status in {401, 403}:
                self.stop_event.set()
            return False
        except Exception as exc:
            self._record(api_errors_increment=1, last_error=f"Worker execution request failed ({type(exc).__name__})")
            return False
        job = response.get("job") or response.get("delivery") or response.get("outbox")
        if not isinstance(job, dict):
            return False
        status = str(job.get("status") or "")
        self._record(
            jobs_seen_increment=1,
            jobs_succeeded_increment=1 if status in {"SUCCEEDED", "PUBLISHED", "DELIVERED"} else 0,
            jobs_failed_increment=1 if status in {"FAILED", "CANCELLED", "DEAD_LETTER"} else 0,
            last_job_id=job.get("id"),
            last_error=job.get("error") if status == "FAILED" else None,
        )
        return True

    def _start_health_server(self) -> None:
        daemon = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                snapshot = daemon.snapshot()
                if self.path not in {"/health/live", "/health/ready", "/metrics"}:
                    self.send_error(404)
                    return
                ready = self.path != "/health/ready" or snapshot["status"] == "READY"
                raw = json.dumps(snapshot, separators=(",", ":")).encode("utf-8")
                self.send_response(200 if ready else 503)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

            def log_message(self, *_args):
                return

        self._health_server = ThreadingHTTPServer((self.config.health_host, self.config.health_port), Handler)
        threading.Thread(target=self._health_server.serve_forever, name="worker-health", daemon=True).start()

    def request_stop(self) -> None:
        self.stop_event.set()

    def run(self, max_cycles: Optional[int] = None) -> Dict[str, Any]:
        self._start_health_server()
        heartbeat_thread: Optional[threading.Thread] = None
        cycles = 0
        try:
            self.register()
            self.heartbeat()
            heartbeat_thread = threading.Thread(target=self._heartbeat_loop, name="worker-heartbeat", daemon=True)
            heartbeat_thread.start()
            endpoint_index = 0
            futures: Dict[Future[bool], str] = {}
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency, thread_name_prefix="job-worker") as pool:
                while not self.stop_event.is_set():
                    while len(futures) < self.config.max_concurrency and not self.stop_event.is_set():
                        endpoint = self.endpoints[endpoint_index % len(self.endpoints)]
                        endpoint_index += 1
                        futures[pool.submit(self._execute_once, endpoint)] = endpoint
                    done, _ = wait(futures, timeout=self.config.poll_interval_seconds, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    found_work = False
                    for future in done:
                        futures.pop(future, None)
                        found_work = future.result() or found_work
                        cycles += 1
                    if max_cycles is not None and cycles >= max_cycles:
                        self.stop_event.set()
                    elif not found_work:
                        self.stop_event.wait(self.config.poll_interval_seconds)
        finally:
            self.stop_event.set()
            self.drain()
            if heartbeat_thread:
                heartbeat_thread.join(timeout=2)
            if self._health_server:
                self._health_server.shutdown()
                self._health_server.server_close()
        return self.snapshot()


def main() -> None:
    config = WorkerConfig.from_env()
    daemon = WorkerDaemon(config)

    def stop(_signum, _frame):
        daemon.request_stop()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    daemon.run()


if __name__ == "__main__":
    main()
