"""Coordinator server entry point.

Run with::

    python -m app.coordinator.server
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

from dotenv import load_dotenv, find_dotenv

# Load .env from current directory or parent directories
load_dotenv(find_dotenv(usecwd=True), encoding="utf-8")

from app.coordinator.runtime import CoordinatorRuntime
from app.coordinator.admin.api import create_admin_api

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    host = os.getenv("AGBUS_HOST", "0.0.0.0")
    port = int(os.getenv("AGBUS_PORT", "8765"))
    api_port = int(os.getenv("AGBUS_API_PORT", "8766"))

    runtime = CoordinatorRuntime(host=host, port=port)
    await runtime.start()

    # Start the Admin REST API alongside the WebSocket server
    import uvicorn

    api_app = create_admin_api(runtime)
    config = uvicorn.Config(
        api_app,
        host=host,
        port=api_port,
        log_level=os.getenv("AGBUS_LOG_LEVEL", "info").lower(),
    )
    api_server = uvicorn.Server(config)
    api_task = asyncio.create_task(api_server.serve())
    logger.info("Admin API listening on http://%s:%d/api/docs", host, api_port)

    stop = asyncio.Event()

    if sys.platform != "win32":
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop.set)
    else:
        # On Windows, signal handlers don't work in asyncio.
        # We rely on KeyboardInterrupt (Ctrl+C) instead.

        def _wait_for_interrupt():
            try:
                while not stop.is_set():
                    stop.wait(timeout=0.5)  # type: ignore[arg-type]
            except KeyboardInterrupt:
                stop.set()

        # Actually, just let the main loop handle it via try/except
        pass

    logger.info("Coordinator running – press Ctrl+C to stop")

    try:
        await stop.wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass

    # Graceful shutdown
    api_server.should_exit = True
    await api_task
    await runtime.stop()
    logger.info("Coordinator shut down cleanly")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
