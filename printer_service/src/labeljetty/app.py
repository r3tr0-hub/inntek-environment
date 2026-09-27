from typing import cast
from pathlib import Path
import uvicorn
import asyncio
from uvicorn.config import LOGGING_CONFIG
from uvicorn.config import LifespanType

from labeljetty.web.app import FastApiAppContainer
from labeljetty.service.worker import PrintServiceManager


def run():
    import multiprocessing
    multiprocessing.freeze_support()

    from labeljetty.config import get_config
    from labeljetty.core.logging import get_logger, get_uvicorn_loglevel

    config = get_config()
    log = get_logger()
    log.info(f"LOG_LEVEL: {config.LOG_LEVEL}")
    log.info(f"UVICORN_LOG_LEVEL: {get_uvicorn_loglevel()}")
    log.info(f"Create image storage directory at '{config.IMAGE_STORAGE_DIRECTORY}'")
    if config.PRINTER_USB:
        log.info(f"USB printer selector: {config.PRINTER_USB}")
    else:
        log.info("PRINTER_USB unset — auto-detecting a connected TSPL printer")
    if config.auth_enabled():
        log.info(f"AUTH_MODE=protected — {len(config.AUTH_TOKENS)} token(s), {len(config.AUTH_USERS)} user(s)")
    else:
        log.warning(
            "AUTH_MODE=open — NO AUTHENTICATION. Every endpoint is public. "
            "Only run this on a trusted LAN. Set AUTH_MODE=protected with "
            "AUTH_TOKENS/AUTH_USERS before exposing it more widely."
        )
    Path(config.IMAGE_STORAGE_DIRECTORY).mkdir(parents=True, exist_ok=True)

    event_loop = asyncio.new_event_loop()
    asyncio.set_event_loop(event_loop)
    uvicorn_log_config = LOGGING_CONFIG
    fast_api_container = FastApiAppContainer()
    uvicorn_config = uvicorn.Config(
        app=fast_api_container.app,
        host=config.SERVER_LISTENING_HOST,
        port=config.SERVER_LISTENING_PORT,
        log_level=get_uvicorn_loglevel(),
        log_config=uvicorn_log_config,
        loop=event_loop,
        lifespan=cast(LifespanType, "on"),
    )
    uvicorn_server = uvicorn.Server(config=uvicorn_config)
    print_service = PrintServiceManager()
    fast_api_container.add_startup_callback(print_service.start)
    fast_api_container.add_shutdown_callback(print_service.shutdown)
    try:
        log.debug("Start uvicorn server...")
        event_loop.run_until_complete(uvicorn_server.serve())
    except KeyboardInterrupt:
        log.info("KeyboardInterrupt shutdown...")
    except Exception:
        log.info("Panic shutdown...")
        raise
    finally:
        # Always tear the worker down with us — uvicorn's lifespan shutdown does
        # not run when KeyboardInterrupt escapes serve(), so the lifespan callback
        # alone is not enough. shutdown() is idempotent.
        print_service.shutdown()


if __name__ == "__main__":
    run()
