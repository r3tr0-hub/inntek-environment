#!/usr/bin/env bash
#
# LabelJetty installer — turn a ready-to-use Raspberry Pi (or any Debian-based Linux box)
# into a running LabelJetty in one shot. Idempotent: safe to re-run to update.
#
#   curl -fsSL https://raw.githubusercontent.com/motey/LabelJetty/main/deploy/install.sh | bash
#
# It will:
#   1. Install Docker + the compose plugin (if missing) and start it.
#   2. Add you to the `docker` and `plugdev` groups.
#   3. Detect the connected USB printer(s) and install a matching udev rule.
#   4. Write a docker-compose.yml under ~/labeljetty (override with LABELJETTY_DIR).
#   5. Pull the image and bring the stack up.
#   6. Print how to reach the UI and what to configure next.
#
# Printer selection: LabelJetty auto-detects a connected TSPL printer, so PRINTER_USB is
# left UNSET by default. Set it only to pin a specific device (e.g. when several printers
# are attached). See tunables below.
#
# Tunables (export before running, or prefix the curl|bash line):
#   LABELJETTY_DIR   install/compose directory      (default: $HOME/labeljetty)
#   PRINTER_USB      pin a specific printer         (default: unset → auto-detect)
#   LABEL_WIDTH_MM / LABEL_HEIGHT_MM / LABEL_DPI     (default: 57 / 32 / 203)
#
# "Any Debian-based system" is best-effort — tested target is Raspberry Pi OS (64-bit).
# Your mileage may vary elsewhere; the script tells you what it's doing so you can adapt.
set -euo pipefail

# ---- pretty logging (degrades gracefully when not a TTY) --------------------------------
if [ -t 1 ]; then B=$'\033[1m'; G=$'\033[32m'; Y=$'\033[33m'; R=$'\033[31m'; N=$'\033[0m'; else B= G= Y= R= N=; fi
info() { printf '%s==>%s %s\n' "$G$B" "$N" "$*"; }
warn() { printf '%s!! %s%s\n'  "$Y"   "$*" "$N"; }
die()  { printf '%sxx %s%s\n'  "$R"   "$*" "$N" >&2; exit 1; }

# ---- privilege + target user ------------------------------------------------------------
if [ "$(id -u)" -eq 0 ]; then SUDO=""; else
  command -v sudo >/dev/null 2>&1 || die "Need root or sudo to install packages."
  SUDO="sudo"
fi
# Resolve the *real* login user even when invoked via `sudo bash` / `curl | sudo bash`.
if [ -n "${SUDO_USER:-}" ] && [ "${SUDO_USER}" != "root" ]; then
  TARGET_USER="$SUDO_USER"
else
  TARGET_USER="$(id -un)"
fi
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
[ -n "$TARGET_HOME" ] || die "Could not determine home directory for '$TARGET_USER'."

# ---- config -----------------------------------------------------------------------------
LABELJETTY_DIR="${LABELJETTY_DIR:-$TARGET_HOME/labeljetty}"
PRINTER_USB="${PRINTER_USB:-}"            # empty → let LabelJetty auto-detect
LABEL_WIDTH_MM="${LABEL_WIDTH_MM:-57}"
LABEL_HEIGHT_MM="${LABEL_HEIGHT_MM:-32}"
LABEL_DPI="${LABEL_DPI:-203}"

info "LabelJetty installer"
echo "    user:      $TARGET_USER"
echo "    directory: $LABELJETTY_DIR"
echo "    printer:   ${PRINTER_USB:-<auto-detect>}"

# ---- 0. sanity checks -------------------------------------------------------------------
command -v apt-get >/dev/null 2>&1 || warn "Not a Debian/apt system — continuing best-effort (YMMV)."
case "$(uname -m)" in
  x86_64|aarch64|arm64) : ;;
  armv7l|armv6l) die "32-bit OS detected ($(uname -m)). LabelJetty's image is amd64/arm64 only — reflash a 64-bit OS." ;;
  *) warn "Unrecognised architecture $(uname -m); the image may not have a matching variant." ;;
esac

# ---- 1. Docker --------------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  info "Docker already installed ($(docker --version))."
else
  info "Installing Docker via get.docker.com ..."
  curl -fsSL https://get.docker.com | $SUDO sh
fi
$SUDO systemctl enable --now docker >/dev/null 2>&1 || true

