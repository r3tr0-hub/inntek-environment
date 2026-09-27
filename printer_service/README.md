# 🏷️ LabelJetty

<a href="docs/labejetti_screenshot.png"><img src="docs/labejetti_screenshot.png" alt="LabelJetty web UI" align="right" width="250"></a>

**Turn a cheap, USB-only TSPL thermal label printer into a smart, network-accessible label
printer** - drive it from your phone, desktop, or another machine over your LAN (a Raspberry Pi
next to the printer is the classic setup).

It talks to the printer **directly over USB** (`pyusb`/libusb) - no CUPS, no vendor driver - and
gives you a mobile-first **web UI**, a **REST API**, and a Python **library** for printing PNGs,
PDFs, text, markdown, barcodes and QR codes, plus an optional, self-contained
**[Homebox](https://github.com/sysadminsmedia/homebox)** integration for inventory labels.

> **Status:** functional (library, REST API, web UI, Homebox, multi-token/user auth all work) but
> still an early **beta** - expect rough edges, and please [file bugs / feedback](../../issues).
> See the [Roadmap](docs/roadmap.md) for what's next.

## ✨ Features

- 📦 **[Homebox](docs/advanced-usage.md#homebox-integration) integration** (the headline feature) -
  search your self-hosted inventory and print labels from the UI, or wire up Homebox's own print
  button. Optional and invisible until you configure it.
- **Direct USB** to TSPL printers - minimal dependencies, no CUPS.
- Print **PNG, PDF, text, markdown, barcodes** (Code128/EAN/UPC/Code39/...) and **QR codes**, plus
  composite barcode/QR + text labels.
- **[Auto-fit rendering](docs/advanced-usage.md#text-rendering--auto-fit)** - text, markdown and QR
  scale to the label automatically; no guessing font sizes.
- Configurable **label size & DPI**, with named **[profiles](docs/configuration.md)** for your stock.
- **Mobile-first web UI** - print every type, **preview** before printing, live job/printer status.
- **REST API** (FastAPI) on a persistent SQLite **job queue** + single **worker**; live docs at
  `/docs`, `/redoc`, `/openapi.json` ([reference](docs/advanced-usage.md#the-rest-api)).
- **[Auth](docs/advanced-usage.md#authentication) when you want it** - multi-token + multi-user
  login, off by default ([OIDC planned](docs/roadmap.md#oidc--sso-authentication)).
- **Dry-run mode** + a **[CLI test bench](docs/developing.md#real-world-print-tests-with-the-testbench)**
  for hardware-free development and on-device geometry checks.

## 🚀 Install

**Recommended:** on a Raspberry Pi (or any Debian-based Linux box), one line installs Docker,
the USB udev rule, and LabelJetty, then prints how to reach the UI:

```sh
curl -fsSL https://raw.githubusercontent.com/motey/LabelJetty/main/deploy/install.sh | bash
```

The script ([`deploy/install.sh`](deploy/install.sh)) is **idempotent** - safe to re-run to update.
Prefer to read before piping to a shell? Download and inspect it first:

```sh
curl -fsSL https://raw.githubusercontent.com/motey/LabelJetty/main/deploy/install.sh -o install.sh
less install.sh && bash install.sh
```

It **auto-detects your connected printer** (and writes a matching udev rule), so there's nothing
to configure for a single printer. Tunables if you need them: `PRINTER_USB=...` (pin a specific
device when several are attached), `LABELJETTY_DIR=...`, `LABEL_WIDTH_MM/HEIGHT_MM/DPI`.

> **New here?** The **[Setup guide](docs/setup.md)** is the start-to-finish overview (printer →
> install → verify → configure). Want to do it **by hand** - picking a printer, the udev rule, the
> [`docker-compose.yml`](docker-compose.yml)? That step-by-step Docker Compose deployment, which is
> exactly what the installer automates, is in
> [Manual Docker setup](docs/advanced-usage.md#manual-docker-setup).

Image tags (`latest` / `beta` / `X.Y.Z` / `dev`) and architectures (incl. 64-bit Pi 3/4/5) are in
[Advanced usage → Docker](docs/advanced-usage.md#docker-tags--architectures); running **without
Docker** (PyPI / source) is in [Advanced usage](docs/advanced-usage.md).

## ⚠️ Important to know

- **No authentication by default.** With `AUTH_MODE=open` (the default) every endpoint and the
  whole web UI are public - fine for a trusted home LAN, but **don't expose it to an untrusted
  network** without turning on [auth](docs/advanced-usage.md#authentication).
- **Reference hardware is a cheap Vretti 420B** (Poskey-class TSPL, ~203 dpi, `2d37:62de`) - the
  only verified model. It *should* work with any USB TSPL printer; **feedback / PRs for other
  printers are welcome** ([issue](../../issues)). See [Hardware](docs/hardware.md) for what to buy.
- **Many cheap clones are write-only for status** - they print fine but always report "ready".
  Printing is unaffected ([details](docs/configuration.md#status-reading-is-optional)).

## 💡 Motivation

The itch behind this is **printing labels for a self-hosted
[Homebox](https://github.com/sysadminsmedia/homebox) inventory** (a QR + name/asset id, from a
phone) - but Homebox is a clean, optional module on top of a **general-purpose TSPL printer
service** that's just as useful on its own. Guiding principles:

- **No CUPS wrapper** - a single thermal printer doesn't need a spooler and PPDs; raw TSPL over USB
  is simpler and behaves the same everywhere.
- **Lowest dependency cost** - pure-wheel libraries only (`pypdfium2`, `segno`, ...), no system
  print stack; runs happily on a Pi.
- **Generic core, optional integrations** - the service knows nothing about Homebox until you
  configure it.

The architecture and trade-offs are in **[Design](docs/design.md)**.

## 📚 Documentation

| Doc | What's in it |
| --- | --- |
| **[Setup guide](docs/setup.md)** | Start here: printer to first label - get a printer, install (the one-liner), verify, configure. |
| **[Configuration](docs/configuration.md)** | Every setting (must / should / optional) and the `PRINTER_USB` selector forms. |
| **[Updating](docs/updating.md)** | Move to a new release (Compose, `docker run`, installer, Watchtower); the UI flags when one is out. |
| **[Advanced usage](docs/advanced-usage.md)** | Non-Docker install, authentication, the REST API, text auto-fit, Homebox, Docker tags/arches. |
| **[Hardware](docs/hardware.md)** | Which cheap 420B-class printer to buy and where (rough, LLM-sourced stub for now). |
| **[Design](docs/design.md)** | Architecture, the moving parts, and the reasoning behind the design. |
| **[Roadmap](docs/roadmap.md)** | What's planned next - printer auto-discovery, OIDC/SSO, and more. |
| **[Developing](docs/developing.md)** | Contributor onramp: project layout, running from source, tests, and the testbench. |
| **[Testing](docs/TESTING.md)** | Deep reference on the automated test harness (isolation, fixtures, coverage, CI). |
| **[Build & release](docs/BUILD.md)** | Versioning (`hatch-vcs`), the Docker image, and release workflows. |

## 📄 License

[MIT](LICENSE)
