# Updating LabelJetty

LabelJetty tells you when a new release is out (an **update-available banner** appears in the web
UI), but applying the update is a manual step you run on the host. A container can't replace its
own image — pulling the new image and recreating the container is an action for whatever started
it (Docker Compose, `docker run`, or the installer).

This page covers each deployment. Your data (the SQLite job DB and stored images) lives in the
`./data` volume and is **untouched** by an update.

## Docker Compose (recommended)

From your compose directory (`~/labeljetty` if you used the installer):

```sh
docker compose pull        # fetch the new image for the tag you track (e.g. :latest)
docker compose up -d        # recreate the container on the new image
docker image prune -f       # optional: drop the now-unused old image
```

That's it — `up -d` only recreates the service whose image changed, and the `./data` volume
carries over. Check the running version in the web UI footer, or:

```sh
curl -s http://localhost:8888/api/version
```

> **Which tag do you track?** `:latest` (every release) is the default. If your compose file
> pins `image: motey/labeljetty:X.Y.Z`, `pull` won't move you forward — bump the tag in
> `docker-compose.yml` first, then `pull` + `up -d`. See the [tag list](README.docker.md#tags).

## Plain `docker run`

```sh
docker pull motey/labeljetty:latest
docker rm -f labeljetty
docker run -d --name labeljetty -p 8888:8888 \
  --device=/dev/bus/usb \
  -e PRINTER_USB=vid:2d37:pid:62de \
  -v "$(pwd)/data:/data" \
  motey/labeljetty:latest
```

(Re-use the exact flags from your original `docker run`; only the image is pulled fresh.)

## Installer-based setup

The [one-line installer](../README.md#-install) is **idempotent** — re-running it pulls the
latest image and brings the stack back up, leaving your `data/` and udev rule in place:

```sh
curl -fsSL https://raw.githubusercontent.com/motey/LabelJetty/main/deploy/install.sh | bash
```

## Without Docker (PyPI / source)

```sh
# PyPI install
pip install --upgrade labeljetty       # or: uv pip install --upgrade labeljetty

# source checkout
git pull && uv sync
```

Restart the service afterwards (your `systemd` unit, `uv run labeljetty`, etc.).

## Automatic updates (optional)

If you'd rather not update by hand, [Watchtower](https://containrrr.dev/watchtower/) watches the
registry and recreates the container when a new image is pushed. Add it alongside LabelJetty and
opt the service in with a label:

```yaml
services:
  labeljetty:
    image: motey/labeljetty:latest
    labels:
      com.centurylinklabs.watchtower.enable: "true"
    # …rest of your service as usual…

  watchtower:
    image: containrrr/watchtower
    restart: unless-stopped
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    command: --label-enable --cleanup --interval 86400   # check daily
```

Watchtower needs the Docker socket (effectively host root), so only add it if you're comfortable
with that trade-off. It handles the pull-and-recreate lifecycle that an in-app "update now" button
can't do safely from inside the container.

## The update-available banner

The banner is driven by a single cached call to the public GitHub releases API. To turn it off
(offline/air-gapped deployments), set `UPDATE_CHECK_ENABLED=false` — or toggle **Check for
updates** on the in-app settings page. Pre-releases never trigger it. On a fork, point
`UPDATE_CHECK_REPO` at your own `owner/repo`. See [Configuration](configuration.md).
