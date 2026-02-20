from datetime import datetime

from pydantic import BaseModel, HttpUrl

ALLOWED_STATUSES = ("no action", "reached out", "responded", "chatted", "referred")


class PostOut(BaseModel):
    id: int
    post_url: HttpUrl
    title: str
    company: str | None
    seniority: str | None
    location: str | None
    remote: bool
    query_used: str
    status: str
    first_seen: datetime
    created_at: datetime


class RunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    inserted: int
    skipped: int
    error: str | None


class PaginatedPosts(BaseModel):
    items: list[PostOut]
    page: int
    page_size: int
    total: int


class CollectorRunResponse(BaseModel):
    run_id: int
    status: str
    inserted: int
    skipped: int
    error: str | None


class PostStatusUpdate(BaseModel):
    status: str
