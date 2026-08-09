"""Read-only operational status for long-running pilot evidence collection."""
from __future__ import annotations

import os
import time
from pathlib import Path

from fastapi import APIRouter, Depends

from .pilot_evidence import (
    JournalIntegrityError, current_migration_head, latest_run, load_journal,
    validate_tail_anchor,
)
from .production_auth import Principal, require_permission

router = APIRouter(tags=["pilot_observability"])


def evidence_root() -> Path:
    return Path(os.getenv("PILOT_EVIDENCE_ROOT", "/var/lib/ontology/pilot-evidence"))


def availability_status(root: Path | None = None) -> dict:
    from availability_probe import WINDOW_SECONDS, summarize

    resolved_root = root or evidence_root()
    journal = resolved_root / "availability-samples.jsonl"
    state_path = resolved_root / "availability-probe-state.json"
    try:
        if not journal.exists() and not state_path.exists():
            records = []
        else:
            all_records = load_journal(journal)
            validate_tail_anchor(all_records, state_path)
            records = latest_run(all_records, migration_head=current_migration_head())
        summary = summarize(records, now=int(time.time()))
        integrity = "PASS"
        warning = None
    except JournalIntegrityError as exc:
        records, summary, integrity = [], summarize([], now=int(time.time())), "FAIL"
        warning = str(exc)
    remaining = max(0, WINDOW_SECONDS - int(summary.get("observed_seconds") or 0))
    return {
        "status": "INVALID" if integrity == "FAIL" else ("COMPLETE" if remaining == 0 else "COLLECTING"),
        "integrity": integrity,
        "journal": journal.name,
        "run_id": records[-1]["run_id"] if records else None,
        "migration_head": records[-1]["migration_head"] if records else None,
        "measurements": summary,
        "remaining_seconds": remaining,
        "warning": warning,
        "last_updated": int(time.time()),
    }


def rpo_status(root: Path | None = None) -> dict:
    from rpo_sampler import (
        REQUIRED_PRE_BACKUP_SAMPLES, REQUIRED_SAMPLES, RPO_LIMIT_SECONDS, summarize,
    )

    journal = (root or evidence_root()) / "rpo-samples.jsonl"
    try:
        records = latest_run(load_journal(journal), migration_head=current_migration_head())
        summary = summarize([dict(record.get("payload") or {}) for record in records])
        integrity, warning = "PASS", None
    except JournalIntegrityError as exc:
        records, summary, integrity, warning = [], summarize([]), "FAIL", str(exc)
        summary["integrity_failures"] = 1
    breached = bool(
        summary["total_loss_samples"]
        or summary["max_rpo_seconds"] > RPO_LIMIT_SECONDS
    )
    complete = bool(
        summary["samples"] >= REQUIRED_SAMPLES
        and summary["pre_backup_samples"] >= REQUIRED_PRE_BACKUP_SAMPLES
        and not breached
    )
    return {
        "status": "INVALID" if integrity == "FAIL" else (
            "BREACHED" if breached else ("COMPLETE" if complete else "COLLECTING")
        ),
        "integrity": integrity,
        "journal": journal.name,
        "run_id": records[-1]["run_id"] if records else None,
        "migration_head": records[-1]["migration_head"] if records else None,
        "measurements": summary,
        "remaining_samples": max(0, REQUIRED_SAMPLES - summary["samples"]),
        "remaining_pre_backup_samples": max(
            0, REQUIRED_PRE_BACKUP_SAMPLES - summary["pre_backup_samples"],
        ),
        "warning": warning,
        "last_updated": int(time.time()),
    }


def rto_status(root: Path | None = None) -> dict:
    from rto_rehearsal import (
        REQUIRED_REHEARSALS, REQUIRED_UNATTENDED, RTO_LIMIT_SECONDS, summarize,
    )

    journal = (root or evidence_root()) / "rto-rehearsals.jsonl"
    try:
        records = load_journal(journal)
        current = [
            record for record in records
            if record.get("migration_head") == current_migration_head()
        ]
        summary = summarize([dict(record.get("payload") or {}) for record in current])
        integrity, warning = "PASS", None
    except JournalIntegrityError as exc:
        current, summary, integrity, warning = [], summarize([]), "FAIL", str(exc)
        summary["integrity_failures"] = 1
    breached = bool(
        summary["failed_recoveries"]
        or summary["max_elapsed_seconds"] > RTO_LIMIT_SECONDS
    )
    complete = bool(
        summary["rehearsals"] >= REQUIRED_REHEARSALS
        and summary["unattended_rehearsals"] >= REQUIRED_UNATTENDED
        and not breached
    )
    return {
        "status": "INVALID" if integrity == "FAIL" else (
            "BREACHED" if breached else ("COMPLETE" if complete else "COLLECTING")
        ),
        "integrity": integrity,
        "journal": journal.name,
        "migration_head": current[-1]["migration_head"] if current else None,
        "measurements": summary,
        "remaining_rehearsals": max(0, REQUIRED_REHEARSALS - summary["rehearsals"]),
        "remaining_unattended": max(
            0, REQUIRED_UNATTENDED - summary["unattended_rehearsals"],
        ),
        "warning": warning,
        "last_updated": int(time.time()),
    }


@router.get("/runtime/pilot-evidence/availability")
def get_availability_status(principal: Principal = Depends(require_permission("view"))):
    del principal
    return availability_status()


@router.get("/runtime/pilot-evidence")
def get_pilot_evidence_status(principal: Principal = Depends(require_permission("view"))):
    del principal
    return {
        "availability": availability_status(),
        "rpo": rpo_status(),
        "rto": rto_status(),
        "last_updated": int(time.time()),
    }


@router.get("/ui-state/pilot-evidence")
def pilot_evidence_ui_state(principal: Principal = Depends(require_permission("view"))):
    del principal
    availability = availability_status()
    rpo = rpo_status()
    rto = rto_status()
    warnings = [
        item["warning"] for item in (availability, rpo, rto) if item.get("warning")
    ]
    return {
        "summary": {"availability": availability, "rpo": rpo, "rto": rto},
        "primary_actions": [{"id": "refresh", "label": "Refresh evidence"}],
        "sections": [
            {"id": "availability", "title": "Pilot availability", "data": availability},
            {"id": "rpo", "title": "Recovery point", "data": rpo},
            {"id": "rto", "title": "Recovery time", "data": rto},
        ],
        "evidence_links": [{"label": "Measurement contract", "href": "/workspace/validation"}],
        "warnings": warnings,
        "permissions": ["view"],
        "last_updated": availability["last_updated"],
    }
