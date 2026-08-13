"""Dependency-free CLI for published ontology registry contracts.

Examples:
  python oms/ontology_cli.py list --project default
  python oms/ontology_cli.py schema --entry ontology_registry_... --output ontology.schema.json
  python oms/ontology_cli.py sdk --entry ontology_registry_... --language typescript --output-dir generated
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict
from urllib import error, parse, request


def _call(base_url: str, path: str, token: str | None = None, payload: Dict[str, Any] | None = None) -> Dict[str, Any]:
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Accept": "application/json"}
    if body is not None:
        headers["Content-Type"] = "application/json"
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = request.Request(base_url.rstrip("/") + path, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with request.urlopen(req, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Ontology API returned {exc.code}: {detail}") from exc
    except error.URLError as exc:
        raise RuntimeError(f"Cannot connect to Ontology Platform at {base_url}: {exc.reason}") from exc


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(content)
        temporary = Path(handle.name)
    temporary.replace(path)


def _safe_file_name(value: str) -> str:
    name = Path(value).name
    if not name or name != value or not re.match(r"^[A-Za-z0-9_.-]+$", name):
        raise RuntimeError(f"Registry returned an unsafe generated file name: {value!r}")
    return name


def _write_sdk_files(output_dir: Path, files: Dict[str, str]) -> list[str]:
    written = []
    for name, content in files.items():
        target = output_dir / _safe_file_name(name)
        _atomic_write(target, content)
        written.append(str(target.resolve()))
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Consume governed Ontology Platform registry contracts.")
    parser.add_argument("--base-url", default=os.getenv("ONTOLOGY_BASE_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--token", default=os.getenv("ONTOLOGY_TOKEN"))
    commands = parser.add_subparsers(dest="command", required=True)

    list_parser = commands.add_parser("list", help="List published registry entries")
    list_parser.add_argument("--project", default="default")
    list_parser.add_argument("--channel")

    publish = commands.add_parser("publish", help="Publish an approved ontology revision")
    publish.add_argument("--project", default="default")
    publish.add_argument("--revision", required=True)
    publish.add_argument("--version", required=True)
    publish.add_argument("--channel", default="production")
    publish.add_argument("--allow-breaking", action="store_true")

    schema = commands.add_parser("schema", help="Export JSON Schema for a registry entry")
    schema.add_argument("--entry", required=True)
    schema.add_argument("--output", required=True, type=Path)

    sdk = commands.add_parser("sdk", help="Generate a typed client from a registry entry")
    sdk.add_argument("--entry", required=True)
    sdk.add_argument("--language", required=True, choices=["typescript", "python"])
    sdk.add_argument("--output-dir", required=True, type=Path)
    return parser


def execute(args: argparse.Namespace) -> Dict[str, Any]:
    if args.command == "list":
        query = {"project_id": args.project}
        if args.channel:
            query["channel"] = args.channel
        return _call(args.base_url, "/ontology/registry?" + parse.urlencode(query), args.token)
    if args.command == "publish":
        return _call(args.base_url, "/ontology/registry/publish", args.token, {
            "project_id": args.project, "revision_id": args.revision, "version": args.version,
            "channel": args.channel, "allow_breaking": args.allow_breaking,
        })
    if args.command == "schema":
        result = _call(args.base_url, f"/ontology/registry/{parse.quote(args.entry, safe='')}/schema", args.token)
        _atomic_write(args.output, json.dumps(result["schema"], indent=2, sort_keys=True) + "\n")
        return {"registry_id": result["registry_id"], "checksum": result["checksum"], "output": str(args.output.resolve())}
    if args.command == "sdk":
        result = _call(args.base_url, f"/ontology/registry/{parse.quote(args.entry, safe='')}/sdk/{args.language}", args.token)
        written = _write_sdk_files(args.output_dir, result["files"])
        return {"registry_id": result["registry_id"], "checksum": result["checksum"], "language": args.language, "files": written}
    raise RuntimeError(f"Unsupported command: {args.command}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        print(json.dumps(execute(args), indent=2, sort_keys=True))
        return 0
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
