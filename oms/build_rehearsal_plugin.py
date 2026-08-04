"""Build an ephemeral signed plugin fixture for production acceptance rehearsals."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import secrets
import zipfile

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def canonical_manifest(manifest: dict) -> bytes:
    return json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode("utf-8")


def build_bundle() -> bytes:
    source = """\
def handle(request):
    import time

    operation = request["operation"]
    delay = float(request.get("input", {}).get("delay_seconds", 0))
    if operation == "slow" and delay:
        time.sleep(delay)
    return {
        "operation": operation,
        "marker": request.get("input", {}).get("marker", "production-rehearsal"),
        "attempt_safe": True,
    }
"""
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("plugin.py", source)
    return stream.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", default=secrets.token_hex(6))
    args = parser.parse_args()
    suffix = "".join(character for character in args.suffix.lower() if character.isalnum())[:24]
    if not suffix:
        raise SystemExit("suffix must contain at least one alphanumeric character")

    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.Raw,
        serialization.PublicFormat.Raw,
    )
    bundle = build_bundle()
    object_schema = {
        "type": "object",
        "properties": {
            "marker": {"type": "string", "maxLength": 200},
            "delay_seconds": {"type": "number", "minimum": 0, "maximum": 35},
        },
        "additionalProperties": False,
    }
    output_schema = {
        "type": "object",
        "properties": {
            "operation": {"type": "string"},
            "marker": {"type": "string"},
            "attempt_safe": {"type": "boolean"},
        },
        "required": ["operation", "marker", "attempt_safe"],
        "additionalProperties": False,
    }
    manifest = {
        "schema_version": 1,
        "sdk_api_version": 1,
        "plugin_id": f"rehearsal.signed-transform-{suffix}",
        "version": "1.0.0",
        "kind": "transform",
        "runtime": "python3",
        "entrypoint": "plugin.py",
        "bundle_sha256": hashlib.sha256(bundle).hexdigest(),
        "capabilities": ["scratch_write"],
        "operations": {
            "fast": {"input_schema": object_schema, "output_schema": output_schema},
            "slow": {"input_schema": object_schema, "output_schema": output_schema},
        },
        "limits": {
            "timeout_seconds": 40,
            "memory_mb": 128,
            "max_input_bytes": 100_000,
            "max_output_bytes": 100_000,
        },
    }
    signature = private_key.sign(canonical_manifest(manifest))
    print(json.dumps({
        "suffix": suffix,
        "trust_key": {
            "id": f"rehearsal-key-{suffix}",
            "organization_id": "pilot",
            "display_name": "Production rehearsal signing key",
            "public_key": base64.b64encode(public_key).decode("ascii"),
        },
        "register": {
            "project_id": "default",
            "manifest": manifest,
            "bundle_base64": base64.b64encode(bundle).decode("ascii"),
            "signer_key_id": f"rehearsal-key-{suffix}",
            "signature": base64.b64encode(signature).decode("ascii"),
        },
    }, separators=(",", ":")))


if __name__ == "__main__":
    main()
