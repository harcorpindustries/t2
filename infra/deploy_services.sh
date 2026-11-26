#!/usr/bin/env bash
# Install/refresh every t2 systemd service + timer on the live server from main, and the latest dashboard build.
# Usage: ssh -i ~/.ssh/t2_lightsail ubuntu@<ip> 'bash -s' < infra/deploy_services.sh
set -euo pipefail
cd /opt/t2/app && git checkout -q main && git pull -q && /usr/local/bin/uv sync -q --frozen
install -d -m 700 /opt/t2/data

# Dashboard: static build published by the dashboard workflow as a release asset.
url=https://github.com/harcorpindustries/t2/releases/download/dashboard/dashboard.tar.gz
if curl -fsSL -o /tmp/dashboard.tar.gz "$url"; then
  rm -rf /opt/t2/dashboard.new && mkdir -p /opt/t2/dashboard.new
  tar -xzf /tmp/dashboard.tar.gz -C /opt/t2/dashboard.new
  rm -rf /opt/t2/dashboard && mv /opt/t2/dashboard.new /opt/t2/dashboard
fi
# Kill-switch token for the dashboard: generated once, never printed (read it on the server or set your own
# with infra/set_server_secret.sh DASHBOARD_TOKEN).
grep -q '^DASHBOARD_TOKEN=' /opt/t2/.env || echo "DASHBOARD_TOKEN=$(openssl rand -hex 24)" >> /opt/t2/.env

sudo cp infra/systemd/t2-*.service infra/systemd/t2-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
for t in infra/systemd/t2-*.timer; do sudo systemctl enable --now "$(basename "$t")"; done
sudo systemctl enable t2-dashboard.service && sudo systemctl restart t2-dashboard.service
systemctl list-timers 't2-*' --no-pager
systemctl is-active t2-dashboard.service
