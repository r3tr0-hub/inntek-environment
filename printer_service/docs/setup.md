# Setup guide

From nothing to a printed label. The classic setup is a Raspberry Pi next to the printer, but
any Linux host with a USB port works.

1. [Get a printer](#1-get-a-printer)
2. [Install](#2-install)
3. [Verify](#3-verify)
4. [Configure](#4-configure)
5. [Next steps](#next-steps)

## 1. Get a printer

You need a USB printer that speaks **TSPL** (~203 dpi is typical). The reference device is a
cheap **Vretti 420B** (USB id `2d37:62de`); any genuine TSPL-over-USB printer should work. See
[Hardware](hardware.md) for what to buy and which clones are equivalent.

## 2. Install

On a Raspberry Pi or any Debian-based box, the **one-line installer** is all you need. It
installs Docker, detects your connected printer and writes a matching USB udev rule, drops a
`docker-compose.yml` under `~/labeljetty`, brings the stack up, and prints how to reach the UI:

```sh
curl -fsSL https://raw.githubusercontent.com/motey/LabelJetty/main/deploy/install.sh | bash
```

It **auto-detects a single connected TSPL printer**, so there's nothing to configure for the
common case. The script is idempotent (safe to re-run to update). To read it before piping to a
shell, or for its tunables (`PRINTER_USB` to pin a device, `LABELJETTY_DIR`, label size), see
[Install](../README.md#-install).

> **Not on a Debian host, or want to do it by hand?** The same Docker Compose deployment, step
> by step (prepare the host, find the printer, the udev rule, the compose file), is in
> [Manual Docker setup](advanced-usage.md#manual-docker-setup). To run **without Docker** (from
> PyPI or a source checkout) instead, see
> [Running without Docker](advanced-usage.md#running-without-docker).

## 3. Verify

Open `http://<host>:8888/` (the installer prints the exact address). The surest test that
the printer works and the label geometry is right is the built-in alignment pattern - from the
compose directory (`~/labeljetty` by default):

```sh
docker compose exec labeljetty labeljetty-testbench pattern
```

<details>
<summary>Not using Compose? - docker / uv / python</summary>

```sh
# docker
docker exec labeljetty labeljetty-testbench pattern

# uv (from a source checkout)
uv run labeljetty-testbench pattern

# python (venv with `pip install labeljetty`)
python -m labeljetty.testbench pattern
```

</details>

A correctly configured label shows a border flush to all four edges, with the millimetre ruler
ticks landing on whole millimetres. Adjust `--width-mm` / `--height-mm` / `--dpi` (or the
`DEFAULT_LABEL_*` settings below) to match your stock. More testbench commands are in
[Developing](developing.md#real-world-print-tests-with-the-testbench).

> Many cheap clones are **write-only for status**: they print fine but never answer status
> queries. That is expected and does not affect printing, see
> [Status reading is optional](configuration.md#status-reading-is-optional).

## 4. Configure

Match your label stock by setting `DEFAULT_LABEL_WIDTH_MM` / `DEFAULT_LABEL_HEIGHT_MM` /
`DEFAULT_DPI`; every other setting is optional. There are two ways to do it:

- **From the browser** - enable the [settings page](configuration.md#settings-via-the-web-ui)
  (`SETTINGS_UI_ENABLED=true`) and edit label defaults and profiles, the printer selector, the
  Homebox connection, auth, and more at runtime, without touching env vars or restarting.
- **Env vars / Compose** - set them in the `environment:` block of your `docker-compose.yml`
  (the installer writes it under `~/labeljetty`) or a `.env` file. Every setting is documented
  in **[Configuration](configuration.md)**.

## Next steps

- **[Configuration](configuration.md)** - every setting, and which to set for your stock.
- **[Authentication](advanced-usage.md#authentication)** - the default is **no auth**; turn it
  on before exposing the service beyond a trusted LAN (via env, or from the
  [settings page](configuration.md#settings-via-the-web-ui) once enabled).
- **[Homebox integration](advanced-usage.md#homebox-integration)** - print inventory labels.
- **[REST API](advanced-usage.md#the-rest-api)** - drive it from scripts and other machines.
- **[Updating](updating.md)** - how to move to a new release (the UI flags when one is out).