if ! docker compose version >/dev/null 2>&1 && ! $SUDO docker compose version >/dev/null 2>&1; then
  warn "Docker Compose v2 plugin not found. Install 'docker-compose-plugin' and re-run."
fi

# ---- 2. group access --------------------------------------------------------------------
info "Adding '$TARGET_USER' to docker + plugdev groups (takes effect on next login)."
$SUDO usermod -aG docker,plugdev "$TARGET_USER" || warn "Could not modify groups for $TARGET_USER."

# ---- 3. detect printer(s) + install udev rule -------------------------------------------
# Find connected USB printers the same way LabelJetty's auto-discovery does: anything that
# advertises the USB printer interface class (07), plus the known TSPL vendor 2d37 (the
# reference Vretti/Poskey 420B), in case it doesn't expose class 07. Pure sysfs read.
declare -a PRINTERS=()
shopt -s nullglob
for iface in /sys/bus/usb/devices/*:*/bInterfaceClass; do
  [ -r "$iface" ] || continue
  [ "$(cat "$iface")" = "07" ] || continue
  devdir="$(dirname "$iface")"; devdir="${devdir%:*}"
  vid="$(cat "$devdir/idVendor" 2>/dev/null || true)"
  pid="$(cat "$devdir/idProduct" 2>/dev/null || true)"
  [ -n "$vid" ] && [ -n "$pid" ] && PRINTERS+=("$vid:$pid")
