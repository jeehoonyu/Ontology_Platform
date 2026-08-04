"""Execute the real hardened plugin OCI boundary without application dependencies."""
from __future__ import annotations

import argparse
import base64
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import zipfile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "oms"))
from app.plugin_oci import PLUGIN_SDK_API_VERSION, build_oci_command, is_digest_pinned_image  # noqa: E402


def _bundle(source: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.py", source)
    return buffer.getvalue()


def _execute(
    image: str,
    source: str,
    *,
    operation: str = "rehearse",
    sdk_api_version: int = PLUGIN_SDK_API_VERSION,
) -> tuple[subprocess.CompletedProcess[str], dict, list[str]]:
    os.environ["PLUGIN_SANDBOX_IMAGE"] = image
    raw = _bundle(source)
    command, environment, sandbox = build_oci_command(
        manifest={"limits": {"memory_mb": 128}}, capabilities=[], production=True
    )
    envelope = {
        "bundle_root": "/scratch/bundle",
        "scratch_root": "/scratch",
        "entrypoint": "plugin.py",
        "capabilities": [],
        "operation": operation,
        "input": {"records": [{"asset_name": " Pump 4 ", "criticality": "HIGH"}]},
        "sdk_api_version": sdk_api_version,
        "bundle_base64": base64.b64encode(raw).decode("ascii"),
        "bundle_sha256": hashlib.sha256(raw).hexdigest(),
    }
    completed = subprocess.run(
        command,
        input=json.dumps(envelope, separators=(",", ":")),
        text=True,
        capture_output=True,
        timeout=45,
        env=environment,
        check=False,
    )
    return completed, sandbox, command


def _result(completed: subprocess.CompletedProcess[str]) -> dict:
    try:
        return json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise AssertionError(f"Sandbox did not return JSON: {completed.stdout!r} {completed.stderr!r}") from exc


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, help="Digest-pinned sandbox image ID or repository digest")
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    assert is_digest_pinned_image(args.image), "The rehearsal requires a digest-pinned image"

    success_source = (ROOT / "plugin-sdk" / "examples" / "normalize_transform" / "plugin.py").read_text(encoding="utf-8")
    success, sandbox, command = _execute(args.image, success_source, operation="normalize")
    success_result = _result(success)
    assert success.returncode == 0 and success_result.get("ok") is True, (success.stdout, success.stderr)
    output = success_result["output"]
    assert output["records"] == [{"asset_name": "Pump 4", "criticality": "high"}], output
    assert output["metrics"] == {"rows": 1}, output

    denial_cases = {
        "filesystem": "def handle(request):\n    open('/etc/passwd').read()\n    return {}\n",
        "network": "import socket\ndef handle(request):\n    socket.create_connection(('127.0.0.1', 9), timeout=0.1)\n    return {}\n",
        "subprocess": "import subprocess\ndef handle(request):\n    subprocess.run(['python', '-V'])\n    return {}\n",
    }
    denials = {}
    for name, source in denial_cases.items():
        completed, _, _ = _execute(args.image, source)
        result = _result(completed)
        assert completed.returncode != 0 and result.get("ok") is False, (name, completed.stdout, completed.stderr)
        denials[name] = result["error"]

    incompatible, _, _ = _execute(args.image, "def handle(request): return {}\n", sdk_api_version=999)
    incompatible_result = _result(incompatible)
    assert incompatible.returncode != 0 and "Unsupported plugin SDK API version" in incompatible_result.get("error", "")

    required_flags = {"--read-only", "--cap-drop", "--security-opt", "--pids-limit", "--memory", "--cpus", "--user", "--tmpfs"}
    assert required_flags <= set(command), command
    assert command[command.index("--network") + 1] == "none", command
    assert sandbox["sdk_api_version"] == PLUGIN_SDK_API_VERSION and sandbox["non_root"] is True

    evidence = {
        "status": "PASS",
        "executed_at": datetime.now(timezone.utc).isoformat(),
        "image": args.image,
        "sdk_api_version": PLUGIN_SDK_API_VERSION,
        "sandbox": sandbox,
        "verified_denials": sorted(denials),
        "sdk_version_denial": True,
        "output": output,
    }
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(evidence, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
