import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from app.collector.signal_classifier import SignalClassifier
from app.collector.search_provider import SearchProvider
from app.config import Settings
from app.repositories import HiringSignalRepository, PostRepository, RunRepository

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
        self.signals = HiringSignalRepository(db)
        self.runs = RunRepository(db)
        self.search = SearchProvider(settings)
        self.classifier = SignalClassifier(settings)

    def run_once(
        self,
        *,
        designations: list[str] | None = None,
        locations: list[str] | None = None,
        last_days: int | None = None,
    ) -> CollectorResult:
        started_at = datetime.now(tz=UTC)
        run = self.runs.create_run(started_at=started_at)

        inserted = 0
        skipped = 0

        try:
            queries = [q.strip() for q in (designations or self.settings.query_terms) if q.strip()]
            location_terms = [l.strip() for l in (locations or ["United States"]) if l.strip()]
            days_back = last_days if last_days is not None else self.settings.collector_days_back

            aggregated: list[dict] = []
            for query in queries:
                for location in location_terms:
                    logger.info(
                        "collector.query.start query=%s location=%s days_back=%s",
                        query,
                        location,
                        days_back,
                    )
                    rows = self.search.fetch(query, days_back=days_back, location=location)
                    if not rows and location.strip():
                        # If location-qualified search is too sparse, retry without location.
                        rows = self.search.fetch(query, days_back=days_back, location=None)
                    aggregated.extend(rows)
                    logger.info(
                        "collector.query.done query=%s location=%s rows=%s",
                        query,
                        location,
                        len(rows),
                    )

            deduped_map: dict[str, dict] = {}
            for row in aggregated:
                deduped_map[row["post_url"]] = row
            deduped = list(deduped_map.values())

            classifications = self.classifier.classify_many_sync(deduped)
            signal_rows: list[dict] = []
            for row, classification in zip(deduped, classifications, strict=False):
                company = classification.company.strip() or (row.get("company") or "").strip()
                if company and not row.get("company"):
                    row["company"] = company
                signal_rows.append(
                    {
                        "company": company or None,
                        "role": (classification.role.strip() or row.get("query_used") or "").strip() or None,
                        "seniority": (classification.seniority.strip() or row.get("seniority") or "").strip() or None,
                        "is_hiring": classification.is_hiring,
                        "signal_strength": classification.signal_strength,
                        "signal_type": classification.signal_type,
                        "confidence": classification.confidence,
                        "reasoning": classification.reasoning,
                        "source_url": row["post_url"],
                        "raw_text": f"{row.get('title', '').strip()} {row.get('query_used', '').strip()}".strip(),
                        "timestamp": datetime.now(tz=UTC),
                    }
                )
            inserted_signals = self.signals.insert_many(signal_rows)
            company_metrics = self.signals.aggregate_company_metrics()

            inserted = self.posts.insert_many_ignore_duplicates(deduped)
            skipped = max(0, len(deduped) - inserted)
            updated = self.posts.update_existing_from_rows(deduped)
            logger.info("collector.run.metadata_refresh updated=%s", updated)
            logger.info(
                "collector.run.signals stored=%s top_company_metrics=%s",
                inserted_signals,
                company_metrics[:5],
            )
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

    def debug_source(
        self,
        *,
        designations: list[str] | None = None,
        locations: list[str] | None = None,
        last_days: int | None = None,
        limit: int = 50,
    ) -> dict:
        queries = [q.strip() for q in (designations or self.settings.query_terms) if q.strip()]
        location_terms = [l.strip() for l in (locations or ["United States"]) if l.strip()]
        days_back = last_days if last_days is not None else self.settings.collector_days_back

        previews: list[dict] = []
        for query in queries:
            for location in location_terms:
                previews.append(
                    self.search.debug_preview(
                        query,
                        days_back=days_back,
                        location=location,
                        limit=limit,
                    )
                )
        return {"previews": previews}

    def preview_signals(
        self,
        *,
        designations: list[str] | None = None,
        locations: list[str] | None = None,
        last_days: int | None = None,
    ) -> dict:
        queries = [q.strip() for q in (designations or self.settings.query_terms) if q.strip()]
        location_terms = [l.strip() for l in (locations or ["United States"]) if l.strip()]
        days_back = last_days if last_days is not None else self.settings.collector_days_back

        filter_counts = {"blocked": 0, "non_linkedin": 0, "missing_hiring_term": 0}
        candidates: list[dict] = []

        for query in queries:
            for location in location_terms:
                preview = self.search.debug_preview(
                    query,
                    days_back=days_back,
                    location=location,
                    limit=120,
                )
                for item in preview.get("items", []):
                    is_blocked = bool(item.get("is_blocked"))
                    is_linkedin = bool(item.get("is_linkedin"))
                    has_hiring_term = bool(item.get("has_hiring_term"))

                    if is_blocked:
                        filter_counts["blocked"] += 1
                        continue
                    if not is_linkedin:
                        filter_counts["non_linkedin"] += 1
                        continue
                    if not has_hiring_term:
                        filter_counts["missing_hiring_term"] += 1
                        continue

                    candidates.append(
                        {
                            "title": item.get("title", ""),
                            "snippet": item.get("snippet", ""),
                            "url": item.get("url", ""),
                            "designation": query,
                            "search_query": item.get("search_query", ""),
                        }
                    )

        deduped_map: dict[str, dict] = {}
        for candidate in candidates:
            url = str(candidate.get("url") or "").strip()
            if not url:
                continue
            deduped_map[url] = candidate
        deduped = list(deduped_map.values())

        classifications = self.classifier.classify_many_sync(deduped)

        company_rows: dict[str, list[dict]] = defaultdict(list)
        strong_signals: list[dict] = []
        for row, classification in zip(deduped, classifications, strict=False):
            company = (classification.company or "").strip() or "Unknown"
            role = (classification.role or "").strip() or str(row.get("designation") or "").strip()
            entry = {
                "company": company,
                "role": role,
                "signal_strength": classification.signal_strength,
                "confidence": round(classification.confidence, 4),
                "url": str(row.get("url") or "").strip(),
                "is_hiring": classification.is_hiring,
            }
            company_rows[company].append(entry)
            if classification.is_hiring:
                strong_signals.append(entry)

        top_companies = []
        for company, rows in company_rows.items():
            strengths = [r["signal_strength"] for r in rows]
            avg_strength = (sum(strengths) / len(strengths)) if strengths else 0.0
            recent_roles = list(dict.fromkeys([r["role"] for r in rows if r["role"]]))[:5]
            top_companies.append(
                {
                    "company": company,
                    "signal_count": len(rows),
                    "avg_strength": round(avg_strength, 2),
                    "recent_roles": recent_roles,
                }
            )

        top_companies.sort(key=lambda x: (x["signal_count"], x["avg_strength"]), reverse=True)
        strong_signals.sort(key=lambda x: (x["signal_strength"], x["confidence"]), reverse=True)

        noise_filtered = sum(filter_counts.values())
        logger.info(
            "collector.preview_signals counts candidates=%s deduped=%s noise_filtered=%s filters=%s",
            len(candidates),
            len(deduped),
            noise_filtered,
            filter_counts,
        )

        return {
            "top_companies": top_companies[:10],
            "strong_signals": strong_signals[:10],
            "noise_filtered": noise_filtered,
        }
