import logging
import time

from app.scheduler import run_scheduled_job
from app.config import get_settings
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def run_worker_loop() -> None:
    settings = get_settings()
    configure_logging()
    interval_seconds = max(1, settings.scheduler_interval_hours) * 3600

    logger.info("worker.loop.start interval_hours=%s", settings.scheduler_interval_hours)
    while True:
        run_scheduled_job()
        logger.info("worker.sleep seconds=%s", interval_seconds)
        time.sleep(interval_seconds)


if __name__ == "__main__":
    run_worker_loop()
