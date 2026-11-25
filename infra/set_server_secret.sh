#!/usr/bin/env bash
# Store a secret in the live server's /opt/t2/.env without it touching disk locally or shell history.
# Usage: infra/set_server_secret.sh NAME [host]
set -euo pipefail
name="${1:?usage: set_server_secret.sh NAME [host]}"
host="${2:-ubuntu@13.206.50.110}"
key="${T2_SSH_KEY:-$HOME/.ssh/t2_lightsail}"
read -rsp "Value for ${name}: " value; echo
printf '%s' "$value" | ssh -i "$key" "$host" "
  set -e; v=\$(cat); f=/opt/t2/.env
  grep -v '^${name}=' \$f > \$f.tmp || true
  printf '%s=%s\n' '${name}' \"\$v\" >> \$f.tmp
  mv \$f.tmp \$f; chmod 600 \$f"
echo "${name} saved on ${host}"
