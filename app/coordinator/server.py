"""Coordinator server entry point.

Run with::

    python -m app.coordinator.server
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

from dotenv import load_dotenv, find_dotenv

# Load .env from current directory or parent directories
load_dotenv(find_dotenv(usecwd=True))

from app.coordinator.runtime import CoordinatorRuntime

logging.basicConfig(
    level=os.getenv("AGBUS_LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    host = os.getenv("AGBUS_HOST", "0.0.0.0")
    port = int(os.getenv("AGBUS_PORT", "8765"))

    runtime = CoordinatorRuntime(host=host, port=port)
    await runtime.start()

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)

    logger.info("Coordinator running – press Ctrl+C to stop")
    await stop.wait()

    await runtime.stop()
    logger.info("Coordinator shut down cleanly")


if __name__ == "__main__":
    asyncio.run(main())
