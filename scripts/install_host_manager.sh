#!/usr/bin/env bash
# Root bootstrap for the v4.4.11 Host Manager. This script never accepts a
# root password and does not disable root SSH until explicitly requested.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
MANAGEMENT_USER=""
DISABLE_ROOT_SSH="no"
RECOVERY_CHANNEL=""
VERIFICATION_EVIDENCE=""
UID_MIN=200000
UID_MAX=299999

while [[ $# -gt 0 ]]; do
  case "$1" in
    --management-user) MANAGEMENT_USER="${2:-}"; shift 2 ;;
    --uid-min) UID_MIN="${2:-}"; shift 2 ;;
    --uid-max) UID_MAX="${2:-}"; shift 2 ;;
    --disable-root-ssh) DISABLE_ROOT_SSH="yes"; shift ;;
    --recovery-channel) RECOVERY_CHANNEL="${2:-}"; shift 2 ;;
    --verification-evidence) VERIFICATION_EVIDENCE="${2:-}"; shift 2 ;;
    *) echo "Unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [[ "$(id -u)" -ne 0 ]]; then
  echo "[ERROR] Initial Host Manager bootstrap must run as root." >&2
  exit 1
fi
if [[ ! "$MANAGEMENT_USER" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]] || ! id "$MANAGEMENT_USER" >/dev/null 2>&1; then
  echo "[ERROR] --management-user must name an existing local account." >&2
  exit 1
fi
if (( UID_MIN < 100000 || UID_MAX <= UID_MIN || UID_MAX - UID_MIN < 999 )); then
  echo "[ERROR] Reserve at least 1000 UID/GID values above 100000." >&2
  exit 1
fi

source "$SCRIPT_DIR/python_runtime.sh"
PYTHON_BIN="$(cx_resolve_python "${PYTHON_BIN:-}")"
cx_prepare_python_environment "$PYTHON_BIN"

groupadd --system --force chuanxu-admin
usermod -a -G chuanxu-admin "$MANAGEMENT_USER"
install -d -o root -g chuanxu-admin -m 0750 /run/chuanxu
install -d -o root -g root -m 0700 /var/lib/chuanxu-runtime
install -d -o root -g root -m 0755 /usr/local/lib/chuanxu-host-manager
rm -rf /usr/local/lib/chuanxu-host-manager/lib
cp -a "$ROOT_DIR/lib" /usr/local/lib/chuanxu-host-manager/lib
install -o root -g root -m 0755 "$SCRIPT_DIR/host_manager_service.py" /usr/local/lib/chuanxu-host-manager/host_manager_service.py
install -o root -g root -m 0755 "$SCRIPT_DIR/host_manager_client.py" /usr/local/bin/chuanxu-host-manager
chown -R root:root /usr/local/lib/chuanxu-host-manager
chmod -R go-w /usr/local/lib/chuanxu-host-manager

SERVICE_FILE=/etc/systemd/system/chuanxu-host-manager.service
TMP_SERVICE="$(mktemp /tmp/chuanxu-host-manager.XXXXXX)"
trap 'rm -f "$TMP_SERVICE"' EXIT
sed \
  -e "s|@PYTHON_BIN@|$PYTHON_BIN|g" \
  -e "s|@SERVICE_SCRIPT@|/usr/local/lib/chuanxu-host-manager/host_manager_service.py|g" \
  -e "s|@UID_MIN@|$UID_MIN|g" \
  -e "s|@UID_MAX@|$UID_MAX|g" \
  "$SCRIPT_DIR/systemd/chuanxu-host-manager.service.in" > "$TMP_SERVICE"
install -o root -g root -m 0644 "$TMP_SERVICE" "$SERVICE_FILE"
systemctl daemon-reload
systemctl enable --now chuanxu-host-manager.service
for _attempt in {1..30}; do
  [[ -S /run/chuanxu/host-manager.sock ]] && break
  sleep 0.2
done
if [[ ! -S /run/chuanxu/host-manager.sock ]]; then
  echo "[ERROR] Host Manager socket did not become ready." >&2
  exit 1
