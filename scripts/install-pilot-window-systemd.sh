#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Install the OntologyOS seven-day pilot supervisor as a systemd service.

Usage:
  sudo ./scripts/install-pilot-window-systemd.sh \
    --evidence-root /var/lib/ontology/pilot-evidence \
    --token-file /etc/ontology/pilot-recovery-token \
    --environment-file /etc/ontology/pilot-runtime.env \
    --user ontology

The pilot window must already have passed preflight and been opened with
pilot_window.py start. The token is read at runtime and never copied into the
unit or process command line.
EOF
}

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_PATH="${PYTHON_PATH:-$(command -v python3 || true)}"
EVIDENCE_ROOT=""
TOKEN_FILE=""
ENVIRONMENT_FILE=""
SERVICE_USER="ontology"
UNIT_NAME="ontology-pilot-window"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --evidence-root) EVIDENCE_ROOT="$2"; shift 2 ;;
    --token-file) TOKEN_FILE="$2"; shift 2 ;;
    --environment-file) ENVIRONMENT_FILE="$2"; shift 2 ;;
    --user) SERVICE_USER="$2"; shift 2 ;;
    --python) PYTHON_PATH="$2"; shift 2 ;;
    --unit-name) UNIT_NAME="$2"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) echo "Unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

[[ "$(id -u)" -eq 0 ]] || { echo "Run as root so the unit and ACL checks are authoritative." >&2; exit 1; }
[[ -n "$PYTHON_PATH" && -x "$PYTHON_PATH" ]] || { echo "Python executable not found: $PYTHON_PATH" >&2; exit 1; }
[[ "$EVIDENCE_ROOT" = /* && -d "$EVIDENCE_ROOT" ]] || { echo "Evidence root must be an existing absolute directory." >&2; exit 1; }
[[ "$TOKEN_FILE" = /* && -f "$TOKEN_FILE" ]] || { echo "Token file must be an existing absolute file." >&2; exit 1; }
[[ "$ENVIRONMENT_FILE" = /* && -f "$ENVIRONMENT_FILE" ]] || { echo "Environment file must be an existing absolute file." >&2; exit 1; }
[[ -f "$EVIDENCE_ROOT/pilot-window.json" ]] || { echo "Open the pilot window before installing the supervisor." >&2; exit 1; }
id "$SERVICE_USER" >/dev/null 2>&1 || { echo "Service user does not exist: $SERVICE_USER" >&2; exit 1; }

observer_state="$EVIDENCE_ROOT/availability-probe-state.json"
[[ -f "$observer_state" ]] || { echo "The availability observer has not written its state file." >&2; exit 1; }
observer_age=$(( $(date +%s) - $(stat -c '%Y' "$observer_state") ))
(( observer_age <= 90 )) || { echo "The availability observer state is stale (${observer_age}s old)." >&2; exit 1; }

token="$(tr -d '\r\n' < "$TOKEN_FILE")"
[[ ${#token} -ge 32 ]] || { echo "Token file must contain at least 32 characters." >&2; exit 1; }
unset token

# Group/other permission bits must all be zero. The service account may own the
# file directly or receive access through an administrator-controlled ACL.
token_mode="$(stat -c '%a' "$TOKEN_FILE")"
(( (8#$token_mode & 077) == 0 )) || { echo "Token file mode must deny group and other access (for example 0600)." >&2; exit 1; }
environment_mode="$(stat -c '%a' "$ENVIRONMENT_FILE")"
(( (8#$environment_mode & 077) == 0 )) || { echo "Environment file mode must deny group and other access (for example 0600)." >&2; exit 1; }
runuser -u "$SERVICE_USER" -- test -r "$TOKEN_FILE" || {
  echo "Service user $SERVICE_USER cannot read the protected token file." >&2
  exit 1
}
if grep -Eq '^[[:space:]]*PILOT_(SOURCE_COMPOSE_FILES|RECOVERY_COMPOSE_FILE)=' "$ENVIRONMENT_FILE"; then
  command -v docker >/dev/null 2>&1 || { echo "Docker is required by the configured recovery driver." >&2; exit 1; }
  runuser -u "$SERVICE_USER" -- docker info >/dev/null 2>&1 || {
    echo "Service user $SERVICE_USER cannot access the Docker recovery runtime." >&2
    exit 1
  }
fi

"$PYTHON_PATH" "$REPO_ROOT/oms/pilot_window.py" \
  --evidence-root "$EVIDENCE_ROOT" \
  --environment-file "$ENVIRONMENT_FILE" \
  --token-file "$TOKEN_FILE" \
  verify-runtime

escape_unit_value() {
  printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g; s/%/%%/g'
}

unit_path="/etc/systemd/system/${UNIT_NAME}.service"
tmp_unit="$(mktemp)"
trap 'rm -f "$tmp_unit"' EXIT

cat > "$tmp_unit" <<EOF
[Unit]
Description=OntologyOS seven-day availability, RPO, and RTO pilot supervisor
After=network-online.target docker.service
Wants=network-online.target docker.service
ConditionPathExists="$(escape_unit_value "$EVIDENCE_ROOT/pilot-window.json")"

[Service]
Type=simple
User=$(escape_unit_value "$SERVICE_USER")
WorkingDirectory="$(escape_unit_value "$REPO_ROOT")"
Environment=PYTHONUNBUFFERED=1
EnvironmentFile="$(escape_unit_value "$ENVIRONMENT_FILE")"
ExecStart="$(escape_unit_value "$PYTHON_PATH")" "$(escape_unit_value "$REPO_ROOT/oms/pilot_window.py")" --evidence-root "$(escape_unit_value "$EVIDENCE_ROOT")" --token-file "$(escape_unit_value "$TOKEN_FILE")" run
Restart=on-failure
RestartSec=180
TimeoutStopSec=45
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
EOF

install -o root -g root -m 0644 "$tmp_unit" "$unit_path"
systemctl daemon-reload
systemctl enable --now "${UNIT_NAME}.service"
systemctl --no-pager --full status "${UNIT_NAME}.service" || true
echo "Installed ${UNIT_NAME}.service. Follow it with: journalctl -fu ${UNIT_NAME}.service"
