import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.collector.search_provider import SearchProvider
from app.config import Settings
from app.repositories import PostRepository, RunRepository

logger = logging.getLogger(__name__)


@dataclass
class CollectorResult:
    run_id: int
    status: str
    inserted: int
    skipped: int
    error: str | None


class CollectorService:
    def __init__(self, db: Session, settings: Settings):
        self.db = db
        self.settings = settings
        self.posts = PostRepository(db)
        self.runs = RunRepository(db)
        self.search = SearchProvider(settings)

    def run_once(self) -> CollectorResult:
        started_at = datetime.now(tz=UTC)
        run = self.runs.create_run(started_at=started_at)

        inserted = 0
        skipped = 0

        try:
            aggregated: list[dict] = []
            for query in self.settings.query_terms:
                logger.info("collector.query.start query=%s", query)
                rows = self.search.fetch(query)
                aggregated.extend(rows)
                logger.info("collector.query.done query=%s rows=%s", query, len(rows))

            deduped_map: dict[str, dict] = {}
            for row in aggregated:
                deduped_map[row["post_url"]] = row
            deduped = list(deduped_map.values())

            inserted = self.posts.insert_many_ignore_duplicates(deduped)
            skipped = max(0, len(deduped) - inserted)
            finished = self.runs.complete_run(
                run.id,
                finished_at=datetime.now(tz=UTC),
                status="success",
                inserted=inserted,
                skipped=skipped,
                error=None,
            )
            logger.info(
                "collector.run.success run_id=%s inserted=%s skipped=%s",
                finished.id,
                finished.inserted,
                finished.skipped,
            )
            return CollectorResult(
                run_id=finished.id,
                status=finished.status,
                inserted=finished.inserted,
                skipped=finished.skipped,
                error=finished.error,
            )
        except Exception as exc:
            message = str(exc)
            finished = self.runs.complete_run(
                run.id,
                finished_at=datetime.now(tz=UTC),
                status="failed",
                inserted=inserted,
                skipped=skipped,
                error=message,
            )
            logger.exception("collector.run.failed run_id=%s error=%s", finished.id, message)
            return CollectorResult(
                run_id=finished.id,
                status=finished.status,
                inserted=finished.inserted,
                skipped=finished.skipped,
                error=finished.error,
            )

    def refresh_companies(self, limit: int = 500) -> tuple[int, int]:
        candidates = self.posts.list_for_company_refresh(limit=limit)
        updated = 0

        for post in candidates:
            extracted = self.search.company_extractor.extract_metadata(post.title, post.post_url)
            if not extracted.company and not extracted.seniority and not extracted.location:
                continue

            changed = False
            company = extracted.company.strip()
            seniority = extracted.seniority.strip()
            location = extracted.location.strip()

            if company and (post.company or "").strip().lower() != company.lower():
                post.company = company
                changed = True
            if seniority and (post.seniority or "").strip().lower() != seniority.lower():
                post.seniority = seniority
                changed = True
            if location and (post.location or "").strip().lower() != location.lower():
                post.location = location
                changed = True
            if post.remote != extracted.remote:
                post.remote = extracted.remote
                changed = True

            if not changed:
                continue
            self.db.add(post)
            updated += 1

        if updated > 0:
            self.db.commit()

        return len(candidates), updated
