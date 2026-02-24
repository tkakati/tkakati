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


class CollectorRunRequest(BaseModel):
    designations: list[str] | None = None
    locations: list[str] | None = None
    last_days: int | None = None


class PostStatusUpdate(BaseModel):
    status: str


class SignalOut(BaseModel):
    id: int
    company: str | None
    role: str | None
    seniority: str | None
    is_hiring: bool
    signal_strength: int
    signal_type: str
    confidence: float
    company_source: str
    company_confidence: float
    hiring_confidence: float
    role_match_score: float
    reasoning: str | None
    review_status: str
    review_label: str | None
    source_url: HttpUrl
    timestamp: datetime


class PaginatedSignals(BaseModel):
    items: list[SignalOut]
    page: int
    page_size: int
    total: int
    total_base: int


class SignalFeedbackIn(BaseModel):
    action: str
    label: str | None = None
    notes: str | None = None


class SignalMetricsOut(BaseModel):
    strong_signals: int
    medium_confidence: int
    filtered: int
    common_filter_reasons: list[dict]
    false_positive_trends: list[dict]
    emerging_companies: list[dict]
    hidden_hiring_clusters: list[dict]
