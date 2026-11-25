#!/usr/bin/env bash
# Install/refresh every t2 systemd service + timer on the live server from main.
# Usage: ssh -i ~/.ssh/t2_lightsail ubuntu@<ip> 'bash -s' < infra/deploy_services.sh
set -euo pipefail
cd /opt/t2/app && git checkout -q main && git pull -q && /usr/local/bin/uv sync -q --frozen
install -d -m 700 /opt/t2/data
sudo cp infra/systemd/t2-*.service infra/systemd/t2-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
for t in infra/systemd/t2-*.timer; do sudo systemctl enable --now "$(basename "$t")"; done
systemctl list-timers 't2-*' --no-pager
