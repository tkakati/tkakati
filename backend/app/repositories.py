from datetime import datetime

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Post, Run


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

    def list_for_company_refresh(self, *, limit: int) -> list[Post]:
        unknown = func.lower(func.coalesce(Post.company, "")) == "unknown"
        empty_company = func.length(func.trim(func.coalesce(Post.company, ""))) == 0
        empty_seniority = func.length(func.trim(func.coalesce(Post.seniority, ""))) == 0
        empty_location = func.length(func.trim(func.coalesce(Post.location, ""))) == 0
        query = (
            select(Post)
            .where(or_(unknown, empty_company, empty_seniority, empty_location))
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
