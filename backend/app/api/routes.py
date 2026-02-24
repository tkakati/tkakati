import asyncio
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
from app.repositories import HiringSignalRepository, PostRepository, RunRepository
from app.schemas import (
    ALLOWED_STATUSES,
    CollectorRunRequest,
    CollectorRunResponse,
    PaginatedPosts,
    PaginatedSignals,
    PostOut,
    PostStatusUpdate,
    RunOut,
    SignalFeedbackIn,
    SignalMetricsOut,
    SignalOut,
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


@router.post("/preview-signals", tags=["collector"])
async def preview_signals(
    body: CollectorRunRequest | None = None,
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> dict:
    payload = body or CollectorRunRequest()
    last_days = payload.last_days if payload.last_days and payload.last_days > 0 else None
    service = CollectorService(db, settings)
    return await asyncio.to_thread(
        service.preview_signals,
        designations=payload.designations,
        locations=payload.locations,
        last_days=last_days,
    )


@router.get("/runs", response_model=list[RunOut], tags=["runs"])
def list_runs(
    limit: int = Query(default=50, ge=1, le=200),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[RunOut]:
    runs = RunRepository(db).list_runs(limit=limit)
    return [RunOut.model_validate(run, from_attributes=True) for run in runs]


@router.get("/signals", response_model=PaginatedSignals, tags=["signals"])
def list_signals(
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    hiring_strictness: str = Query(default="medium"),
    role_similarity_threshold: float = Query(default=0.0, ge=0.0, le=1.0),
    review_status: str | None = Query(default=None),
    last_days: int | None = Query(default=30, ge=1, le=365),
    page: int = Query(default=1, ge=1),
    page_size: int | None = Query(default=None, ge=1),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> PaginatedSignals:
    strictness = _normalize_strictness(hiring_strictness)
    size = min(page_size or settings.default_page_size, settings.max_page_size)
    repo = HiringSignalRepository(db)
    items, total, total_base = repo.list_signals(
        min_confidence=min_confidence,
        hiring_strictness=strictness,
        role_similarity_threshold=role_similarity_threshold,
        page=page,
        page_size=size,
        review_status=review_status,
        days_back=last_days,
    )
    return PaginatedSignals(
        items=[SignalOut.model_validate(item, from_attributes=True) for item in items],
        page=page,
        page_size=size,
        total=total,
        total_base=total_base,
    )


@router.get("/signals/review-queue", response_model=list[SignalOut], tags=["signals"])
def review_queue(
    limit: int = Query(default=100, ge=1, le=500),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> list[SignalOut]:
    items = HiringSignalRepository(db).list_review_queue(limit=limit)
    return [SignalOut.model_validate(item, from_attributes=True) for item in items]


@router.patch("/signals/{signal_id}/review", response_model=SignalOut, tags=["signals"])
def review_signal(
    signal_id: int,
    body: SignalFeedbackIn,
    claims: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SignalOut:
    action = body.action.strip().lower()
    if action not in {"approve", "reject", "relabel"}:
        raise HTTPException(status_code=400, detail="Invalid action")
    signal = HiringSignalRepository(db).update_review(
        signal_id=signal_id,
        action=action,
        label=body.label,
        notes=body.notes,
        reviewer_id=str(claims.get("sub") or ""),
    )
    if signal is None:
        raise HTTPException(status_code=404, detail="Signal not found")
    return SignalOut.model_validate(signal, from_attributes=True)


@router.get("/signals/analytics", response_model=SignalMetricsOut, tags=["signals"])
def signals_analytics(
    min_confidence: float = Query(default=0.0, ge=0.0, le=1.0),
    hiring_strictness: str = Query(default="medium"),
    role_similarity_threshold: float = Query(default=0.0, ge=0.0, le=1.0),
    last_days: int | None = Query(default=30, ge=1, le=365),
    _: dict = Depends(require_auth),
    db: Session = Depends(get_db),
) -> SignalMetricsOut:
    strictness = _normalize_strictness(hiring_strictness)
    repo = HiringSignalRepository(db)
    items, total, total_base = repo.list_signals(
        min_confidence=min_confidence,
        hiring_strictness=strictness,
        role_similarity_threshold=role_similarity_threshold,
        page=1,
        page_size=1000,
        days_back=last_days,
    )
    strong_signals = sum(1 for item in items if item.signal_strength >= 4)
    medium_confidence = sum(1 for item in items if 0.5 <= item.confidence < 0.75)
    filtered = max(0, total_base - total)

    return SignalMetricsOut(
        strong_signals=strong_signals,
        medium_confidence=medium_confidence,
        filtered=filtered,
        common_filter_reasons=repo.filter_reason_counts(
            min_confidence=min_confidence,
            hiring_strictness=strictness,
            role_similarity_threshold=role_similarity_threshold,
            days_back=last_days,
        ),
        false_positive_trends=repo.false_positive_trends(days=14),
        emerging_companies=repo.emerging_companies(days=14, limit=10),
        hidden_hiring_clusters=repo.hidden_hiring_clusters(days=30, limit=10),
    )


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


def _normalize_strictness(value: str) -> str:
    lowered = value.strip().lower()
    if lowered not in {"low", "medium", "high"}:
        return "medium"
    return lowered
