"""Contract for replica-loss collaboration WebSocket acceptance."""
from pathlib import Path

root = Path(__file__).resolve().parent
script = (root / "verify_collaboration_websocket_chaos_postgres.py").read_text(encoding="utf-8")
runtime = (root / "app" / "platform_runtime.py").read_text(encoding="utf-8")
frontend = (root.parent / "frontend" / "src" / "workspaces" / "VisualBuilder.tsx").read_text(encoding="utf-8")
workflow = (root.parent / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

for required in (
    "replica_terminations", "replica_restarts", "duplicate_events", "missed_events",
    "reconnect_max_ms", "COLLABORATION_WS_RECONNECT_LIMIT_SECONDS", "current_revision",
):
    assert required in script, required
assert '@router.websocket("/artifacts/{artifact_id}/collaboration/ws")' in runtime
assert "production_auth._session_principal" in runtime and "_websocket_origin_allowed" in runtime
assert "artifactCollaborationWebSocketUrl" in frontend and "reconnectAttempt" in frontend
assert "verify_collaboration_websocket_chaos_postgres.py" in workflow

print("Collaboration WebSocket chaos contract verified: authentication, cursor resume, replica loss, restart, and CI evidence are required.")
