#!/usr/bin/env bash
# Install/refresh the news crawler timers on the live server.
# Usage: ssh -i ~/.ssh/t2_lightsail ubuntu@<ip> 'bash -s' < infra/deploy_news.sh
set -euo pipefail
cd /opt/t2/app && git pull -q && /usr/local/bin/uv sync -q --frozen
install -d -m 700 /opt/t2/data
sudo cp infra/systemd/t2-news-*.service infra/systemd/t2-news-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now t2-news-poll.timer t2-news-export.timer
systemctl list-timers 't2-news-*' --no-pager
