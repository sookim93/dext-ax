"""
APScheduler configuration for automated bidding notice synchronization.

Two sync jobs run every weekday at 09:00 and 15:00. Each sync fetches → filters
→ persists with lifecycle_state, auto-detects reposts via refNtceNo, and fires
a digest email of newly-inserted notices.

A separate EXPIRE job runs daily at 09:30 — flips notices to EXPIRED when their
bid_close_date passed > 24h ago AND they're still in an actionable state
(DISCOVERED / DECIDED_PARTICIPATE / REPOST_DETECTED). EXPIRED is loud-fail and
surfaces in the monitor view.

A 48h Slack escalation runs daily at 09:00 — preserved from earlier iteration,
will be superseded by Kakao push (Ticket #2 in TODOS.md) in a later cycle.
"""

import json
import logging
import os
from datetime import datetime, timedelta
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from sqlalchemy.orm import Session

from api_client import G2BAPIClient
from database import get_db_session
from filters import apply_filters
from models import LifecycleState, Notice
from notifier import (
    find_stale_notices,
    send_decision_digest,
    send_decision_reminder,
    send_executor_deadline_reminder,
    send_repost_alert,
    send_slack_escalation,
)

# Lifecycle states that EXPIRED should sweep — anything in an actionable state
# past the bid_close_date + EXPIRE_GRACE_HOURS. SUBMITTED is excluded because
# we've already done our part; AWARDED/LOST/DECIDED_PASS are terminal.
EXPIRABLE_STATES = (
    LifecycleState.DISCOVERED,
    LifecycleState.DECIDED_PARTICIPATE,
    LifecycleState.REPOST_DETECTED,
)
EXPIRE_GRACE_HOURS = 24

# States that show up in the digest email's 3 sections.
DIGEST_STATES = (
    LifecycleState.DISCOVERED,
    LifecycleState.DECIDED_PARTICIPATE,
    LifecycleState.REPOST_DETECTED,
)


def _notice_to_digest_dict(notice: Notice) -> dict:
    return {
        "id": notice.id,
        "bid_notice_no": notice.bid_notice_no,
        "bid_notice_name": notice.bid_notice_name,
        "institution_name": notice.institution_name,
        "bid_amount_min": notice.bid_amount_min,
        "bid_amount_max": notice.bid_amount_max,
        "bid_close_date": notice.bid_close_date,
        "notice_date": notice.notice_date,
        "url": notice.url,
        "lifecycle_state": notice.lifecycle_state.value if notice.lifecycle_state else "DISCOVERED",
        "ref_notice_no": notice.ref_notice_no,
    }


def _build_digest_sections(db) -> dict:
    """
    Legacy helper — kept for backwards-compat with /notify/test-email.
    Groups actionable notices by lifecycle_state. New code paths use
    _discovered_notices() instead.
    """
    sections = {state.value: [] for state in DIGEST_STATES}
    rows = (
        db.query(Notice)
        .filter(Notice.passes_filters == True)  # noqa: E712
        .filter(Notice.lifecycle_state.in_(DIGEST_STATES))
        .order_by(Notice.notice_date.desc())
        .all()
    )
    for n in rows:
        key = n.lifecycle_state.value if n.lifecycle_state else LifecycleState.DISCOVERED.value
        sections.setdefault(key, []).append(_notice_to_digest_dict(n))
    return sections


def _discovered_notices(db) -> list:
    """All DISCOVERED notices for the decision digest. 박이사 → [참여]/[불참]."""
    rows = (
        db.query(Notice)
        .filter(Notice.passes_filters == True)  # noqa: E712
        .filter(Notice.lifecycle_state == LifecycleState.DISCOVERED)
        .order_by(Notice.notice_date.desc())
        .all()
    )
    return [_notice_to_digest_dict(n) for n in rows]


def _business_hours_elapsed(start: datetime, end: datetime) -> float:
    """Hours between start and end, excluding entire Sat/Sun days.
    Used for '48h 무결정 (주말 제외)' reminder eligibility."""
    if end <= start:
        return 0.0
    total = 0.0
    current = start
    while current < end:
        next_midnight = (
            current.replace(hour=0, minute=0, second=0, microsecond=0)
            + timedelta(days=1)
        )
        slice_end = min(next_midnight, end)
        if current.weekday() < 5:  # Mon=0..Fri=4
            total += (slice_end - current).total_seconds() / 3600.0
        current = slice_end
    return total

