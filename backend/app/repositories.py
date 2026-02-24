from datetime import datetime

from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import HiringSignal, Post, Run


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
