import inspect
import json
from typing import Dict, List, Callable, Any, Coroutine
from contextlib import asynccontextmanager

from dataclasses import dataclass
from fastapi import FastAPI

import secrets

from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.sessions import SessionMiddleware
from fastapi.staticfiles import StaticFiles

from pathlib import Path

from fastapi.openapi.utils import get_openapi


from labeljetty.web.api import fast_api_router
from labeljetty.web.ui import ui_router

from labeljetty.core.logging import get_logger
from labeljetty.config import Config, get_config
from labeljetty.version import get_version

import sys as _sys


def _static_dir() -> Path:
    """Путь к папке static — работает и в обычном запуске, и в PyInstaller exe."""
    if getattr(_sys, "frozen", False):
        return Path(_sys._MEIPASS) / "labeljetty" / "web" / "static"
    return Path(__file__).parent / "static"


STATIC_DIR = _static_dir()

log = get_logger()
config = get_config()


@dataclass
class AppLifespanCallback:
    func: Callable[..., None] | Callable[..., Coroutine[Any, Any, None]]
    params: Dict[str, Any] | None = None

    def is_async(self):
        return inspect.iscoroutinefunction(self.func)


class FastApiAppContainer:
    def __init__(self, url_prefix: str = "/api"):
        self.url_prefix = url_prefix
        self.shutdown_callbacks: List[AppLifespanCallback] = []
        self.startup_callbacks: List[AppLifespanCallback] = []
        # import __main__

        self.app = FastAPI(
            title="LabelJetty API",
            version=get_version(),
            lifespan=self._app_lifespan,
        )
        self._mount_routers()
        self._apply_api_middleware()
        self._apply_session_middleware()

    def add_startup_callback(
        self,
        func: Callable[..., None] | Callable[..., Coroutine[Any, Any, None]],
        params: Dict[str, Any] | None = None,
    ) -> None:
        self.startup_callbacks.append(AppLifespanCallback(func=func, params=params))

    def add_shutdown_callback(
        self,
        func: Callable[..., None] | Callable[..., Coroutine[Any, Any, None]],
        params: Dict[str, Any] | None = None,
    ) -> None:
        self.shutdown_callbacks.append(AppLifespanCallback(func=func, params=params))

    def dump_open_api_specification(self, json_file_path: Path):
        if json_file_path.suffix.upper() not in [".JSON"]:
            json_file_path = Path(json_file_path, "openapi.json")
        json_parent_dir_path = json_file_path.parent
        json_parent_dir_path.mkdir(exist_ok=True, parents=True)
        # f"{Path(__file__).parent}/../../openapi.json"
        with open(json_file_path, "w") as f:
            json.dump(
                get_openapi(
                    title=self.app.title,
                    version=self.app.version,
                    openapi_version=self.app.openapi_version,
                    description=self.app.description,
                    routes=self.app.routes,
                ),
                f,
                sort_keys=False,
                indent=2,
            )

    @asynccontextmanager
    async def _app_lifespan(self, app: FastAPI):
        # https://fastapi.tiangolo.com/advanced/events/#lifespan
        for cb in self.startup_callbacks:
            params = cb.params if cb.params else {}
            if cb.is_async():
                await cb.func(**params)
            else:
                cb.func(**params)

        yield
        for cb in self.shutdown_callbacks:
            params = cb.params if cb.params else {}
            if cb.is_async():
                await cb.func(**params)
            else:
                cb.func(**params)

    def _apply_api_middleware(self):
        allow_origins = ["0.0.0.0"]

        allow_origins = set(allow_origins)
        log.info(f"Origin allowed: {allow_origins}")
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=list(set(allow_origins)),
            allow_methods=["*"],
            allow_headers=["*"],
            allow_credentials=True,
        )

    def _apply_session_middleware(self):
        """Signed-cookie sessions for human login (and future OIDC).

        Without a configured SESSION_SECRET we generate an ephemeral one: logins
        work but do not survive a restart. Warn so production deployments set a
        stable secret.
        """
        secret = config.SESSION_SECRET
        if not secret:
            secret = secrets.token_hex(32)
            log.warning(
                "SESSION_SECRET is not set — using an ephemeral random secret. "
                "Sessions (logins) will not survive a restart. Set SESSION_SECRET "
                "for stable sessions."
            )
        self.app.add_middleware(
            SessionMiddleware,
            secret_key=secret,
            session_cookie=config.SESSION_COOKIE_NAME,
            max_age=config.SESSION_MAX_AGE,
            same_site="lax",
            https_only=False,
        )

    def _mount_routers(self):
        self.app.include_router(fast_api_router, prefix=self.url_prefix)
        # Web UI (server-rendered HTMX) mounted at the root.
        self.app.include_router(ui_router)
        self.app.mount(
            "/static", StaticFiles(directory=STATIC_DIR), name="static"
        )