fi

PREFLIGHT_REQUEST='{"protocol":"chuanxu-host-manager/v1","action":"preflight","request_id":"bootstrap-preflight","idempotency_key":"bootstrap-preflight-v1"}'
PREFLIGHT_RESULT="$(printf '%s\n' "$PREFLIGHT_REQUEST" | /usr/local/bin/chuanxu-host-manager)"
printf '%s\n' "$PREFLIGHT_RESULT"
if ! "$PYTHON_BIN" -c 'import json,sys; raise SystemExit(0 if json.load(sys.stdin).get("result",{}).get("passed") is True else 1)' <<<"$PREFLIGHT_RESULT"; then
  echo "[ERROR] Host preflight failed; root SSH settings were not changed." >&2
  exit 1
fi
if ! runuser -u "$MANAGEMENT_USER" -- /usr/local/bin/chuanxu-host-manager <<<"$PREFLIGHT_REQUEST" >/dev/null; then
  echo "[ERROR] Management user cannot call the Host Manager socket." >&2
  exit 1
fi

if [[ "$DISABLE_ROOT_SSH" == "yes" ]]; then
  if [[ -z "$RECOVERY_CHANNEL" ]]; then
    echo "[ERROR] --recovery-channel is required before disabling root SSH." >&2
    exit 1
  fi
  if [[ -z "$VERIFICATION_EVIDENCE" || ! -f "$VERIFICATION_EVIDENCE" ]]; then
    echo "[ERROR] --verification-evidence is required before disabling root SSH." >&2
    exit 1
  fi
  if ! "$PYTHON_BIN" -c 'import json,sys; p=json.load(open(sys.argv[1],encoding="ascii")); raise SystemExit(0 if p.get("passed") is True and p.get("lifecycle_passed") is True else 1)' "$VERIFICATION_EVIDENCE"; then
    echo "[ERROR] Verification evidence must prove preflight and provision/start/stop/revoke lifecycle." >&2
    exit 1
  fi
  install -d -o root -g root -m 0755 /etc/ssh/sshd_config.d
  # OpenSSH uses the first value it encounters. Neutralize earlier active
  # PermitRootLogin directives so a pre-existing drop-in cannot override the
  # handoff policy written below.
  while IFS= read -r config_file; do
    [[ "$config_file" == /etc/ssh/sshd_config.d/90-chuanxu-no-root.conf ]] && continue
    sed -i -E 's/^([[:space:]]*)PermitRootLogin([[:space:]]+).*/\1# PermitRootLogin disabled-by-chuanxu/' "$config_file"
  done < <(grep -rl -E '^[[:space:]]*PermitRootLogin[[:space:]]+' /etc/ssh/sshd_config /etc/ssh/sshd_config.d 2>/dev/null || true)
  printf 'PermitRootLogin no\n' > /etc/ssh/sshd_config.d/90-chuanxu-no-root.conf
  chmod 0600 /etc/ssh/sshd_config.d/90-chuanxu-no-root.conf
  sshd -t
  systemctl reload sshd
  install -d -o root -g chuanxu-admin -m 0750 /var/lib/chuanxu-runtime/evidence
  printf '%s\n' "$RECOVERY_CHANNEL" > /var/lib/chuanxu-runtime/evidence/recovery-channel
  install -o root -g chuanxu-admin -m 0640 "$VERIFICATION_EVIDENCE" /var/lib/chuanxu-runtime/evidence/host-verification.json
  printf '{"root_remote_login":"DISABLED"}\n' > /var/lib/chuanxu-runtime/evidence/root-ssh-state.json
  chmod 0640 /var/lib/chuanxu-runtime/evidence/recovery-channel
  chown root:chuanxu-admin /var/lib/chuanxu-runtime/evidence/recovery-channel /var/lib/chuanxu-runtime/evidence/root-ssh-state.json
  chmod 0640 /var/lib/chuanxu-runtime/evidence/root-ssh-state.json
fi

echo "[PASS] Host Manager bootstrap completed for management user $MANAGEMENT_USER."
