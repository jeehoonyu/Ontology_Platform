"""Ontology registry CLI argument and safe artifact writing checks."""
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import ontology_cli

passed = 0


def mark() -> None:
    global passed
    passed += 1


parser = ontology_cli.build_parser()
args = parser.parse_args(["--base-url", "http://local", "list", "--project", "ops", "--channel", "production"])
with patch("ontology_cli._call", return_value={"count": 1, "entries": [{"version": "1.0.0"}]}) as call:
    result = ontology_cli.execute(args)
    assert result["count"] == 1
    assert call.call_args.args[1] == "/ontology/registry?project_id=ops&channel=production"
mark()

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    output = Path(folder) / "contract.json"
    args = parser.parse_args(["--base-url", "http://local", "schema", "--entry", "registry-1", "--output", str(output)])
    with patch("ontology_cli._call", return_value={"registry_id": "registry-1", "checksum": "abc", "schema": {"type": "object"}}):
        result = ontology_cli.execute(args)
    assert json.loads(output.read_text(encoding="utf-8")) == {"type": "object"}
    assert result["output"] == str(output.resolve())
mark()

with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
    output_dir = Path(folder) / "generated"
    args = parser.parse_args(["sdk", "--entry", "registry-1", "--language", "python", "--output-dir", str(output_dir)])
    with patch("ontology_cli._call", return_value={"registry_id": "registry-1", "checksum": "abc", "files": {"ontology_client.py": "class Client:\n    pass\n"}}):
        result = ontology_cli.execute(args)
    assert (output_dir / "ontology_client.py").exists() and len(result["files"]) == 1
mark()

try:
    ontology_cli._write_sdk_files(Path("unused"), {"../escape.py": ""})
    raise AssertionError("Unsafe generated file name was accepted")
except RuntimeError:
    mark()

print(f"Ontology registry CLI verified: {passed} assertions passed.")
