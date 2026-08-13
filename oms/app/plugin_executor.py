"""Pull-based plugin executor that owns OCI access outside the API process."""
from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
import signal
import subprocess
import threading
import time
from typing import Any, Dict, Optional
import urllib.error
import urllib.parse
import urllib.request

from .plugin_oci import build_oci_command, is_digest_pinned_image
from .plugin_egress import validated_ca_bundle


_SAFE_RUNTIME_NAME = __import__("re").compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]{0,127}$")


class ExecutorApiError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(f"Executor API returned HTTP {status}: {message}")
        self.status = status


class PluginRunError(RuntimeError):
    def __init__(self, message: str, *, retriable: bool, sandbox: Optional[Dict[str, Any]] = None, duration_ms: int = 0):
        super().__init__(message)
        self.retriable = retriable
        self.sandbox = sandbox or {}
        self.duration_ms = duration_ms


def _oci(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    executable = os.getenv("PLUGIN_OCI_EXECUTABLE", "docker")
    completed = subprocess.run(
        [executable, *arguments], text=True, capture_output=True, timeout=60, check=False,
        env={key: value for key, value in os.environ.items() if key.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "DOCKER_HOST", "DOCKER_CONTEXT"}},
    )
    if check and completed.returncode != 0:
        raise RuntimeError(f"OCI egress boundary command failed: {(completed.stderr or completed.stdout)[:1000]}")
    return completed


