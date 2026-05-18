"""
SQLAlchemy ORM models for bidding notices and decisions.

Lifecycle state machine:
    DISCOVERED → DECIDED_PARTICIPATE → SUBMITTED → REPOST_DETECTED → RESUBMITTED → AWARDED/LOST
              ↘ DECIDED_PASS (terminal)
    EXPIRED (auto, if bid_close_date + 24h passes without resolution)
"""

from __future__ import annotations

import enum
from datetime import datetime
from sqlalchemy import Column, Integer, String, Float, DateTime, Boolean, ForeignKey, Text
from sqlalchemy import Enum as SAEnum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship

Base = declarative_base()


class LifecycleState(str, enum.Enum):
    """Stages a bid notice passes through. Stored as string in DB."""
    DISCOVERED = "DISCOVERED"                    # sync 발견, 결정 대기
    DECIDED_PASS = "DECIDED_PASS"                # 박이사 [패스] (terminal)
    DECIDED_PARTICIPATE = "DECIDED_PARTICIPATE"  # 박이사 [참여], 실행자 처리 시작
    SUBMITTED = "SUBMITTED"                      # 실행자 [제출완료], 결과 대기
    REPOST_DETECTED = "REPOST_DETECTED"          # 재공고 자동 감지 (refNtceNo 매칭)
    RESUBMITTED = "RESUBMITTED"                  # 실행자 [재제출 완료]
    AWARDED = "AWARDED"                          # 낙찰 (수동 입력 또는 Ticket #1 자동)
    LOST = "LOST"                                # 패찰 (수동 또는 자동)
    EXPIRED = "EXPIRED"                          # 마감 + 24h 후 미처리 (자동)


class TransitionType(str, enum.Enum):
    """Action embedded in the decision token URL."""
    PARTICIPATE = "participate"
    PASS = "pass"
    SUBMITTED = "submitted"
    RESUBMITTED = "resubmitted"


class Notice(Base):
    """Bid notice — one row per unique bidNtceNo."""
    __tablename__ = "notices"

    id = Column(Integer, primary_key=True, index=True)
    bid_notice_no = Column(String(255), unique=True, index=True)
    bid_notice_name = Column(String(512))
    notice_status = Column(String(100))
    notice_date = Column(DateTime)
    institution_name = Column(String(255))
    institution_type = Column(String(100))
    bid_amount_min = Column(Float, nullable=True)
    bid_amount_max = Column(Float, nullable=True)
    description = Column(Text, nullable=True)
    url = Column(String(1024), nullable=True)
    bid_close_date = Column(DateTime, nullable=True)

    # New (lifecycle governance)
    lifecycle_state = Column(
        SAEnum(LifecycleState, native_enum=False, length=32),
        default=LifecycleState.DISCOVERED,
        nullable=False,
        index=True,
    )
    # If this is a repost, the bidNtceNo of the original notice.
    # Stored as plain string (not FK) — original may not exist in our DB
    # (e.g. filter changed, or original predates our first sync).
    ref_notice_no = Column(String(255), nullable=True, index=True)

    passes_filters = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Reminder dedup timestamps. NULL = not sent yet. Set the moment the
    # corresponding reminder mail is fired; cron checks NULL before sending.
    decision_reminder_sent_at = Column(DateTime, nullable=True)  # 박이사 48h 무결정
    deadline_d3_sent_at = Column(DateTime, nullable=True)        # 주니어 D-3 마감 임박
    deadline_d1_sent_at = Column(DateTime, nullable=True)        # 주니어+박이사 D-1 마감 임박

    decisions = relationship("Decision", back_populates="notice", cascade="all, delete-orphan")

    def __repr__(self):
        return (
            f"<Notice(id={self.id}, no={self.bid_notice_no}, "
            f"state={self.lifecycle_state})>"
        )


class Decision(Base):
    """
    One row per emitted decision token. The token is unique and single-use:
    on first click ``used_at`` is set, subsequent clicks return "already done."
    """
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True, index=True)
    notice_id = Column(Integer, ForeignKey("notices.id"), index=True)
    transition_type = Column(
        SAEnum(TransitionType, native_enum=False, length=32),
        nullable=False,
    )
    token = Column(String(255), unique=True, index=True, nullable=False)
    decided_by = Column(String(255), nullable=True)
    decided_at = Column(DateTime, default=datetime.utcnow)
    used_at = Column(DateTime, nullable=True)

    notice = relationship("Notice", back_populates="decisions")

    def __repr__(self):
        return (
            f"<Decision(id={self.id}, notice_id={self.notice_id}, "
            f"transition={self.transition_type}, used={self.used_at is not None})>"
        )
