from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (UniqueConstraint("post_url", name="uq_posts_post_url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    post_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    title: Mapped[str] = mapped_column(String(512), nullable=False)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(120), nullable=True)
    location: Mapped[str | None] = mapped_column(String(120), nullable=True)
    remote: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    query_used: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="no action", server_default="no action")
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(50), nullable=False)
    inserted: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class HiringSignal(Base):
    __tablename__ = "hiring_signals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    company: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)
    role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    seniority: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_hiring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    signal_strength: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    signal_type: Mapped[str] = mapped_column(String(20), nullable=False, default="noise", server_default="noise")
    confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    company_source: Mapped[str] = mapped_column(String(20), nullable=False, default="llm", server_default="llm")
    company_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    hiring_confidence: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    role_match_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0, server_default="0")
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    review_label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )


class SignalFeedback(Base):
    __tablename__ = "signal_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    signal_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(20), nullable=False)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, server_default=func.now()
    )
