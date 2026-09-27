"""Single source of truth for the running version.

Resolution order (first hit wins):

1. ``LABELJETTY_VERSION`` env var — how the version is *branded* into the Docker
   image. The image is built with ``--build-arg VERSION=…`` (the git tag) which
   the Dockerfile exposes as this env var, so the container reports its release
   without needing a ``.git`` checkout inside the image.
2. Installed package metadata — for a normal ``pip``/``uv`` install from PyPI the
   version comes from the wheel that hatch-vcs stamped at build time from the tag.
3. ``_version.py`` — the file hatch-vcs writes into the source tree at build time
   (present in an editable/dev install).
4. ``"0.0.0+unknown"`` — running straight from a source tree with no metadata.
"""

from __future__ import annotations

import os


def get_version() -> str:
    branded = os.environ.get("LABELJETTY_VERSION")
    if branded:
        return branded

    try:
        from importlib.metadata import PackageNotFoundError, version

        try:
            return version("labeljetty")
        except PackageNotFoundError:
            pass
    except Exception:
        pass

    try:
        from labeljetty._version import __version__  # type: ignore

        return __version__
    except Exception:
        return "0.0.0+unknown"
