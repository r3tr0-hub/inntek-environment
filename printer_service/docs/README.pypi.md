# 🏷️ LabelJetty

**Turn a cheap, USB-only TSPL thermal label printer into a smart, network-accessible label
printer** - drive it from your phone, desktop, or another machine over your LAN. It talks to the
printer **directly over USB** (no CUPS, no vendor driver) and gives you a mobile-first web UI, a
REST API, and a Python library for printing PNGs, PDFs, text, markdown, barcodes and QR codes.
Optional, self-contained [Homebox](https://github.com/sysadminsmedia/homebox) integration is
built in.

## Install

```sh
pip install labeljetty
# or, with uv:
uv tool install labeljetty
```

This gives you three commands:

- `labeljetty` - runs the service (REST API + web UI + background print worker)
- `labeljetty-testbench` - drives the printer library directly (real device or dry-run)
- `labeljetty-hash-password` - generates a password hash for a login user

You need **Python 3.11+**, **libusb**, and a USB **TSPL** printer. `PRINTER_USB` auto-detects a
single connected printer; pin one (e.g. `PRINTER_USB=vid:2d37:pid:62de`, found via `lsusb`) in a
`.env` or the environment if you have several. Then run `labeljetty` and open
**http://localhost:8888/**. The
[Setup guide](https://github.com/motey/LabelJetty/blob/main/docs/setup.md) is the overview;
finding the printer and the [udev rule](https://github.com/motey/LabelJetty/blob/main/docs/advanced-usage.md#grant-usb-access)
are covered under Advanced usage.

> Prefer Docker? The image is [`motey/labeljetty`](https://hub.docker.com/r/motey/labeljetty).

## Heads-up

- **No authentication by default** - fine on a trusted home LAN, but turn on `AUTH_MODE=protected`
  before exposing it to an untrusted network.
- **Reference hardware is a Vretti 420B** (Poskey-class TSPL, ~203 dpi). It should work with any
  USB TSPL printer; feedback/PRs for other models are welcome.

## More information

Full docs, the configuration reference, authentication, the REST API, printer/udev setup, and
Homebox integration live on **GitHub: https://github.com/motey/LabelJetty**
