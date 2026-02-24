from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import HiringSignal, Post, Run, SignalFeedback


class PostRepository:
    def __init__(self, db: Session):
        self.db = db

    def insert_many_ignore_duplicates(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = insert(Post).values(rows)
        stmt = stmt.on_conflict_do_nothing(index_elements=[Post.post_url])
        stmt = stmt.returning(Post.id)
        result = self.db.execute(stmt)
        inserted_ids = result.scalars().all()
        return len(inserted_ids)

    def list_posts(
        self,
        *,
        company: str | None,
        title: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
        page: int,
        page_size: int,
    ) -> tuple[list[Post], int]:
        filters = []
        if company:
            filters.append(Post.company.ilike(f"%{company}%"))
        if title:
            filters.append(Post.title.ilike(f"%{title}%"))
        if date_from:
            filters.append(Post.first_seen >= date_from)
        if date_to:
            filters.append(Post.first_seen <= date_to)

        where_clause = and_(*filters) if filters else None

        total_query = select(func.count()).select_from(Post)
        if where_clause is not None:
            total_query = total_query.where(where_clause)
        total = self.db.execute(total_query).scalar_one()

        items_query = select(Post)
        if where_clause is not None:
            items_query = items_query.where(where_clause)
        items_query = (
            items_query.order_by(Post.first_seen.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )

        items = self.db.execute(items_query).scalars().all()
        return items, total

    def list_for_export(
        self,
        *,
        company: str | None,
        title: str | None,
        date_from: datetime | None,
        date_to: datetime | None,
    ) -> list[Post]:
        filters = []
        if company:
            filters.append(Post.company.ilike(f"%{company}%"))
        if title:
            filters.append(Post.title.ilike(f"%{title}%"))
        if date_from:
            filters.append(Post.first_seen >= date_from)
        if date_to:
            filters.append(Post.first_seen <= date_to)

        query = select(Post)
        if filters:
            query = query.where(and_(*filters))
        query = query.order_by(Post.first_seen.desc())
        return self.db.execute(query).scalars().all()

    def update_status(self, post_id: int, status: str) -> Post | None:
        post = self.db.get(Post, post_id)
        if post is None:
            return None
        post.status = status
        self.db.add(post)
        self.db.commit()
        self.db.refresh(post)
        return post

    def update_existing_from_rows(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        urls = [row["post_url"] for row in rows if row.get("post_url")]
        if not urls:
            return 0

        existing = self.db.execute(select(Post).where(Post.post_url.in_(urls))).scalars().all()
        by_url = {post.post_url: post for post in existing}

        updated = 0
        for row in rows:
            post_url = row.get("post_url")
            if not post_url:
                continue
            post = by_url.get(post_url)
            if post is None:
                continue

            changed = False
            company = (row.get("company") or "").strip()
            seniority = (row.get("seniority") or "").strip()
            location = (row.get("location") or "").strip()

            if company and (post.company or "").strip().lower() != company.lower():
                post.company = company
                changed = True
            if seniority and (post.seniority or "").strip().lower() != seniority.lower():
                post.seniority = seniority
                changed = True
            if location and (post.location or "").strip().lower() != location.lower():
                post.location = location
                changed = True

            remote = row.get("remote")
            if isinstance(remote, bool) and post.remote != remote:
                post.remote = remote
                changed = True

            if changed:
                self.db.add(post)
                updated += 1

        if updated > 0:
            self.db.commit()
        return updated

    def list_for_company_refresh(self, *, limit: int) -> list[Post]:
        unknown = func.lower(func.coalesce(Post.company, "")) == "unknown"
        empty_company = func.length(func.trim(func.coalesce(Post.company, ""))) == 0
        empty_seniority = func.length(func.trim(func.coalesce(Post.seniority, ""))) == 0
        empty_location = func.length(func.trim(func.coalesce(Post.location, ""))) == 0
        suspicious_company = or_(
            Post.company.ilike("we are%"),
            Post.company.ilike("we're%"),
            Post.company.ilike("hiring%"),
            Post.company.ilike("looking for%"),
            Post.company.ilike("%product manager%"),
            Post.company.ilike("%program manager%"),
            Post.company.ilike("%hiring list%"),
            func.length(func.coalesce(Post.company, "")) > 48,
        )
        query = (
            select(Post)
            .where(or_(unknown, empty_company, empty_seniority, empty_location, suspicious_company))
            .order_by(Post.first_seen.desc())
            .limit(limit)
        )
        return self.db.execute(query).scalars().all()


class RunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create_run(self, *, started_at: datetime) -> Run:
        run = Run(
            started_at=started_at,
            status="running",
            inserted=0,
            skipped=0,
            error=None,
        )
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def complete_run(
        self,
        run_id: int,
        *,
        finished_at: datetime,
        status: str,
        inserted: int,
        skipped: int,
        error: str | None,
    ) -> Run:
        run = self.db.get(Run, run_id)
        if run is None:
            raise ValueError(f"Run {run_id} not found")

        run.finished_at = finished_at
        run.status = status
        run.inserted = inserted
        run.skipped = skipped
        run.error = error
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def list_runs(self, limit: int = 50) -> list[Run]:
        query = select(Run).order_by(Run.started_at.desc()).limit(limit)
        return self.db.execute(query).scalars().all()


class HiringSignalRepository:
    def __init__(self, db: Session):
        self.db = db

    def insert_many(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        stmt = insert(HiringSignal).values(rows)
        stmt = stmt.returning(HiringSignal.id)
        result = self.db.execute(stmt)
        inserted_ids = result.scalars().all()
        self.db.commit()
        return len(inserted_ids)

    def aggregate_company_metrics(self) -> list[dict]:
        strong_case = case((HiringSignal.signal_strength >= 4, 1), else_=0)
        query = (
            select(
                func.coalesce(HiringSignal.company, "").label("company"),
                func.sum(strong_case).label("strong_signals"),
                func.avg(HiringSignal.signal_strength).label("avg_signal_strength"),
            )
            .group_by(HiringSignal.company)
            .order_by(func.avg(HiringSignal.signal_strength).desc(), func.sum(strong_case).desc())
            .limit(50)
        )
        rows = self.db.execute(query).all()
        return [
            {
                "company": company or "",
                "strong_signals": int(strong_signals or 0),
                "avg_signal_strength": float(avg_signal_strength or 0.0),
            }
            for company, strong_signals, avg_signal_strength in rows
        ]

    def list_signals(
        self,
        *,
        min_confidence: float,
        hiring_strictness: str,
        role_similarity_threshold: float,
        page: int,
        page_size: int,
        review_status: str | None = None,
        days_back: int | None = None,
    ) -> tuple[list[HiringSignal], int, int]:
        base_filters = []
        if days_back and days_back > 0:
            base_filters.append(HiringSignal.timestamp >= datetime.now(tz=UTC) - timedelta(days=days_back))
        if review_status:
            base_filters.append(HiringSignal.review_status == review_status)

        tuning_filters = self._tuning_filters(
            min_confidence=min_confidence,
            hiring_strictness=hiring_strictness,
            role_similarity_threshold=role_similarity_threshold,
        )
        all_filters = [*base_filters, *tuning_filters]

        base_total_query = select(func.count()).select_from(HiringSignal)
        if base_filters:
            base_total_query = base_total_query.where(and_(*base_filters))
        total_base = int(self.db.execute(base_total_query).scalar_one() or 0)

        filtered_total_query = select(func.count()).select_from(HiringSignal)
        if all_filters:
            filtered_total_query = filtered_total_query.where(and_(*all_filters))
        total_filtered = int(self.db.execute(filtered_total_query).scalar_one() or 0)

        query = select(HiringSignal)
        if all_filters:
            query = query.where(and_(*all_filters))
        query = query.order_by(HiringSignal.timestamp.desc()).offset((page - 1) * page_size).limit(page_size)
        items = self.db.execute(query).scalars().all()
        return items, total_filtered, total_base

    def update_review(
        self,
        *,
        signal_id: int,
        action: str,
        label: str | None,
        notes: str | None,
        reviewer_id: str | None,
    ) -> HiringSignal | None:
        signal = self.db.get(HiringSignal, signal_id)
        if signal is None:
            return None

        if action == "approve":
            signal.review_status = "approved"
        elif action == "reject":
            signal.review_status = "rejected"
        else:
            signal.review_status = "relabelled"
        signal.review_label = (label or "").strip() or None
        signal.reviewed_at = datetime.now(tz=UTC)
        signal.reviewed_by = reviewer_id
        self.db.add(signal)

        feedback = SignalFeedback(
            signal_id=signal.id,
            action=action,
            label=signal.review_label,
            notes=(notes or "").strip() or None,
            reviewer_id=reviewer_id,
        )
        self.db.add(feedback)
        self.db.commit()
        self.db.refresh(signal)
        return signal

    def list_review_queue(self, *, limit: int = 100) -> list[HiringSignal]:
        query = (
            select(HiringSignal)
            .where(HiringSignal.review_status == "pending")
            .order_by(HiringSignal.timestamp.desc())
            .limit(limit)
        )
        return self.db.execute(query).scalars().all()

    def filter_reason_counts(
        self,
        *,
        min_confidence: float,
        hiring_strictness: str,
        role_similarity_threshold: float,
        days_back: int | None,
    ) -> list[dict]:
        base_filters = []
        if days_back and days_back > 0:
            base_filters.append(HiringSignal.timestamp >= datetime.now(tz=UTC) - timedelta(days=days_back))

        low_confidence_q = select(func.count()).select_from(HiringSignal).where(HiringSignal.confidence < min_confidence)
        low_role_q = (
            select(func.count())
            .select_from(HiringSignal)
            .where(HiringSignal.role_match_score < role_similarity_threshold)
        )

        strictness_filters = self._strictness_only_filters(hiring_strictness)
        low_strictness_count = 0
        low_strictness_q = select(func.count()).select_from(HiringSignal)
        for f in strictness_filters:
            low_strictness_q = low_strictness_q.where(f)

        if base_filters:
            for f in base_filters:
                low_confidence_q = low_confidence_q.where(f)
                low_role_q = low_role_q.where(f)
                if strictness_filters:
                    low_strictness_q = low_strictness_q.where(f)

        if strictness_filters:
            low_strictness_count = int(self.db.execute(low_strictness_q).scalar_one() or 0)

        return [
            {"reason": "low_confidence", "count": int(self.db.execute(low_confidence_q).scalar_one() or 0)},
            {"reason": "low_role_similarity", "count": int(self.db.execute(low_role_q).scalar_one() or 0)},
            {"reason": "strictness_filter", "count": low_strictness_count},
        ]

    def false_positive_trends(self, *, days: int = 14) -> list[dict]:
        since = datetime.now(tz=UTC) - timedelta(days=days)
        query = (
            select(
                func.date_trunc("day", SignalFeedback.created_at).label("day"),
                func.count().label("count"),
            )
            .where(SignalFeedback.created_at >= since, SignalFeedback.action == "reject")
            .group_by(func.date_trunc("day", SignalFeedback.created_at))
            .order_by(func.date_trunc("day", SignalFeedback.created_at).asc())
        )
        rows = self.db.execute(query).all()
        return [{"day": day.isoformat(), "count": int(count)} for day, count in rows]

    def emerging_companies(self, *, days: int = 14, limit: int = 10) -> list[dict]:
        since = datetime.now(tz=UTC) - timedelta(days=days)
        query = (
            select(
                func.coalesce(HiringSignal.company, "").label("company"),
                func.count().label("signals"),
                func.avg(HiringSignal.signal_strength).label("avg_strength"),
            )
            .where(HiringSignal.timestamp >= since, HiringSignal.is_hiring.is_(True))
            .group_by(HiringSignal.company)
            .order_by(func.count().desc(), func.avg(HiringSignal.signal_strength).desc())
            .limit(limit)
        )
        rows = self.db.execute(query).all()
        return [
            {
                "company": company or "Unknown",
                "signals": int(signals or 0),
                "avg_strength": round(float(avg_strength or 0.0), 2),
            }
            for company, signals, avg_strength in rows
        ]

    def hidden_hiring_clusters(self, *, days: int = 30, limit: int = 10) -> list[dict]:
        since = datetime.now(tz=UTC) - timedelta(days=days)
        query = (
            select(
                func.coalesce(HiringSignal.company, "").label("company"),
                func.coalesce(HiringSignal.role, "").label("role"),
                func.count().label("signals"),
                func.avg(HiringSignal.signal_strength).label("avg_strength"),
            )
            .where(
                HiringSignal.timestamp >= since,
                HiringSignal.is_hiring.is_(True),
                HiringSignal.signal_strength >= 3,
            )
            .group_by(HiringSignal.company, HiringSignal.role)
            .having(func.count() >= 2)
            .order_by(func.count().desc(), func.avg(HiringSignal.signal_strength).desc())
            .limit(limit)
        )
        rows = self.db.execute(query).all()
        return [
            {
                "company": company or "Unknown",
                "role": role or "Unknown",
                "signals": int(signals or 0),
                "avg_strength": round(float(avg_strength or 0.0), 2),
            }
            for company, role, signals, avg_strength in rows
        ]

    def _tuning_filters(
        self,
        *,
        min_confidence: float,
        hiring_strictness: str,
        role_similarity_threshold: float,
    ) -> list:
        filters = [HiringSignal.confidence >= min_confidence]
        if role_similarity_threshold > 0:
            filters.append(HiringSignal.role_match_score >= role_similarity_threshold)
        filters.extend(self._strictness_only_filters(hiring_strictness, inverse=False))
        return filters

    def _strictness_only_filters(self, hiring_strictness: str, inverse: bool = True) -> list:
        level = hiring_strictness.strip().lower()
        if level == "high":
            if inverse:
                return [or_(HiringSignal.is_hiring.is_(False), HiringSignal.signal_strength < 4, HiringSignal.hiring_confidence < 0.7)]
            return [HiringSignal.is_hiring.is_(True), HiringSignal.signal_strength >= 4, HiringSignal.hiring_confidence >= 0.7]
        if level == "medium":
            if inverse:
                return [or_(HiringSignal.is_hiring.is_(False), HiringSignal.signal_strength < 3)]
            return [HiringSignal.is_hiring.is_(True), HiringSignal.signal_strength >= 3]
        return []