done
for devdir in /sys/bus/usb/devices/*; do
  [ -r "$devdir/idVendor" ] || continue
  [ "$(cat "$devdir/idVendor")" = "2d37" ] || continue
  pid="$(cat "$devdir/idProduct" 2>/dev/null || true)"
  [ -n "$pid" ] && PRINTERS+=("2d37:$pid")
done
shopt -u nullglob
# de-duplicate
if [ "${#PRINTERS[@]}" -gt 0 ]; then
  mapfile -t PRINTERS < <(printf '%s\n' "${PRINTERS[@]}" | sort -u)
fi

if [ "${#PRINTERS[@]}" -gt 0 ]; then
  info "Detected USB printer(s): ${PRINTERS[*]}"
  [ "${#PRINTERS[@]}" -gt 1 ] && warn "Several printers present — auto-detect won't guess. Pin one with PRINTER_USB=vid:..:pid:.."
else
  warn "No USB printer detected right now — writing a rule for the reference 420B (2d37:62de)."
  warn "Plug the printer in & power it on; if it isn't a 420B, edit /etc/udev/rules.d/99-tspl-printer.rules."
  PRINTERS=("2d37:62de")
fi

info "Installing udev rule for raw USB printer access."
{
  echo "# TSPL label printer(s) — allow the plugdev group raw USB access. Managed by deploy/install.sh."
  for vp in "${PRINTERS[@]}"; do
    echo "SUBSYSTEM==\"usb\", ATTRS{idVendor}==\"${vp%:*}\", ATTRS{idProduct}==\"${vp#*:}\", MODE=\"0660\", GROUP=\"plugdev\""
  done
} | $SUDO tee /etc/udev/rules.d/99-tspl-printer.rules >/dev/null
$SUDO udevadm control --reload-rules >/dev/null 2>&1 || true
$SUDO udevadm trigger >/dev/null 2>&1 || true

# ---- 4. compose project -----------------------------------------------------------------
info "Setting up compose project in $LABELJETTY_DIR"
mkdir -p "$LABELJETTY_DIR/data"
# Only emit a PRINTER_USB line when the user pinned one; otherwise leave it for auto-detect.
if [ -n "$PRINTER_USB" ]; then
  PRINTER_USB_LINE="      PRINTER_USB: ${PRINTER_USB}"
else
  PRINTER_USB_LINE="      # PRINTER_USB left unset: LabelJetty auto-detects the printer. Pin it (e.g.
      #   PRINTER_USB: vid:2d37:pid:62de) only if you have several printers attached."
fi
COMPOSE_FILE="$LABELJETTY_DIR/docker-compose.yml"
if [ -f "$COMPOSE_FILE" ]; then
  warn "Existing $COMPOSE_FILE kept (your settings are preserved). Delete it to regenerate."
  # Older installers wrote a static `devices:` mapping, which pins the USB node that
  # existed at 'up' time: replug the printer and the container can no longer see it.
  if grep -qE '^[[:space:]]*devices:' "$COMPOSE_FILE" \
     && ! grep -qE '^[[:space:]]*device_cgroup_rules:' "$COMPOSE_FILE"; then
    warn "  ^ that file still uses a 'devices:' USB mapping. Replugging the printer will make"
    warn "    it undetectable until the container is recreated. Replace:"
    warn "        devices:"
    warn "          - /dev/bus/usb:/dev/bus/usb"
    warn "    with:"
    warn "        device_cgroup_rules:"
    warn "          - \"c 189:* rmw\""
    warn "    and add '- /dev/bus/usb:/dev/bus/usb' under 'volumes:', then re-run"
    warn "    'docker compose up -d'. See docs/README.docker.md."
  fi
else
  cat > "$COMPOSE_FILE" <<EOF
# Generated by deploy/install.sh — edit freely, then re-run 'docker compose up -d' to apply.
services:
  labeljetty:
    image: motey/labeljetty:latest
    container_name: labeljetty
    restart: unless-stopped
    ports:
      - "8888:8888"
    # USB passthrough that survives unplug/replug. We do NOT use \`devices:\` here:
    # a static device mapping pins the node that existed at 'up' time, so a replugged
    # printer (new /dev/bus/usb/NNN/MMM node) stays invisible until the container is
    # recreated. The cgroup rule grants the whole USB major (189) and the bind mount
    # below keeps /dev/bus/usb live inside the container.
    device_cgroup_rules:
      - "c 189:* rmw"
    environment:
${PRINTER_USB_LINE}
      DEFAULT_LABEL_WIDTH_MM: "${LABEL_WIDTH_MM}"
      DEFAULT_LABEL_HEIGHT_MM: "${LABEL_HEIGHT_MM}"
      DEFAULT_DPI: "${LABEL_DPI}"
      # No auth by default. Turn on before exposing beyond a trusted LAN:
      # AUTH_MODE: protected
      # AUTH_TOKENS: '[{"name":"ci","token":"choose-a-long-random-secret"}]'
      # SESSION_SECRET: another-long-random-string
      # Optional Homebox integration:
      # HOMEBOX_URL: https://box.example.com
      # HOMEBOX_API_KEY: hb_xxxxxxxxxxxx
      # SETTINGS_UI_ENABLED: true
    volumes:
      - ./data:/data
      # Live view of the USB bus, paired with device_cgroup_rules above.
      - /dev/bus/usb:/dev/bus/usb
EOF
  info "Wrote $COMPOSE_FILE"
fi
# Make sure the project belongs to the login user (matters if we ran via sudo).
$SUDO chown -R "$TARGET_USER" "$LABELJETTY_DIR" 2>/dev/null || true

# ---- 5. bring it up ---------------------------------------------------------------------
# Group membership isn't active in this shell yet, so use sudo for docker this run only.
if docker info >/dev/null 2>&1; then DC="docker"; else DC="$SUDO docker"; fi
info "Pulling image and starting LabelJetty ..."
( cd "$LABELJETTY_DIR" && $DC compose pull && $DC compose up -d )

# ---- 6. report --------------------------------------------------------------------------
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
HOST="$(hostname)"
echo
info "LabelJetty is up. Open the web UI:"
[ -n "$IP" ] && echo "    http://${IP}:8888/"
echo "    http://${HOST}.local:8888/   (if mDNS/Avahi is available)"
echo
info "Recommended next steps:"
cat <<EOF
  • Print the alignment test to confirm hardware + geometry:
        cd "$LABELJETTY_DIR" && docker compose exec labeljetty labeljetty-testbench pattern
  • Match your label stock: edit DEFAULT_LABEL_WIDTH_MM / HEIGHT_MM / DPI in
        $COMPOSE_FILE
    then  (cd "$LABELJETTY_DIR" && docker compose up -d)   to apply.
  • Printer not found? Either it isn't plugged in/powered, or your image predates
    auto-detection — set PRINTER_USB in the compose file ('lsusb' to find vid:pid).
  • Exposing it beyond a trusted LAN? enable AUTH_MODE=protected (see the compose comments
    and docs: advanced-usage.md#authentication).
  • Homebox user? set HOMEBOX_URL + HOMEBOX_API_KEY to print inventory labels.
EOF
echo
warn "You were added to the 'docker' group — log out and back in (or 'newgrp docker') to run"
warn "docker without sudo. The service itself is already running and survives reboots."
