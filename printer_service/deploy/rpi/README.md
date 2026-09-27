# LabelJetty on Raspberry Pi — headless appliance (PARKED idea)

> 🅿️ **PARKED — maybe later, but it's hard.** A fully prebaked, flash-and-go image (custom
> WiFi onboarding via captive portal + a CI-built `.img`) turned out to be more friction and
> ongoing maintenance than it's worth right now: headless WiFi onboarding without the Imager
> GUI was fiddly, and a custom image means owning an OS distribution (base-OS security
> rebuilds, a slow CI image pipeline, a niche Comitup dependency). The notes and starter
> artifacts below are kept as a **starting point if we ever revisit it** — they are not a
> supported path today.
>
> **Use this instead:** install onto a normal, already-networked Raspberry Pi (or any Debian
> box) with the one-line installer — see [`deploy/install.sh`](../install.sh) and the Setup
> guide. Docker on a Linux host remains the recommended, first-class deployment.

---

_Everything below is the parked design, retained for reference._

Goal: a Raspberry Pi that you flash, power on, and onboard onto WiFi **without an HDMI
cable and without the Raspberry Pi Imager GUI**. If no WiFi is known, the Pi raises its
own setup hotspot with a captive portal to enter the real network; then it runs LabelJetty
in Docker and prints.

This is built in phases so nothing is wasted — each phase is the verified content of the
next:

| Phase | What | Status |
| --- | --- | --- |
| **0** | Boot a stock Raspberry Pi OS Lite (64-bit) headless via a hand-written `custom.toml` (bypasses the Imager GUI). | recipe here |
| **1** | On that Pi: install [Comitup](http://davesteele.github.io/comitup/) (WiFi AP + captive portal), Docker, and the LabelJetty stack. Prove the full UX on hardware. | recipe here |
| **2** | Bake Phase 1 into a flashable image built in GitHub CI with [CustomPiOS](https://github.com/guysoft/CustomPiOS). | TODO (after Phase 1 verified) |
| **3** | `docs/raspberry-pi-headless.md`. | TODO |

## Why this combination

- **`custom.toml`** is the official, file-based headless first-boot config — same result as
  the Imager "customisation" screen, but you just drop a text file on the FAT boot
  partition. No GUI.
- **Comitup** is the WiFi onboarding: known network → connect as client; no known network →
  raise an AP + portal. This is *complementary* to `custom.toml`, not a replacement — a
  preconfigured network in `custom.toml` is just a "known network" Comitup will use.
- **64-bit OS is mandatory** — `motey/labeljetty:latest` only has an `arm64` variant for the
  Pi 3 B+, not `armhf`.

## Files

| File | Phase | Where it goes |
| --- | --- | --- |
| `boot/custom.toml.example` | 0 | FAT boot partition as `custom.toml` (fill in placeholders first) |
| `comitup.conf` | 1 | `/etc/comitup.conf` |
| `provision.sh` | 1 | `/opt/labeljetty/provision.sh` (Docker + udev + stack) |
| `labeljetty-provision.service` | 1 | `/etc/systemd/system/`, enabled once |
| `docker-compose.yml` | 1 | `/opt/labeljetty/docker-compose.yml` |

## Phase 0 — flash + headless boot (no Imager GUI)

1. Download **Raspberry Pi OS Lite (64-bit)** `.img.xz` and flash it with any tool
   (`dd`, Etcher, `rpi-imager --cli`) — we don't use the customisation screen at all.
2. Re-mount the small FAT partition (`bootfs`) and copy `boot/custom.toml.example` to it as
   **`custom.toml`**, after editing:
   - `hostname`, user `name`
   - user `password`: generate a hash with `openssl passwd -6` and paste it
   - `[wlan]` `ssid` + `password` (plaintext) + `country` — **or delete the whole `[wlan]`
     block** to force the Comitup portal on first boot (Phase 1 test).
3. Boot the Pi. After ~1–2 min: `ssh <user>@<hostname>.local`.

> Pi 3 B+ also has Ethernet — plugging it in for the first boot is a zero-config fallback if
> WiFi onboarding misbehaves.

## Phase 1 — install Comitup + the stack (over SSH)

Run on the Pi (proves the recipe; these exact steps become the Phase-2 image build):

```sh
# Comitup (WiFi AP + captive portal). Bookworm needs Comitup's NM python pkg — see their docs.
sudo apt-get update
sudo apt-get install -y comitup
sudo cp comitup.conf /etc/comitup.conf
# Comitup manages NetworkManager; disable the conflicting wpa_supplicant/dhcpcd path per its docs.

# LabelJetty stack
sudo install -Dm755 provision.sh                /opt/labeljetty/provision.sh
sudo install -Dm644 docker-compose.yml          /opt/labeljetty/docker-compose.yml
sudo install -Dm644 labeljetty-provision.service /etc/systemd/system/labeljetty-provision.service
sudo systemctl enable labeljetty-provision.service
sudo systemctl start  labeljetty-provision.service   # or just reboot

# Watch it install Docker + start LabelJetty
tail -f /var/log/labeljetty-provision.log
```

Verify:

```sh
docker compose -f /opt/labeljetty/docker-compose.yml ps
docker compose -f /opt/labeljetty/docker-compose.yml exec labeljetty labeljetty-testbench pattern
```

Then open `http://<hostname>.local:8888/`. To test the **no-WiFi portal**: forget the WiFi
connection (or boot with `[wlan]` removed), confirm the `LabelJetty-xxxx` AP appears and its
portal connects you to a real network.
