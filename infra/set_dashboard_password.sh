#!/usr/bin/env bash
# Set the dashboard password. It is typed twice (hidden), sent over SSH on stdin, hashed with scrypt on the server,
# and only the hash is stored in /opt/t2/.env. Signs everyone out (new session key) and restarts the dashboard.
# Usage: infra/set_dashboard_password.sh [host]
set -euo pipefail
host="${1:-ubuntu@13.206.50.110}"
key="${T2_SSH_KEY:-$HOME/.ssh/t2_lightsail}"
read -rsp "New dashboard password (12+ characters): " pw; echo
read -rsp "Repeat: " pw2; echo
[ "$pw" = "$pw2" ] || { echo "Passwords differ."; exit 1; }
[ "${#pw}" -ge 12 ] || { echo "Use at least 12 characters."; exit 1; }
printf '%s' "$pw" | ssh -i "$key" "$host" '
  set -e; cd /opt/t2/app; f=/opt/t2/.env
  h=$(/usr/local/bin/uv run --frozen python -c "import sys; from t2.dashboard.auth import hash_password; print(hash_password(sys.stdin.read()))")
  grep -v -e "^DASHBOARD_PASSWORD_HASH=" -e "^DASHBOARD_SESSION_KEY=" $f > $f.tmp || true
  printf "DASHBOARD_PASSWORD_HASH=%s\nDASHBOARD_SESSION_KEY=%s\n" "$h" "$(openssl rand -hex 32)" >> $f.tmp
  mv $f.tmp $f; chmod 600 $f
  sudo systemctl restart t2-dashboard.service'
echo "Dashboard password set on ${host}."
