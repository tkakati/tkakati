import csv
from datetime import UTC, datetime, timedelta
from io import StringIO

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.auth.clerk import require_auth
from app.collector.service import CollectorService
from app.config import Settings, get_settings
from app.db import get_db
from app.repositories import PostRepository, RunRepository
from app.schemas import (
    ALLOWED_STATUSES,
    CollectorRunRequest,
    CollectorRunResponse,
    PaginatedPosts,
    PostOut,
    PostStatusUpdate,
    RunOut,
)

router = APIRouter()


@router.get("/posts", response_model=PaginatedPosts, tags=["posts"])
def list_posts(
    company: str | None = Query(default=None),
    title: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaginatedPosts:
    now = datetime.now(tz=UTC)
    effective_date_to = date_to or now
    effective_date_from = date_from or (now - timedelta(days=settings.collector_days_back))
    size = min(page_size or settings.default_page_size, settings.max_page_size)
    repo = PostRepository(db)
    items, total = repo.list_posts(
        company=company,
        title=title,
        date_from=effective_date_from,
        date_to=effective_date_to,
        page=page,
        page_size=size,
    )
    return PaginatedPosts(
        items=[PostOut.model_validate(item, from_attributes=True) for item in items],
        page=page,
        page_size=size,
        total=total,
    )


@router.post("/collector/run", response_model=CollectorRunResponse, tags=["collector"])
def run_collector(
    body: CollectorRunRequest | None = None,
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> CollectorRunResponse:
    payload = body or CollectorRunRequest()
    last_days = payload.last_days if payload.last_days and payload.last_days > 0 else None
    result = CollectorService(db, settings).run_once(
        designations=payload.designations,
        locations=payload.locations,
        last_days=last_days,
    )
    return CollectorRunResponse(
        run_id=result.run_id,
        status=result.status,
        inserted=result.inserted,
        skipped=result.skipped,
        error=result.error,
    )


@router.post("/collector/debug-source", tags=["collector"])
def debug_collector_source(
    body: CollectorRunRequest | None = None,
    limit: int = Query(default=50, ge=1, le=300),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    payload = body or CollectorRunRequest()
    last_days = payload.last_days if payload.last_days and payload.last_days > 0 else None
    return CollectorService(db, settings).debug_source(
        designations=payload.designations,
        locations=payload.locations,
        last_days=last_days,
        limit=limit,
    )


@router.post("/collector/refresh-companies", tags=["collector"])
def refresh_companies(
    limit: int = Query(default=500, ge=1, le=5000),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict[str, int]:
    scanned, updated = CollectorService(db, settings).refresh_companies(limit=limit)
    return {"scanned": scanned, "updated": updated}


@router.get("/runs", response_model=list[RunOut], tags=["runs"])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    runs = RunRepository(db).list_runs(limit=limit)
    return [RunOut.model_validate(run, from_attributes=True) for run in runs]


@router.get("/export.csv", tags=["posts"])
def export_csv(
    company: str | None = Query(default=None),
    title: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> StreamingResponse:
    now = datetime.now(tz=UTC)
    effective_date_to = date_to or now
    effective_date_from = date_from or (now - timedelta(days=7))
    rows = PostRepository(db).list_for_export(
        company=company,
        title=title,
        date_from=effective_date_from,
        date_to=effective_date_to,
    )

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(
        [
            "post_url",
            "title",
            "company",
            "seniority",
            "location",
            "remote",
            "query_used",
            "status",
            "first_seen",
            "created_at",
        ]
    )
    for row in rows:
        writer.writerow(
            [
                row.post_url,
                row.title,
                row.company or "",
                row.seniority or "",
                row.location or "",
                str(row.remote).lower(),
                row.query_used,
                row.status,
                row.first_seen.isoformat(),
                row.created_at.isoformat(),
            ]
        )
    output.seek(0)

    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=posts.csv"},
    )


@router.patch("/posts/{post_id}/status", response_model=PostOut, tags=["posts"])
def update_post_status(
    post_id: int,
    body: PostStatusUpdate,
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> PostOut:
    normalized = body.status.strip().lower()
    if normalized not in ALLOWED_STATUSES:
        raise HTTPException(status_code=400, detail="Invalid status value")

    post = PostRepository(db).update_status(post_id, normalized)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    return PostOut.model_validate(post, from_attributes=True)
