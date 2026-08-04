"""Install generated ontology SDK packages in clean consumer directories."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from types import SimpleNamespace

from app.ontology_registry import _python_package, _typescript_package


entry = SimpleNamespace(
    id="ontology_registry_installation_test",
    project_id="default",
    channel="production",
    version="1.2.3",
    revision_id="ontology_revision_installation_test",
    checksum="a" * 64,
    contract_schema={"$schema": "https://json-schema.org/draft/2020-12/schema", "title": "Installation test"},
    manifest={
        "object_types": [{
            "id": "industrial_asset",
            "primary_key": "asset_id",
            "properties": {
                "asset_id": {"base_type": "string", "required": True},
                "risk_score": {"base_type": "double"},
            },
        }],
        "action_types": [{"id": "request_inspection"}],
    },
)


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=120,
        check=False,
    )
    if result.returncode:
        raise AssertionError(
            f"Command failed ({result.returncode}): {' '.join(command)}\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
        )
    return result


with tempfile.TemporaryDirectory(prefix="ontology-sdk-install-") as temporary_directory:
    root = Path(temporary_directory)

    python_package = _python_package(entry)
    wheel_path = root / python_package["filename"]
    wheel_path.write_bytes(python_package["payload"])
    python_target = root / "python-target"
    run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-deps", "--no-index", "--target", str(python_target), str(wheel_path)],
        cwd=root,
    )
    python_environment = os.environ.copy()
    python_environment["PYTHONPATH"] = str(python_target)
    python_result = run(
        [
            sys.executable,
            "-c",
            (
                "from ontologyos_default_production import IndustrialAsset, OntologyClient; "
                "asset = IndustrialAsset(asset_id='asset-1', risk_score=0.91); "
                "client = OntologyClient('http://127.0.0.1:8000/'); "
                "print(asset.asset_id, asset.risk_score, client.base_url)"
            ),
        ],
        cwd=root,
        env=python_environment,
    )
    assert python_result.stdout.strip() == "asset-1 0.91 http://127.0.0.1:8000"

    npm_package = _typescript_package(entry)
    archive_path = root / npm_package["filename"]
    archive_path.write_bytes(npm_package["payload"])
    npm_project = root / "npm-consumer"
    npm_project.mkdir()
    (npm_project / "package.json").write_text(
        json.dumps({"name": "ontology-sdk-consumer", "private": True, "type": "module"}),
        encoding="utf-8",
    )
    npm_executable = shutil.which("npm") or shutil.which("npm.cmd")
    node_executable = shutil.which("node") or shutil.which("node.exe")
    assert npm_executable and node_executable, "Node.js and npm are required for ontology SDK installation verification"
    run(
        [npm_executable, "install", "--ignore-scripts", "--no-audit", "--no-fund", str(archive_path)],
        cwd=npm_project,
    )
    node_result = run(
        [
            node_executable,
            "--input-type=module",
            "-e",
            (
                "import { OntologyClient } from '@ontologyos/default-production'; "
                "const client = new OntologyClient('http://127.0.0.1:8000/'); "
                "console.log(client.baseUrl, typeof client.industrialAsset.get, typeof client.executeRequestInspection);"
            ),
        ],
        cwd=npm_project,
    )
    assert node_result.stdout.strip() == "http://127.0.0.1:8000 function function"

print("Ontology SDK clean-install verification passed for Python wheel and npm package.")