def ensure_egress_boundary() -> bool:
    """Provision one proxy inside the isolated OCI daemon, never inside the API."""
    image = os.getenv("PLUGIN_EGRESS_PROXY_IMAGE", "").strip()
    if not image:
        return False
    if not is_digest_pinned_image(image):
        raise RuntimeError("PLUGIN_EGRESS_PROXY_IMAGE must be digest-pinned")
    secret = os.getenv("PLUGIN_EGRESS_TOKEN_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError("PLUGIN_EGRESS_TOKEN_SECRET must contain at least 32 characters")
    network = os.getenv("PLUGIN_SANDBOX_NETWORK", "ontology-plugin-egress").strip()
    name = os.getenv("PLUGIN_EGRESS_PROXY_NAME", "plugin-egress-proxy").strip()
    if not _SAFE_RUNTIME_NAME.fullmatch(network) or network.lower() in {"bridge", "host", "default", "none"}:
        raise RuntimeError("PLUGIN_SANDBOX_NETWORK must be a dedicated runtime name")
    if not _SAFE_RUNTIME_NAME.fullmatch(name):
        raise RuntimeError("PLUGIN_EGRESS_PROXY_NAME is invalid")

    allow_private = os.getenv("PLUGIN_EGRESS_ALLOW_PRIVATE", "false").strip().lower()
    boundary_fingerprint = hashlib.sha256(
        json.dumps({
            "image": image,
            "network": network,
            "allow_private": allow_private,
            "secret": secret,
        }, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    inspected_network = _oci("network", "inspect", "--format", "{{.Internal}}", network, check=False)
    if inspected_network.returncode != 0:
        _oci("network", "create", "--internal", "--driver", "bridge", network)
    elif inspected_network.stdout.strip().lower() != "true":
        raise RuntimeError("PLUGIN_SANDBOX_NETWORK exists but is not internal")

    inspect_format = "{{.State.Running}}|{{index .Config.Labels \"ontology.egress.boundary\"}}"
    inspected_proxy = _oci("inspect", "--format", inspect_format, name, check=False)
    if inspected_proxy.returncode == 0:
        running, _, fingerprint = inspected_proxy.stdout.strip().partition("|")
        if fingerprint != boundary_fingerprint:
            _oci("rm", "--force", name)
        elif running.lower() != "true":
            _oci("start", name)
            return True
        else:
            return True

    command = [
        "run", "--detach", "--name", name, "--restart", "unless-stopped",
        "--label", f"ontology.egress.boundary={boundary_fingerprint}",
        "--network", network, "--read-only", "--cap-drop", "ALL",
        "--security-opt", "no-new-privileges", "--pids-limit", "128",
        "--memory", "128m", "--cpus", "0.5", "--user", "65534:65534",
        "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=8m,mode=1777",
        "--env", f"PLUGIN_EGRESS_TOKEN_SECRET={secret}",
        "--env", f"PLUGIN_EGRESS_ALLOW_PRIVATE={allow_private}",
        image,
    ]
    created = _oci(*command, check=False)
    if created.returncode != 0:
        # Another executor may have won the create race. Reuse only an exact
        # boundary match; otherwise fail closed and leave diagnosis intact.
        raced = _oci("inspect", "--format", inspect_format, name, check=False)
        if raced.returncode != 0 or raced.stdout.strip().partition("|")[2] != boundary_fingerprint:
            raise RuntimeError(f"OCI egress boundary command failed: {(created.stderr or created.stdout)[:1000]}")
    # Only the proxy gets an uplink. Sandboxes remain attached solely to the
    # internal network and can reach no destination except this proxy.
    connected = _oci("network", "connect", "bridge", name, check=False)
    if connected.returncode != 0 and "already exists" not in (connected.stderr or "").lower():
        raise RuntimeError(f"Could not attach egress proxy uplink: {(connected.stderr or connected.stdout)[:1000]}")
    return True


@dataclass(frozen=True)
class ExecutorConfig:
    api_url: str
    token: str
    worker_name: str
    project_id: Optional[str]
    lease_seconds: int = 600
    heartbeat_seconds: float = 20.0
    poll_seconds: float = 1.0
    request_timeout_seconds: int = 60
    health_host: str = "0.0.0.0"
    health_port: int = 8092

    @classmethod
    def from_env(cls) -> "ExecutorConfig":
        api_url = os.getenv("PLUGIN_EXECUTOR_API_URL", os.getenv("WORKER_API_URL", "http://127.0.0.1:8000")).rstrip("/")
        parsed = urllib.parse.urlsplit(api_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("PLUGIN_EXECUTOR_API_URL must be an http or https URL")
        token = os.getenv("PLUGIN_EXECUTOR_TOKEN", os.getenv("WORKER_TOKEN", "")).strip()
        if not token:
            raise ValueError("PLUGIN_EXECUTOR_TOKEN is required")
        return cls(
            api_url=api_url,
            token=token,
            worker_name=os.getenv("PLUGIN_EXECUTOR_NAME", "ontology-plugin-executor-1").strip(),
            project_id=os.getenv("PLUGIN_EXECUTOR_PROJECT_ID", "").strip() or None,
            lease_seconds=max(10, min(900, int(os.getenv("PLUGIN_EXECUTOR_LEASE_SECONDS", "600")))),
            heartbeat_seconds=max(1.0, float(os.getenv("PLUGIN_EXECUTOR_HEARTBEAT_SECONDS", "20"))),
            poll_seconds=max(0.05, float(os.getenv("PLUGIN_EXECUTOR_POLL_SECONDS", "1"))),
            request_timeout_seconds=max(10, int(os.getenv("PLUGIN_EXECUTOR_REQUEST_TIMEOUT_SECONDS", "60"))),
            health_host=os.getenv("PLUGIN_EXECUTOR_HEALTH_HOST", "0.0.0.0"),
            health_port=max(1, min(65535, int(os.getenv("PLUGIN_EXECUTOR_HEALTH_PORT", "8092")))),
        )


class ExecutorApi:
    def __init__(self, config: ExecutorConfig):
        self.config = config

    def request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        payload = None if body is None else json.dumps(body, separators=(",", ":")).encode("utf-8")
        request = urllib.request.Request(
            f"{self.config.api_url}{path}",
            data=payload,
            method=method,
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
            detail = exc.read(2000).decode("utf-8", errors="replace")
            raise ExecutorApiError(exc.code, detail) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise ExecutorApiError(0, type(getattr(exc, "reason", exc)).__name__) from exc
        if not raw:
            return {}
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ExecutorApiError(502, "API returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise ExecutorApiError(502, "API returned a non-object response")
        return value


def execute_plugin_work(work: Dict[str, Any]) -> tuple[Dict[str, Any], Dict[str, Any], int]:
    manifest = work.get("manifest") or {}
    capabilities = work.get("capabilities") or []
    command, environment, sandbox = build_oci_command(manifest=manifest, capabilities=capabilities, production=True)
    bundle_base64 = str(work.get("bundle_base64") or "")
    try:
        raw = base64.b64decode(bundle_base64, validate=True)
    except ValueError as exc:
        raise PluginRunError("Worker payload contains invalid bundle bytes", retriable=False, sandbox=sandbox) from exc
    if hashlib.sha256(raw).hexdigest() != work.get("bundle_sha256"):
        raise PluginRunError("Worker payload bundle digest mismatch", retriable=False, sandbox=sandbox)
    envelope = {
        "bundle_root": "/scratch/bundle",
        "scratch_root": "/scratch",
        "entrypoint": work["entrypoint"],
        "capabilities": capabilities,
        "operation": work["operation"],
        "input": work.get("input") or {},
        "sdk_api_version": work["sdk_api_version"],
        "bundle_base64": bundle_base64,
        "bundle_sha256": work["bundle_sha256"],
    }
    ca_bundle, _ = validated_ca_bundle(manifest)
    if ca_bundle:
        envelope["tls_ca_bundle_pem"] = ca_bundle
    limits = manifest.get("limits") or {}
    timeout = int(limits.get("timeout_seconds", 30))
    maximum = int(limits.get("max_output_bytes", 1_000_000))
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            input=json.dumps(envelope, separators=(",", ":")),
            text=True,
            capture_output=True,
            timeout=timeout,
            env=environment,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        duration = max(0, int((time.perf_counter() - started) * 1000))
        retriable = isinstance(exc, OSError)
        raise PluginRunError(f"OCI execution {type(exc).__name__}", retriable=retriable, sandbox=sandbox, duration_ms=duration) from exc
    duration = max(0, int((time.perf_counter() - started) * 1000))
    if len(completed.stdout.encode("utf-8", errors="replace")) > maximum or len(completed.stderr.encode("utf-8", errors="replace")) > maximum:
        raise PluginRunError("Plugin exceeded output size limit", retriable=False, sandbox=sandbox, duration_ms=duration)
    try:
        result = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        # Docker/runtime failures generally do not produce the runner envelope and are retryable.
        raise PluginRunError("OCI runtime returned invalid JSON", retriable=True, sandbox=sandbox, duration_ms=duration) from exc
    if completed.returncode != 0 or not result.get("ok", completed.returncode == 0):
        message = str(result.get("error") or completed.stderr or f"exit code {completed.returncode}")[:2000]
        raise PluginRunError(f"Plugin execution failed: {message}", retriable=False, sandbox=sandbox, duration_ms=duration)
    output = result.get("output", result)
    if not isinstance(output, dict):
        raise PluginRunError("Plugin output must be an object", retriable=False, sandbox=sandbox, duration_ms=duration)
    return output, sandbox, duration


class PluginExecutor:
    def __init__(self, config: ExecutorConfig, api: Optional[ExecutorApi] = None):
        self.config = config
        self.api = api or ExecutorApi(config)
        self.stop_event = threading.Event()
        self.started_at = int(time.time())
        self.registered = False
        self.current_job_id: Optional[str] = None
        self.last_error: Optional[str] = None
        self.completed_jobs = 0
        self.failed_jobs = 0
        self.egress_proxy_ready = False
        self._health_server: Optional[ThreadingHTTPServer] = None
        self._state_lock = threading.Lock()

    def snapshot(self) -> Dict[str, Any]:
        with self._state_lock:
            return {
                "status": "STOPPING" if self.stop_event.is_set() else ("READY" if self.registered else "STARTING"),
                "worker_name": self.config.worker_name,
                "project_id": self.config.project_id,
                "capabilities": ["plugin.execute"],
                "current_job_id": self.current_job_id,
                "completed_jobs": self.completed_jobs,
                "failed_jobs": self.failed_jobs,
                "egress_proxy_ready": self.egress_proxy_ready,
                "last_error": self.last_error,
                "started_at": self.started_at,
            }

    def _start_health_server(self) -> None:
        executor = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path not in {"/health/live", "/health/ready", "/metrics"}:
                    self.send_error(404)
                    return
                snapshot = executor.snapshot()
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
        threading.Thread(target=self._health_server.serve_forever, name="plugin-executor-health", daemon=True).start()

    def register(self) -> Dict[str, Any]:
        self.egress_proxy_ready = ensure_egress_boundary()
        result = self.api.request("PUT", f"/runtime/workers/{urllib.parse.quote(self.config.worker_name, safe='')}", {
            "project_id": self.config.project_id,
            "supported_job_types": ["plugin.execute"],
            "max_concurrency": 1,
            "labels": self._worker_labels(),
        })
        with self._state_lock:
            self.registered = True
            self.last_error = None
        return result

    def _worker_labels(self) -> Dict[str, str]:
        return {
            "runtime": "plugin-oci-executor",
            "health": "ready" if self.registered else "starting",
            "sandbox_image": os.getenv("PLUGIN_SANDBOX_IMAGE", ""),
            "egress_proxy": "ready" if self.egress_proxy_ready else "disabled",
        }

    def heartbeat_worker(self) -> None:
        self.api.request("POST", f"/runtime/workers/{urllib.parse.quote(self.config.worker_name, safe='')}/heartbeat", {
            "labels": self._worker_labels(),
        })

    def _worker_heartbeat_loop(self) -> None:
        while not self.stop_event.wait(self.config.heartbeat_seconds):
            try:
                self.heartbeat_worker()
            except ExecutorApiError as exc:
                with self._state_lock:
                    self.last_error = str(exc)
                if exc.status in {401, 403}:
                    self.stop_event.set()
                    return

    def _job_heartbeat(self, job_id: str, lease_token: str, heartbeat_stop: threading.Event) -> None:
        while not heartbeat_stop.wait(self.config.heartbeat_seconds):
            try:
                self.api.request("POST", f"/jobs/{urllib.parse.quote(job_id, safe='')}/heartbeat", {
                    "lease_token": lease_token,
                    "progress": 50,
                    "message": "Plugin sandbox is running",
                    "metrics": {"executor": self.config.worker_name},
                    "lease_seconds": self.config.lease_seconds,
                })
            except ExecutorApiError:
                return

    def run_once(self) -> bool:
        claimed = self.api.request("POST", "/jobs/claim", {
            "worker_id": self.config.worker_name,
            "supported_job_types": ["plugin.execute"],
            "project_id": self.config.project_id,
            "lease_seconds": self.config.lease_seconds,
        })
        job = claimed.get("job")
        if not isinstance(job, dict):
            return False
        job_id = str(job["id"])
        lease_token = str(job["lease_token"])
        with self._state_lock:
            self.current_job_id = job_id
            self.last_error = None
        heartbeat_stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._job_heartbeat,
            args=(job_id, lease_token, heartbeat_stop),
            daemon=True,
        )
        heartbeat.start()
        started = time.perf_counter()
        try:
            work = self.api.request("POST", "/api/v1/plugins/workers/work", {"job_id": job_id, "lease_token": lease_token})
            output, sandbox, duration = execute_plugin_work(work)
            self.api.request("POST", "/api/v1/plugins/workers/complete", {
                "job_id": job_id,
                "lease_token": lease_token,
                "output": output,
                "sandbox": sandbox,
                "exit_code": 0,
                "duration_ms": duration,
            })
            with self._state_lock:
                self.completed_jobs += 1
        except PluginRunError as exc:
            self.api.request("POST", "/api/v1/plugins/workers/fail", {
                "job_id": job_id,
                "lease_token": lease_token,
                "error": str(exc),
                "retriable": exc.retriable,
                "retry_delay_seconds": 5,
                "sandbox": exc.sandbox,
                "duration_ms": exc.duration_ms,
            })
            with self._state_lock:
                self.failed_jobs += 1
                self.last_error = str(exc)
        except ExecutorApiError as exc:
            try:
                self.api.request("POST", "/api/v1/plugins/workers/fail", {
                    "job_id": job_id,
                    "lease_token": lease_token,
                    "error": str(exc),
                    "retriable": exc.status == 0 or exc.status >= 500,
                    "retry_delay_seconds": 5,
                    "sandbox": {"mode": "oci"},
                    "duration_ms": max(0, int((time.perf_counter() - started) * 1000)),
                })
            except ExecutorApiError:
                pass
            with self._state_lock:
                self.failed_jobs += 1
                self.last_error = str(exc)
        finally:
            heartbeat_stop.set()
            heartbeat.join(timeout=2)
            with self._state_lock:
                self.current_job_id = None
        return True

    def run(self, max_cycles: Optional[int] = None) -> None:
        self._start_health_server()
        worker_heartbeat: Optional[threading.Thread] = None
        try:
            self.register()
            self.heartbeat_worker()
            worker_heartbeat = threading.Thread(
                target=self._worker_heartbeat_loop,
                name="plugin-worker-heartbeat",
                daemon=True,
            )
            worker_heartbeat.start()
            cycles = 0
            while not self.stop_event.is_set():
                found = self.run_once()
                cycles += 1
                if max_cycles is not None and cycles >= max_cycles:
                    return
                if not found:
                    self.stop_event.wait(self.config.poll_seconds)
        finally:
            self.stop_event.set()
            if worker_heartbeat:
                worker_heartbeat.join(timeout=2)
            if self._health_server:
                self._health_server.shutdown()
                self._health_server.server_close()


def main() -> None:
    config = ExecutorConfig.from_env()
    maximum = os.getenv("PLUGIN_EXECUTOR_MAX_CYCLES", "").strip()
    executor = PluginExecutor(config)

    def stop(_signum: int, _frame: Any) -> None:
        executor.stop_event.set()

    for signum in (signal.SIGINT, signal.SIGTERM):
        signal.signal(signum, stop)
    executor.run(max_cycles=int(maximum) if maximum else None)


if __name__ == "__main__":
    main()
