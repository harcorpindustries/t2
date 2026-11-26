#!/usr/bin/env bash
# Daily Breeze login in one command (run in your own Terminal, before 09:20 IST on trading days).
#  1. opens ICICI's login page for the t2 API app in your browser
#  2. you log in there as usual; ICICI then sends the browser to https://127.0.0.1/?apisession=NNNN
#     (that page does not load: that is expected)
#  3. paste that address here; the session is saved on the server and checked
# The API key is read on the server; nothing is printed or stored on this Mac.
set -euo pipefail
host="${1:-ubuntu@13.206.50.110}"
key="${T2_SSH_KEY:-$HOME/.ssh/t2_lightsail}"

url=$(ssh -i "$key" "$host" 'python3 - <<PY
import urllib.parse
k = ""
for line in open("/opt/t2/.env"):
    if line.startswith("BREEZE_API_KEY="):
        k = line.split("=", 1)[1].strip()
print("https://api.icicidirect.com/apiuser/login?api_key=" + urllib.parse.quote_plus(k))
PY')
open "$url" 2>/dev/null || echo "Open this in your browser: (login page could not be opened automatically)"
echo "ICICI login page opened in your browser. Log in there."
echo "Afterwards the browser shows an address like https://127.0.0.1/?apisession=12345678 (the page itself won't load)."
read -rp "Paste that address (or just the number): " pasted
session=$(printf '%s' "$pasted" | grep -oE 'apisession=[A-Za-z0-9]+' | cut -d= -f2 || true)
[ -n "$session" ] || session=$(printf '%s' "$pasted" | tr -cd 'A-Za-z0-9')
[ -n "$session" ] || { echo "No session number found."; exit 1; }

printf '%s' "$session" | ssh -i "$key" "$host" '
  set -e; v=$(cat); f=/opt/t2/.env
  grep -v "^BREEZE_SESSION_TOKEN=" $f > $f.tmp || true
  printf "BREEZE_SESSION_TOKEN=%s\n" "$v" >> $f.tmp
  mv $f.tmp $f; chmod 600 $f
  cd /opt/t2/app
  out=$(/usr/local/bin/uv run --frozen python -m t2.brokers.breeze_check 2>&1 || true)
  if printf "%s" "$out" | grep -q "^session: ok"; then
    echo "Breeze session OK. Paper trading and data collection are set for today."
  else
    echo "Breeze rejected the session number: log in again and paste the new address (numbers are single-use)."
    exit 1
  fi'
