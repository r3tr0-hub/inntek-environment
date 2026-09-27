#!/usr/bin/env bash
# LabelJetty Raspberry Pi provisioner.
#
# Installs Docker, grants raw-USB access to the printer, and brings up the LabelJetty
# stack. Runs once on first boot via labeljetty-provision.service, then self-disables.
# Network onboarding (WiFi / setup-AP captive portal) is handled separately by Comitup —
# this script only assumes a network eventually comes up.
set -euo pipefail
exec >>/var/log/labeljetty-provision.log 2>&1
echo "=== labeljetty provision $(date -Is) ==="

APP_DIR=/opt/labeljetty
TARGET_USER="$(getent passwd 1000 | cut -d: -f1)"   # the first-boot-created login user

# 1. Wait for working DNS (Comitup may still be bringing WiFi up).
for i in $(seq 1 60); do
  getent hosts download.docker.com >/dev/null 2>&1 && break
  echo "waiting for network ($i)…"; sleep 5
done

# 2. Docker Engine + compose plugin (official convenience script; supports arm64 Bookworm).
if ! command -v docker >/dev/null 2>&1; then
  curl -fsSL https://get.docker.com | sh
fi
systemctl enable --now docker

# 3. Group access: docker socket + raw USB (plugdev).
[ -n "$TARGET_USER" ] && usermod -aG docker,plugdev "$TARGET_USER" || true

# 4. udev rule so the printer is openable over raw USB (matches docs/setup.md, step 4).
cat >/etc/udev/rules.d/99-tspl-printer.rules <<'EOF'
SUBSYSTEM=="usb", ATTRS{idVendor}=="2d37", ATTRS{idProduct}=="62de", MODE="0660", GROUP="plugdev"
EOF
udevadm control --reload-rules || true
udevadm trigger || true

# 5. Bring up LabelJetty.
docker compose -f "$APP_DIR/docker-compose.yml" up -d

# 6. One-shot: never run again.
systemctl disable labeljetty-provision.service || true
touch "$APP_DIR/.provisioned"
echo "=== done $(date -Is) ==="
