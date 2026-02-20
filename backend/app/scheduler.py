import logging

from app.collector.service import CollectorService
from app.config import get_settings
from app.db import SessionLocal
from app.logging_config import configure_logging

logger = logging.getLogger(__name__)


def run_scheduled_job() -> int:
    settings = get_settings()
    configure_logging()
    db = SessionLocal()
    try:
        result = CollectorService(db, settings).run_once()
        logger.info(
            "scheduler.run status=%s inserted=%s skipped=%s error=%s",
            result.status,
            result.inserted,
            result.skipped,
            result.error,
        )
        return 0 if result.status == "success" else 1
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(run_scheduled_job())