# Where we persist the timestamp of the last successful sync. Used to set
# inqryBgnDt on the next call so we only fetch notices registered AFTER that
# moment — turning subsequent syncs from "130 pages" into "1-3 pages".
SYNC_STATE_FILE = "sync_state.json"

# Safety overlap: when reading state, rewind a bit so we don't miss notices
# registered in the seconds immediately around the last sync boundary.
OVERLAP_MINUTES = 5

# Per-sync configuration. Confirmed 2026-05-13 that PubDataOpnStdService
# ignores ALL server-side filter params we tried (ntceInsttNm, bidNtceNm,
# inqryBgnDt/inqryEndDt) — it returns a roughly fixed ~12K-row dataset
# regardless of inputs. So we instead cap pages aggressively:
#   • Bootstrap (no state yet) → walk up to MAX_PAGES_BOOTSTRAP for a full pull
#   • Incremental (state present) → only scan MAX_PAGES_INCREMENTAL = 5 pages
#     (= 500 most-recent rows). New bids land near the top, so this is enough
#     between scheduled cron runs and keeps each manual sync under ~10 seconds.
BOOTSTRAP_DAYS_BACK = 14  # client-side filters.py also drops >14d-old notices
ROWS_PER_PAGE = 100              # endpoint maximum
MAX_PAGES_BOOTSTRAP = 300        # full bootstrap cap
MAX_PAGES_INCREMENTAL = 5        # warm-mode cap


