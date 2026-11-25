#!/usr/bin/env bash
# One-time setup for the live server (Ubuntu 24.04). Safe to re-run.
# Usage (from your machine): ssh -i ~/.ssh/t2_lightsail ubuntu@<ip> 'sudo bash -s' < infra/bootstrap.sh
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Exchange time matters: IST + accurate clock (Breeze rejects requests >60s off).
timedatectl set-timezone Asia/Kolkata
apt-get update -q
apt-get -yq upgrade
apt-get -yq install chrony ufw fail2ban unattended-upgrades ca-certificates curl git jq
systemctl enable --now chrony

# Automatic security updates, no surprise reboots during market hours.
cat > /etc/apt/apt.conf.d/52t2-unattended <<'CONF'
Unattended-Upgrade::Automatic-Reboot "true";
Unattended-Upgrade::Automatic-Reboot-Time "02:30";
CONF
dpkg-reconfigure -f noninteractive unattended-upgrades

# Host firewall: SSH only (dashboard will come through an outbound tunnel).
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable

# SSH: keys only.
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
systemctl reload ssh
systemctl enable --now fail2ban

# 2 GB swap so builds and model loads don't OOM on a 2 GB box.
if ! swapon --show | grep -q /swapfile; then
  fallocate -l 2G /swapfile && chmod 600 /swapfile && mkswap /swapfile && swapon /swapfile
  echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

# Docker (official repo).
if ! command -v docker >/dev/null; then
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" \
    > /etc/apt/sources.list.d/docker.list
  apt-get update -q
  apt-get -yq install docker-ce docker-ce-cli containerd.io docker-compose-plugin
fi
usermod -aG docker ubuntu

# uv for running Python tools directly on the host.
if ! command -v uv >/dev/null; then
  curl -LsSf https://astral.sh/uv/install.sh | env UV_INSTALL_DIR=/usr/local/bin sh
fi

# App directory + secrets file readable only by ubuntu.
install -d -o ubuntu -g ubuntu -m 700 /opt/t2
touch /opt/t2/.env && chown ubuntu:ubuntu /opt/t2/.env && chmod 600 /opt/t2/.env

echo "bootstrap complete: $(date -Is)"
