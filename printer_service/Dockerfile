# syntax=docker/dockerfile:1

FROM python:3.11-slim

# VERSION is the release being built (the git tag, e.g. "0.1.0"). It is:
#  - given to setuptools_scm so the package builds without a .git checkout, and
#  - exposed at runtime as LABELJETTY_VERSION so the app/API/UI report the release
#    (see labeljetty/version.py).
ARG VERSION=0.0.0
ENV SETUPTOOLS_SCM_PRETEND_VERSION=${VERSION} \
    LABELJETTY_VERSION=${VERSION} \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

# Runtime system deps:
#  - libusb-1.0-0: required by pyusb to talk to the USB printer
#  - fonts-dejavu-core: text/markdown rendering uses DejaVu Sans (DEFAULT_FONT_PATH)
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libusb-1.0-0 \
        fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

# uv: the official static binary from Astral's image.
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# Install into a project venv from the frozen lockfile. The source is needed
# because the project itself is installed (and version-stamped) — copy it all.
# pyproject's `readme` points at docs/README.pypi.md, so that file must be present
# at its original path for the build to succeed.
COPY pyproject.toml uv.lock ./
COPY docs/README.pypi.md ./docs/README.pypi.md
COPY src ./src
RUN uv sync --frozen --no-dev --no-editable

ENV PATH="/app/.venv/bin:$PATH"

# LOG_LEVEL is baked in at build time so the channel sets verbosity: production
# releases (:latest / :<version>) ship at INFO, while the dev/beta channels keep
# DEBUG. CI passes this per channel (see .github/workflows/docker*.yml). The app
# default is DEBUG, and a runtime `-e LOG_LEVEL=...` still overrides this.
ARG LOG_LEVEL=DEBUG

# Container-friendly defaults (override via env/-e). Data lives under /data so it
# can be a mounted volume; bind to all interfaces inside the container.
ENV SERVER_LISTENING_HOST=0.0.0.0 \
    SERVER_LISTENING_PORT=8888 \
    SQLITE_PATH=/data/printjobs.sqlite \
    IMAGE_STORAGE_DIRECTORY=/data/images \
    LOG_LEVEL=${LOG_LEVEL}

RUN mkdir -p /data
VOLUME ["/data"]
EXPOSE 8888

# PRINTER_USB has no default and must be provided at run time, e.g.:
#   docker run --device=/dev/bus/usb -e PRINTER_USB=vid:2d37:pid:62de ...
ENTRYPOINT ["labeljetty"]