def _load_sync_state() -> dict:
    try:
        with open(SYNC_STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_sync_state(last_sync_at: datetime) -> None:
    try:
        with open(SYNC_STATE_FILE, "w", encoding="utf-8") as f:
            json.dump({"last_sync_at": last_sync_at.isoformat()}, f)
    except OSError as exc:
        logger.warning("Could not persist sync state: %s", exc)

logger = logging.getLogger(__name__)

# Global scheduler instance
_scheduler = None

# Weekday digest schedule (Mon–Fri). User decision 2026-05-14: two sends/day.
SYNC_SCHEDULE = [
    {"hour": 9, "minute": 0, "id": "sync_morning"},
    {"hour": 15, "minute": 0, "id": "sync_afternoon"},
]
# Daily EXPIRED sweep (after morning sync settled).
EXPIRE_HOUR = 9
EXPIRE_MINUTE = 30
# Reminder cron times (after morning sync + EXPIRE sweep settled).
DECISION_REMINDER_HOUR = 9      # 박이사 48h 무결정 reminder
DECISION_REMINDER_MINUTE = 45
DEADLINE_REMINDER_HOUR = 9      # D-3 / D-1 주니어 reminder
DEADLINE_REMINDER_MINUTE = 50

# Legacy Slack escalation (no longer scheduled — kept for backwards-compat call)
STALE_THRESHOLD_HOURS = 48


def sync_notices(db: Session = None) -> dict:
    """
    Synchronize bidding notices from G2B API.
    Fetches notices, applies filters, and stores passing notices in database.

    Args:
        db: Optional database session. If None, creates new session.

    Returns:
        Dict with sync statistics:
        {
            "fetched": int (total notices fetched from API),
            "filtered": int (notices that passed filters),
            "inserted": int (new notices inserted),
            "updated": int (existing notices updated),
            "errors": int (notices that failed to process)
        }
    """
    close_db = False
    if db is None:
        db = get_db_session()
        close_db = True

    try:
        stats = {
            "fetched": 0,
            "filtered": 0,
            "inserted": 0,
            "updated": 0,
            "errors": 0
        }
        new_notice_dicts: list = []  # populated for the digest email below
        new_repost_notices: list = []  # populated when REPOST_DETECTED on insert

        # Initialize API client
        try:
            client = G2BAPIClient()
        except ValueError as e:
            logger.error(f"Failed to initialize G2B API client: {str(e)}")
            return stats

        # State-based incremental: read the last successful sync timestamp and
        # use it as inqryBgnDt. Bootstrap path falls back to a 2-day window.
        sync_started_at = datetime.now()
        state = _load_sync_state()
        since_dt = None
        if state.get("last_sync_at"):
            try:
                last_at = datetime.fromisoformat(state["last_sync_at"])
                since_dt = last_at - timedelta(minutes=OVERLAP_MINUTES)
            except ValueError:
                since_dt = None

        if since_dt:
            max_pages = MAX_PAGES_INCREMENTAL
            logger.info(
                "Starting incremental sync (since %s, max_pages=%d)",
                since_dt.isoformat(timespec="minutes"), max_pages,
            )
        else:
            max_pages = MAX_PAGES_BOOTSTRAP
            logger.info(
                "Starting bootstrap sync (days_back=%d, max_pages=%d)",
                BOOTSTRAP_DAYS_BACK, max_pages,
            )

        seen_ids: set = set()
        notices: list = []

        for page in range(1, max_pages + 1):
            result = client.search_notices(
                keyword=None,
                institution_type=None,
                days_back=BOOTSTRAP_DAYS_BACK,
                since_dt=since_dt,
                page_no=page,
                num_of_rows=ROWS_PER_PAGE,
            )
            page_notices = (result or {}).get("notices", [])
            if not page_notices:
                logger.info("Pagination complete at page %d (empty page)", page)
                break
            for n in page_notices:
                nid = n.get("bid_notice_no")
                if nid and nid not in seen_ids:
                    seen_ids.add(nid)
                    notices.append(n)
            if len(page_notices) < ROWS_PER_PAGE:
                logger.info("Pagination complete at page %d (partial page)", page)
                break
        else:
            logger.info("Hit max_pages=%d cap (expected for incremental mode)", max_pages)

        stats["fetched"] = len(notices)
        logger.info(f"Fetched {stats['fetched']} unique notices from G2B API")

        # Process each notice
        for notice_data in notices:
            try:
                # Apply filters
                if not apply_filters(notice_data):
                    logger.debug(f"Notice {notice_data.get('bid_notice_no')} did not pass filters")
                    continue

                stats["filtered"] += 1
                logger.debug(f"Notice {notice_data.get('bid_notice_no')} passed filters")

                # Check if notice already exists
                existing_notice = db.query(Notice).filter(
                    Notice.bid_notice_no == notice_data.get("bid_notice_no")
                ).first()

                if existing_notice:
                    # Update mutable fields. Lifecycle state is intentionally
                    # NOT reset here — that's owned by user decisions and the
                    # EXPIRED sweep.
                    existing_notice.bid_notice_name = notice_data.get("bid_notice_name")
                    existing_notice.notice_status = notice_data.get("notice_status")
                    existing_notice.notice_date = notice_data.get("notice_date")
                    existing_notice.institution_name = notice_data.get("institution_name")
                    existing_notice.institution_type = notice_data.get("institution_type")
                    existing_notice.bid_amount_min = notice_data.get("bid_amount_min")
                    existing_notice.bid_amount_max = notice_data.get("bid_amount_max")
                    existing_notice.bid_close_date = notice_data.get("bid_close_date")
                    existing_notice.description = notice_data.get("description")
                    existing_notice.url = notice_data.get("url")
                    # Update ref_notice_no in case the API only published it later
                    if notice_data.get("ref_notice_no") and not existing_notice.ref_notice_no:
                        existing_notice.ref_notice_no = notice_data.get("ref_notice_no")
                    existing_notice.passes_filters = True
                    existing_notice.updated_at = datetime.utcnow()
                    stats["updated"] += 1
                    logger.debug(f"Updated notice {notice_data.get('bid_notice_no')}")
                else:
                    # Create new notice. Determine lifecycle_state based on
                    # whether this is a repost of an existing tracked notice.
                    ref_no = notice_data.get("ref_notice_no")
                    initial_state = LifecycleState.DISCOVERED
                    if ref_no:
                        original = db.query(Notice).filter(
                            Notice.bid_notice_no == ref_no
                        ).first()
                        if original is not None and original.lifecycle_state in (
                            LifecycleState.DECIDED_PARTICIPATE,
                            LifecycleState.SUBMITTED,
                        ):
                            # Original we've actually engaged with; this is the
                            # repost path we need to surface loudly.
                            initial_state = LifecycleState.REPOST_DETECTED
                        # else: original is None / DECIDED_PASS / AWARDED / LOST
                        # → treat the repost as plain DISCOVERED (no repost UX)
                    new_notice = Notice(
                        bid_notice_no=notice_data.get("bid_notice_no"),
                        bid_notice_name=notice_data.get("bid_notice_name"),
                        notice_status=notice_data.get("notice_status"),
                        notice_date=notice_data.get("notice_date"),
                        institution_name=notice_data.get("institution_name"),
                        institution_type=notice_data.get("institution_type"),
                        bid_amount_min=notice_data.get("bid_amount_min"),
                        bid_amount_max=notice_data.get("bid_amount_max"),
                        bid_close_date=notice_data.get("bid_close_date"),
                        description=notice_data.get("description"),
                        url=notice_data.get("url"),
                        ref_notice_no=ref_no,
                        lifecycle_state=initial_state,
                        passes_filters=True,
                    )
                    db.add(new_notice)
                    stats["inserted"] += 1
                    new_notice_dicts.append({**notice_data, "lifecycle_state": initial_state})
                    if initial_state == LifecycleState.REPOST_DETECTED:
                        new_repost_notices.append(new_notice)
                    logger.debug(
                        "Inserted notice %s as %s (ref=%s)",
                        notice_data.get('bid_notice_no'), initial_state, ref_no,
                    )

            except Exception as e:
                logger.error(f"Error processing notice {notice_data.get('bid_notice_no')}: {str(e)}")
                stats["errors"] += 1

        # Commit all changes
        db.commit()
        logger.info(
            f"Synchronization complete. Fetched: {stats['fetched']}, "
            f"Filtered: {stats['filtered']}, "
            f"Inserted: {stats['inserted']}, "
            f"Updated: {stats['updated']}, "
            f"Errors: {stats['errors']}"
        )

        # Persist the start-of-sync timestamp so the next run can use it as
        # inqryBgnDt. Use start time (not end) so any notices registered
        # mid-sync are picked up on the next run.
        _save_sync_state(sync_started_at)

        # 1) 박이사 다이제스트 — DISCOVERED 신규 공고만. 매 sync마다 발송 (결정될 때까지 reminder 역할).
        discovered = _discovered_notices(db)
        if discovered:
            try:
                send_decision_digest(discovered)
            except Exception:
                logger.exception("send_decision_digest failed (non-fatal)")

        # 2) 재공고 즉시 알림 — 박이사 + 주니어 모두에게 (commit 후 단건씩)
        for notice in new_repost_notices:
            try:
                send_repost_alert(notice)
            except Exception:
                logger.exception(
                    "send_repost_alert failed (non-fatal) for %s",
                    notice.bid_notice_no,
                )

        return stats

    except Exception as e:
        logger.error(f"Unexpected error during synchronization: {str(e)}")
        return stats
    finally:
        if close_db:
            db.close()


def expire_stale_notices() -> dict:
    """
    Sweep notices whose bid_close_date passed > EXPIRE_GRACE_HOURS ago and are
    still in an actionable state (DISCOVERED / DECIDED_PARTICIPATE /
    REPOST_DETECTED). Flip them to EXPIRED. This is the loud-fail signal that
    surfaces in the monitor's "마감 누락" section.
    """
    db = get_db_session()
    result = {"swept": 0, "expired": 0}
    try:
        cutoff = datetime.utcnow() - timedelta(hours=EXPIRE_GRACE_HOURS)
        candidates = (
            db.query(Notice)
            .filter(Notice.bid_close_date.isnot(None))
            .filter(Notice.bid_close_date <= cutoff)
            .filter(Notice.lifecycle_state.in_(EXPIRABLE_STATES))
            .all()
        )
        result["swept"] = len(candidates)
        for n in candidates:
            n.lifecycle_state = LifecycleState.EXPIRED
            result["expired"] += 1
        db.commit()
        logger.info(
            "EXPIRE sweep: scanned %d, expired %d",
            result["swept"], result["expired"],
        )
        return result
    finally:
        db.close()


def escalate_stale_notices() -> dict:
    """Legacy Slack stale-notice escalation. Kept for backwards-compat but no
    longer scheduled — replaced by ``send_decision_reminders_48h``."""
    db = get_db_session()
    result = {"stale_count": 0, "slack_sent": False}
    try:
        stale = find_stale_notices(db, threshold_hours=STALE_THRESHOLD_HOURS)
        result["stale_count"] = len(stale)
        if stale:
            result["slack_sent"] = send_slack_escalation(stale)
        return result
    finally:
        db.close()


# ---------------------------------------------------------------------
# Reminder cron jobs (UX 잠금 결과 — 2026-05-14)
# ---------------------------------------------------------------------

def send_decision_reminders_48h() -> dict:
    """
    DISCOVERED 상태로 영업일 기준 48시간 이상 결정 안 된 공고를 골라
    박이사에게 reminder 메일. Notice.decision_reminder_sent_at으로 dedup.
    """
    db = get_db_session()
    result = {"checked": 0, "sent": 0}
    try:
        now = datetime.utcnow()
        candidates = (
            db.query(Notice)
            .filter(Notice.passes_filters == True)  # noqa: E712
            .filter(Notice.lifecycle_state == LifecycleState.DISCOVERED)
            .filter(Notice.decision_reminder_sent_at.is_(None))
            .all()
        )
        result["checked"] = len(candidates)
        eligible = [
            n for n in candidates
            if n.created_at and _business_hours_elapsed(n.created_at, now) >= 48
        ]
        if not eligible:
            logger.info("Decision reminder: 0/%d eligible (none >48 business hours)", result["checked"])
            return result
        payload = [_notice_to_digest_dict(n) for n in eligible]
        ok = send_decision_reminder(payload)
        if ok:
            for n in eligible:
                n.decision_reminder_sent_at = now
            db.commit()
            result["sent"] = len(eligible)
        logger.info(
            "Decision reminder: %d/%d eligible, sent=%s",
            len(eligible), result["checked"], ok,
        )
        return result
    finally:
        db.close()


def send_deadline_reminders() -> dict:
    """
    DECIDED_PARTICIPATE 상태에서 bid_close_date가 임박한 공고를 골라 reminder.
    D-3 (2.5-3.5 days remaining): 주니어
    D-1 (0-1.5 days remaining):    주니어 + 박이사 cc
    Notice.deadline_d3_sent_at / deadline_d1_sent_at으로 dedup.
    """
    db = get_db_session()
    result = {"d3_sent": 0, "d1_sent": 0}
    try:
        now = datetime.utcnow()
        actionable = (
            db.query(Notice)
            .filter(Notice.passes_filters == True)  # noqa: E712
            .filter(Notice.lifecycle_state == LifecycleState.DECIDED_PARTICIPATE)
            .filter(Notice.bid_close_date.isnot(None))
            .all()
        )
        d3_batch = []
        d1_batch = []
        for n in actionable:
            days = (n.bid_close_date - now).total_seconds() / 86400.0
            if 2.5 <= days < 3.5 and n.deadline_d3_sent_at is None:
                d3_batch.append(n)
            elif 0 <= days < 1.5 and n.deadline_d1_sent_at is None:
                d1_batch.append(n)
        if d3_batch:
            payload = [_notice_to_digest_dict(n) for n in d3_batch]
            if send_executor_deadline_reminder(payload, dday=3):
                for n in d3_batch:
                    n.deadline_d3_sent_at = now
                result["d3_sent"] = len(d3_batch)
        if d1_batch:
            payload = [_notice_to_digest_dict(n) for n in d1_batch]
            if send_executor_deadline_reminder(payload, dday=1):
                for n in d1_batch:
                    n.deadline_d1_sent_at = now
                result["d1_sent"] = len(d1_batch)
        if result["d3_sent"] or result["d1_sent"]:
            db.commit()
        logger.info(
            "Deadline reminders: D-3 sent=%d, D-1 sent=%d (scanned %d actionable)",
            result["d3_sent"], result["d1_sent"], len(actionable),
        )
        return result
    finally:
        db.close()


def start_scheduler(enabled: bool = True) -> None:
    """
    Start the background scheduler.

    Args:
        enabled: Whether to enable the scheduler (can be disabled via env var)
    """
    global _scheduler

    if _scheduler is not None and _scheduler.running:
        logger.warning("Scheduler already running")
        return

    # max_instances=1 + coalesce=True so a slow sync can't overlap with a
    # manual /sync invocation, and missed runs collapse to a single execution.
    _scheduler = BackgroundScheduler(
        job_defaults={"max_instances": 1, "coalesce": True, "misfire_grace_time": 300},
    )

    if enabled:
        # Three weekday sync jobs — each one fetches, filters, persists, and
        # fires off a digest email with any newly-inserted notices.
        for slot in SYNC_SCHEDULE:
            _scheduler.add_job(
                sync_notices,
                trigger=CronTrigger(
                    day_of_week="mon-fri",
                    hour=slot["hour"],
                    minute=slot["minute"],
                ),
                id=slot["id"],
                name=f"G2B sync @ {slot['hour']:02d}:{slot['minute']:02d}",
                replace_existing=True,
            )
            logger.info(
                "Scheduled %s at %02d:%02d (Mon-Fri)",
                slot["id"], slot["hour"], slot["minute"],
            )

        # Daily EXPIRED sweep (auto-flip stale actionable notices).
        _scheduler.add_job(
            expire_stale_notices,
            trigger=CronTrigger(hour=EXPIRE_HOUR, minute=EXPIRE_MINUTE),
            id="expire_stale_sweep",
            name=f"EXPIRED sweep @ {EXPIRE_HOUR:02d}:{EXPIRE_MINUTE:02d}",
            replace_existing=True,
        )
        logger.info(
            "Scheduled EXPIRED sweep at %02d:%02d daily",
            EXPIRE_HOUR, EXPIRE_MINUTE,
        )

        # 박이사 48h 무결정 reminder (영업일 기준, 평일만).
        _scheduler.add_job(
            send_decision_reminders_48h,
            trigger=CronTrigger(
                day_of_week="mon-fri",
                hour=DECISION_REMINDER_HOUR,
                minute=DECISION_REMINDER_MINUTE,
            ),
            id="decision_reminder_48h",
            name=f"Decision reminder (48 business hours) @ {DECISION_REMINDER_HOUR:02d}:{DECISION_REMINDER_MINUTE:02d}",
            replace_existing=True,
        )
        logger.info(
            "Scheduled 48h decision reminder at %02d:%02d (Mon-Fri)",
            DECISION_REMINDER_HOUR, DECISION_REMINDER_MINUTE,
        )

        # 주니어 D-3 / D-1 마감 임박 reminder (매일 — 마감은 주말도 다가옴).
        _scheduler.add_job(
            send_deadline_reminders,
            trigger=CronTrigger(
                hour=DEADLINE_REMINDER_HOUR,
                minute=DEADLINE_REMINDER_MINUTE,
            ),
            id="deadline_reminders",
            name=f"Deadline reminders (D-3 / D-1) @ {DEADLINE_REMINDER_HOUR:02d}:{DEADLINE_REMINDER_MINUTE:02d}",
            replace_existing=True,
        )
        logger.info(
            "Scheduled D-3/D-1 deadline reminders at %02d:%02d daily",
            DEADLINE_REMINDER_HOUR, DEADLINE_REMINDER_MINUTE,
        )
    else:
        logger.info("Scheduler is disabled (CRON_ENABLED=false)")

    _scheduler.start()
    logger.info("Background scheduler started")


def stop_scheduler() -> None:
    """Stop the background scheduler."""
    global _scheduler

    if _scheduler is None:
        logger.warning("Scheduler not initialized")
        return

    if _scheduler.running:
        _scheduler.shutdown(wait=True)
        logger.info("Background scheduler stopped")
    else:
        logger.warning("Scheduler is not running")


def get_scheduler():
    """Get the global scheduler instance."""
    return _scheduler


def trigger_sync_now() -> dict:
    """
    Manually trigger a notice synchronization (used by POST /api/sync endpoint).

    Returns:
        Dict with sync statistics
    """
    logger.info("Manual sync triggered via API")
    return sync_notices()
