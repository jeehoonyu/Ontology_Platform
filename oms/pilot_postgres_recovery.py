"""Reference isolated PostgreSQL backup/restore driver for ``pilot_window``.

The driver deliberately uses a separate Compose project and fresh volumes for
every restore. It never swaps or mutates the live source database. Configuration
is environment based so scheduler commands remain stable across seven days:

    python oms/pilot_postgres_recovery.py backup
    python oms/pilot_postgres_recovery.py restore
    python oms/pilot_postgres_recovery.py cleanup

This logical-backup reference is suitable for a small pilot. Larger deployments
must replace the backup command with tested WAL/incremental infrastructure while
retaining the same isolated restore and evidence protocol.
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence
from urllib.request import urlopen

sys.path.insert(0, str(Path(__file__).resolve().parent))

REPO_ROOT = Path(__file__).resolve().parent.parent
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
SAFE_COMPOSE_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]{0,62}$")


def _truthy(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _resolved(path: str, *, base: Path = REPO_ROOT) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = base / candidate
    return candidate.resolve()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


@dataclass(frozen=True)
class Config:
    source_compose_files: tuple[Path, ...]
    source_project: str
    recovery_compose_file: Path
    recovery_project: str
    backup_root: Path
    database_service: str
    api_service: str
    database_user: str
    database_name: str
    source_url: str
    recovery_url: str
    integrity_key: str
    include_snapshots: bool
    include_plugins: bool
    retention_count: int
    ready_timeout_seconds: int

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Config":
        values = os.environ if env is None else env
        compose_value = values.get("PILOT_SOURCE_COMPOSE_FILES", "docker-compose.yml")
        compose_files = tuple(
            _resolved(item) for item in compose_value.split(os.pathsep) if item.strip()
        )
        config = cls(
            source_compose_files=compose_files,
            source_project=values.get("PILOT_SOURCE_PROJECT", "ontology_platform").strip(),
            recovery_compose_file=_resolved(
                values.get("PILOT_RECOVERY_COMPOSE_FILE", "docker-compose.pilot-recovery.yml")
            ),
            recovery_project=values.get("PILOT_RECOVERY_PROJECT", "ontology_pilot_recovery").strip(),
            backup_root=_resolved(values.get("PILOT_BACKUP_ROOT", "pilot-backups")),
            database_service=values.get("PILOT_SOURCE_DATABASE_SERVICE", "postgres").strip(),
            api_service=values.get("PILOT_SOURCE_API_SERVICE", "oms-api").strip(),
            database_user=values.get("POSTGRES_USER", "ontology").strip(),
            database_name=values.get("POSTGRES_DB", "ontology").strip(),
            source_url=values.get("PILOT_SOURCE_URL", "http://127.0.0.1:8000").rstrip("/"),
            recovery_url=values.get("PILOT_RECOVERY_URL", "http://127.0.0.1:18002").rstrip("/"),
            integrity_key=values.get("PILOT_BACKUP_INTEGRITY_KEY", "").strip(),
            include_snapshots=_truthy(values.get("PILOT_BACKUP_SNAPSHOTS", "true")),
            include_plugins=_truthy(values.get("PILOT_BACKUP_PLUGINS", "true")),
            retention_count=int(values.get("PILOT_BACKUP_RETENTION_COUNT", "24")),
            ready_timeout_seconds=int(values.get("PILOT_RECOVERY_READY_TIMEOUT_SECONDS", "900")),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not self.source_compose_files:
            raise ValueError("PILOT_SOURCE_COMPOSE_FILES must name at least one Compose file")
        for path in (*self.source_compose_files, self.recovery_compose_file):
            if not path.is_file():
                raise FileNotFoundError(path)
        if self.source_project == self.recovery_project:
            raise ValueError("Recovery Compose project must differ from the live source project")
        for value in (self.source_project, self.recovery_project, self.database_service, self.api_service):
            if not SAFE_COMPOSE_NAME.fullmatch(value):
                raise ValueError(f"Unsafe Compose identifier: {value!r}")
        for value in (self.database_user, self.database_name):
            if not SAFE_IDENTIFIER.fullmatch(value):
                raise ValueError(f"Unsafe Postgres identifier: {value!r}")
        if self.retention_count < 2:
            raise ValueError("PILOT_BACKUP_RETENTION_COUNT must retain at least two recovery points")
        if self.ready_timeout_seconds <= 0:
            raise ValueError("PILOT_RECOVERY_READY_TIMEOUT_SECONDS must be positive")
        if len(self.integrity_key) < 32:
            raise ValueError("PILOT_BACKUP_INTEGRITY_KEY must contain at least 32 characters")
        from recovery_probe_client import require_isolated_target

        require_isolated_target(self.source_url, self.recovery_url)

    @property
    def latest_path(self) -> Path:
        return self.backup_root / "latest-backup.json"


class DockerCompose:
    def __init__(self, config: Config, *, runner=subprocess.run):
        self.config = config
        self.runner = runner

    def source(self, args: Sequence[str], **kwargs):
        command = ["docker", "compose"]
        for path in self.config.source_compose_files:
            command.extend(("-f", str(path)))
        command.extend(("-p", self.config.source_project, *args))
        return self._run(command, **kwargs)

    def recovery(self, args: Sequence[str], **kwargs):
        command = [
            "docker", "compose", "-f", str(self.config.recovery_compose_file),
            "-p", self.config.recovery_project, *args,
        ]
        return self._run(command, **kwargs)

    def _run(
        self, command: Sequence[str], *, timeout: int = 3600, capture: bool = True,
        env: Optional[Mapping[str, str]] = None,
    ):
        process_env = {
            **os.environ,
            "PILOT_BACKUP_ROOT": str(self.config.backup_root),
            "PILOT_RECOVERY_URL": self.config.recovery_url,
            **(dict(env) if env else {}),
        }
        try:
            return self.runner(
                list(command), cwd=REPO_ROOT, check=True, timeout=timeout,
                text=True, capture_output=capture, env=process_env,
            )
        except subprocess.CalledProcessError as error:
            detail = (error.stderr or error.stdout or "").strip()
            rendered = subprocess.list2cmdline(list(command))
            raise RuntimeError(
                f"Command failed with exit {error.returncode}: {rendered}"
                + (f"\n{detail[-2000:]}" if detail else "")
            ) from error


def _copy_from_service(docker: DockerCompose, service: str, container_path: str, target: Path) -> None:
    docker.source(("cp", f"{service}:{container_path}", str(target)))


def _manifest_digest(payload: Mapping[str, Any], key: str) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), canonical, hashlib.sha256).hexdigest()


def _archive_volume(
    docker: DockerCompose, service: str, directory: str, target: Path, container_path: str
) -> None:
    docker.source(("exec", "-T", service, "sh", "-c", f"mkdir -p '{directory}' && tar -czf '{container_path}' -C '{directory}' ."))
    try:
        _copy_from_service(docker, service, container_path, target)
    finally:
        docker.source(("exec", "-T", service, "rm", "-f", container_path))


def _current_database_head(docker: DockerCompose, *, recovery: bool = False) -> str:
    command = (
        "exec", "-T", "postgres" if recovery else docker.config.database_service,
        "psql", "-At", "-U", docker.config.database_user,
        "-d", docker.config.database_name,
        "-c", "SELECT version_num FROM alembic_version LIMIT 1;",
    )
    result = docker.recovery(command) if recovery else docker.source(command)
    return result.stdout.strip()


def backup(config: Config, docker: Optional[DockerCompose] = None) -> dict[str, Any]:
    from tier_b_evidence import current_head

    docker = docker or DockerCompose(config)
    expected_head = current_head()
    database_head = _current_database_head(docker)
    if database_head != expected_head:
        raise RuntimeError(
            f"Live database migration head {database_head!r} does not match runtime {expected_head!r}"
        )
    config.backup_root.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + f"-{uuid.uuid4().hex[:8]}"
    dump_name = f"ontology-{stamp}.dump"
    dump_path = config.backup_root / dump_name
    container_dump = f"/tmp/{dump_name}"
    docker.source((
        "exec", "-T", config.database_service, "pg_dump", "-U", config.database_user,
        "-d", config.database_name, "-Fc", "-f", container_dump,
    ))
    try:
        docker.source(("exec", "-T", config.database_service, "pg_restore", "--list", container_dump))
        _copy_from_service(docker, config.database_service, container_dump, dump_path)
    finally:
        docker.source(("exec", "-T", config.database_service, "rm", "-f", container_dump))

    files: dict[str, dict[str, Any]] = {
        "database": {"name": dump_name, "sha256": _sha256(dump_path), "size_bytes": dump_path.stat().st_size}
    }
    if config.include_snapshots:
        target = config.backup_root / f"{dump_name}.snapshots.tar.gz"
        _archive_volume(
            docker, config.api_service, "/var/lib/ontology/snapshots", target,
            f"/var/cache/ontology/snapshots/{target.name}",
        )
        files["snapshots"] = {"name": target.name, "sha256": _sha256(target), "size_bytes": target.stat().st_size}
    if config.include_plugins:
        target = config.backup_root / f"{dump_name}.plugins.tar.gz"
        _archive_volume(
            docker, config.api_service, "/var/lib/ontology/plugins", target,
            f"/var/cache/ontology/snapshots/{target.name}",
        )
        files["plugins"] = {"name": target.name, "sha256": _sha256(target), "size_bytes": target.stat().st_size}

    manifest = {
        "schema_version": 1,
        "backup_id": stamp,
        "created_at": int(time.time()),
        "migration_head": database_head,
        "source_project": config.source_project,
        "database": config.database_name,
        "files": files,
    }
    manifest["integrity"] = {
        "algorithm": "HMAC-SHA256",
        "digest": _manifest_digest(manifest, config.integrity_key),
    }
    manifest_path = config.backup_root / f"{dump_name}.json"
    _atomic_json(manifest_path, manifest)
    pointer = {
        "manifest": manifest_path.name,
        "manifest_sha256": _sha256(manifest_path),
        "backup_id": stamp,
        "migration_head": database_head,
    }
    _atomic_json(config.latest_path, pointer)
    _prune(config, keep_manifest=manifest_path.name)
    return {**manifest, "manifest_path": str(manifest_path)}


def _load_backup(config: Config) -> tuple[dict[str, Any], Path]:
    if not config.latest_path.is_file():
        raise RuntimeError("No pilot backup exists; run the backup command first")
    pointer = json.loads(config.latest_path.read_text(encoding="utf-8"))
    manifest_path = config.backup_root / str(pointer.get("manifest") or "")
    if manifest_path.parent.resolve() != config.backup_root.resolve() or not manifest_path.is_file():
        raise RuntimeError("Latest-backup pointer does not reference a valid local manifest")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not hmac.compare_digest(str(pointer.get("manifest_sha256") or ""), _sha256(manifest_path)):
        raise RuntimeError("Latest-backup pointer does not match the manifest bytes")
    if pointer.get("backup_id") != manifest.get("backup_id"):
        raise RuntimeError("Latest-backup pointer and manifest identity differ")
    integrity = manifest.get("integrity") or {}
    unsigned_manifest = {key: value for key, value in manifest.items() if key != "integrity"}
    if integrity.get("algorithm") != "HMAC-SHA256" or not hmac.compare_digest(
        str(integrity.get("digest") or ""),
        _manifest_digest(unsigned_manifest, config.integrity_key),
    ):
        raise RuntimeError("Backup manifest authentication failed")
    for label, spec in (manifest.get("files") or {}).items():
        path = config.backup_root / str(spec.get("name") or "")
        if path.parent.resolve() != config.backup_root.resolve() or not path.is_file():
            raise RuntimeError(f"Backup {label} file is missing")
        if _sha256(path) != spec.get("sha256"):
            raise RuntimeError(f"Backup {label} checksum mismatch")
    return manifest, manifest_path


def _prune(config: Config, *, keep_manifest: str) -> None:
    manifests = sorted(config.backup_root.glob("ontology-*.dump.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    for path in manifests[config.retention_count:]:
        if path.name == keep_manifest:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            for spec in (payload.get("files") or {}).values():
                candidate = config.backup_root / str(spec.get("name") or "")
                if candidate.parent.resolve() == config.backup_root.resolve():
                    candidate.unlink(missing_ok=True)
            path.unlink(missing_ok=True)
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            continue


def _wait_postgres(config: Config, docker: DockerCompose) -> None:
    deadline = time.monotonic() + config.ready_timeout_seconds
    while time.monotonic() < deadline:
        try:
            # PostGIS initialization starts a temporary accepting server while
            # extension scripts are still running. PID 1 becomes postgres only
            # after the entrypoint has completed and execs the final server.
            docker.recovery((
                "exec", "-T", "postgres", "sh", "-c",
                'test "$(cat /proc/1/comm)" = "postgres"',
            ), timeout=10)
            docker.recovery((
                "exec", "-T", "postgres", "pg_isready", "-U", config.database_user,
                "-d", config.database_name,
            ), timeout=10)
            return
        except (subprocess.CalledProcessError, RuntimeError):
            time.sleep(1)
    raise TimeoutError("Isolated recovery Postgres did not become ready")


def _wait_api(config: Config) -> None:
    deadline = time.monotonic() + config.ready_timeout_seconds
    last_error: Optional[Exception] = None
    while time.monotonic() < deadline:
        try:
            with urlopen(f"{config.recovery_url}/health/ready", timeout=5) as response:
                if response.status == 200:
                    return
        except Exception as error:  # readiness must tolerate container startup
            last_error = error
        time.sleep(1)
    raise TimeoutError(f"Isolated recovery API did not become ready: {last_error}")


def restore(config: Config, docker: Optional[DockerCompose] = None) -> dict[str, Any]:
    from tier_b_evidence import current_head

    docker = docker or DockerCompose(config)
    manifest, manifest_path = _load_backup(config)
    if manifest.get("migration_head") != current_head():
        raise RuntimeError("Backup migration head is not the current runtime head")
    started = time.monotonic()
    docker.recovery(("down", "-v", "--remove-orphans"), timeout=900)
    docker.recovery(("up", "-d", "postgres"), timeout=900)
    _wait_postgres(config, docker)

    database_spec = manifest["files"]["database"]
    local_dump = config.backup_root / database_spec["name"]
    container_dump = f"/tmp/{database_spec['name']}"
    docker.recovery(("cp", str(local_dump), f"postgres:{container_dump}"))
    try:
        docker.recovery((
            "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U",
            config.database_user, "-d", "postgres", "-c",
            f'DROP DATABASE IF EXISTS "{config.database_name}" WITH (FORCE);',
        ))
        docker.recovery((
            "exec", "-T", "postgres", "psql", "-v", "ON_ERROR_STOP=1", "-U",
            config.database_user, "-d", "postgres", "-c",
            f'CREATE DATABASE "{config.database_name}" WITH OWNER "{config.database_user}" TEMPLATE template0;',
        ))
        docker.recovery((
            "exec", "-T", "postgres", "pg_restore", "-U", config.database_user,
            "-d", config.database_name, "--exit-on-error", "--no-owner", "--no-privileges",
            container_dump,
        ))
    finally:
        try:
            docker.recovery(("exec", "-T", "postgres", "rm", "-f", container_dump))
        except RuntimeError:
            pass

    restored_head = _current_database_head(docker, recovery=True)
    if restored_head != manifest["migration_head"]:
        raise RuntimeError(
            f"Restored database migration head {restored_head!r} differs from backup {manifest['migration_head']!r}"
        )

    loader_env = os.environ.copy()
    loader_env["PILOT_SNAPSHOT_ARCHIVE"] = (manifest.get("files", {}).get("snapshots") or {}).get("name", "")
    loader_env["PILOT_PLUGIN_ARCHIVE"] = (manifest.get("files", {}).get("plugins") or {}).get("name", "")
    if loader_env["PILOT_SNAPSHOT_ARCHIVE"] or loader_env["PILOT_PLUGIN_ARCHIVE"]:
        docker.recovery(
            ("--profile", "restore-files", "run", "--rm", "recovery-loader"),
            timeout=900,
            env=loader_env,
        )

    docker.recovery(("up", "-d", "oms-api"), timeout=900)
    _wait_api(config)
    receipt = {
        "schema_version": 1,
        "backup_id": manifest["backup_id"],
        "manifest": manifest_path.name,
        "migration_head": restored_head,
        "recovery_project": config.recovery_project,
        "recovery_url": config.recovery_url,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "restored_at": int(time.time()),
        "fresh_volumes": True,
    }
    _atomic_json(config.backup_root / "latest-restore.json", receipt)
    return receipt


def cleanup(config: Config, docker: Optional[DockerCompose] = None) -> dict[str, Any]:
    docker = docker or DockerCompose(config)
    docker.recovery(("down", "-v", "--remove-orphans"), timeout=900)
    return {"recovery_project": config.recovery_project, "removed_volumes": True}


def validate(config: Config, docker: Optional[DockerCompose] = None) -> dict[str, Any]:
    docker = docker or DockerCompose(config)
    docker.source(("config", "--quiet"), timeout=60)
    docker.recovery(("config", "--quiet"), timeout=60)
    return {
        "source_project": config.source_project,
        "recovery_project": config.recovery_project,
        "recovery_url": config.recovery_url,
        "backup_root": str(config.backup_root),
        "isolated": config.source_project != config.recovery_project,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("validate", "backup", "restore", "cleanup"))
    args = parser.parse_args()
    config = Config.from_env()
    result = {
        "validate": validate,
        "backup": backup,
        "restore": restore,
        "cleanup": cleanup,
    }[args.mode](config)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
