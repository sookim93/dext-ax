"""
FastAPI web application for bidding notice dashboard.

Lifecycle governance: notices move through DISCOVERED → DECIDED_* →
SUBMITTED → (optional) REPOST_DETECTED → RESUBMITTED → AWARDED/LOST,
with EXPIRED as the terminal failure state. State transitions happen via
one-click links embedded in digest emails. Each link is a single-use,
expiring token bound to (notice_id, transition).
"""

import logging
import os
import threading
from collections import defaultdict
from datetime import datetime
from typing import Optional

# Load .env BEFORE any module that calls os.getenv at import time
# (api_client/scheduler/notifier all read env on init).
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from database import engine, get_db_session, init_db
from models import Base, Notice, Decision, LifecycleState, TransitionType
from notifier import (
    find_stale_notices,
    send_decision_digest,
    send_decision_reminder,
    send_executor_confirmation,
    send_executor_deadline_reminder,
    send_digest_email,
    send_repost_alert,
    send_slack_escalation,
)
from scheduler import (
    escalate_stale_notices,
    expire_stale_notices,
    send_decision_reminders_48h,
    send_deadline_reminders,
    start_scheduler,
    stop_scheduler,
    trigger_sync_now,
)
from tokens import make_decision_token, verify_decision_token

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Bidding Notice Dashboard", version="2.0.0")
templates = Jinja2Templates(directory="templates")

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

# ---------------------------------------------------------------------
# Lifecycle transitions — what's allowed from each state
# ---------------------------------------------------------------------

ALLOWED_TRANSITIONS = {
    TransitionType.PARTICIPATE: ({LifecycleState.DISCOVERED}, LifecycleState.DECIDED_PARTICIPATE),
    TransitionType.PASS: ({LifecycleState.DISCOVERED}, LifecycleState.DECIDED_PASS),
    TransitionType.SUBMITTED: ({LifecycleState.DECIDED_PARTICIPATE}, LifecycleState.SUBMITTED),
    TransitionType.RESUBMITTED: ({LifecycleState.REPOST_DETECTED}, LifecycleState.RESUBMITTED),
}


def get_db():
    """Yield a db session for FastAPI route handlers."""
    session = get_db_session()
    try:
        yield session
    finally:
        session.close()


# ---------------------------------------------------------------------
# Monitor view (사용자 본인 dashboard) — lifecycle-grouped
# ---------------------------------------------------------------------

LIFECYCLE_SECTIONS = [
    # (state, label, group, tier) — tier governs visual weight + default-open
    ("DISCOVERED",            "🆕 미결정",          "신규",     "active"),
    ("DECIDED_PARTICIPATE",   "⏳ 결정완료, 처리 중", "결정완료", "active"),
    ("REPOST_DETECTED",       "🔁 재공고 추적",      "재공고",   "active"),
    ("EXPIRED",               "⚠️  마감 누락",       "fail-loud", "fail"),
    ("SUBMITTED",             "✅ 제출 완료",        "제출",     "terminal"),
    ("RESUBMITTED",           "↩️  재제출 완료",     "재제출",   "terminal"),
    ("AWARDED",               "🏆 낙찰",            "결과",     "terminal"),
    ("LOST",                  "❌ 패찰",            "결과",     "terminal"),
    ("DECIDED_PASS",          "🚫 불참",            "기록",     "terminal"),
]

# Undo mapping — user-initiated lifecycle states only. System-set states
# (REPOST_DETECTED / EXPIRED / AWARDED / LOST) are not undoable here.
UNDO_TARGET = {
    LifecycleState.DECIDED_PASS: LifecycleState.DISCOVERED,
    LifecycleState.DECIDED_PARTICIPATE: LifecycleState.DISCOVERED,
    LifecycleState.SUBMITTED: LifecycleState.DECIDED_PARTICIPATE,
    LifecycleState.RESUBMITTED: LifecycleState.REPOST_DETECTED,
}
UNDO_TARGET_VALUES = {k.value: v.value for k, v in UNDO_TARGET.items()}


def _next_sync_time() -> str:
    """다음 sync 시각 (09:00 / 15:00 Mon-Fri) — 헤로 표시용."""
    from datetime import timedelta
    now = datetime.now()
    morning = now.replace(hour=9, minute=0, second=0, microsecond=0)
    afternoon = now.replace(hour=15, minute=0, second=0, microsecond=0)
    if now.weekday() < 5:
        if now < morning:
            return morning.strftime("%m/%d %H:%M")
        if now < afternoon:
            return afternoon.strftime("%m/%d %H:%M")
    nxt = now + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    nxt = nxt.replace(hour=9, minute=0, second=0, microsecond=0)
    return nxt.strftime("%m/%d %H:%M")


@app.get("/", response_class=HTMLResponse)
def dashboard(db: Session = Depends(get_db)):
    """Monitor view — lifecycle별 grouping + hero stats."""
    try:
        notices = (
            db.query(Notice)
            .filter(Notice.passes_filters == True)  # noqa: E712
            .order_by(Notice.notice_date.desc())
            .all()
        )

        now = datetime.utcnow()
        groups = defaultdict(list)
        all_data = []
        for notice in notices:
            days_left = None
            if notice.bid_close_date:
                days_left = (notice.bid_close_date - now).days

            state_val = notice.lifecycle_state.value if notice.lifecycle_state else "DISCOVERED"
            d = {
                "id": notice.id,
                "bid_notice_no": notice.bid_notice_no,
                "bid_notice_name": notice.bid_notice_name,
                "institution_name": notice.institution_name,
                "bid_amount_min": notice.bid_amount_min or 0,
                "bid_amount_max": notice.bid_amount_max or 0,
                "notice_date": notice.notice_date,
                "bid_close_date": notice.bid_close_date,
                "days_left": days_left,
                "notice_status": notice.notice_status,
                "lifecycle_state": state_val,
                "ref_notice_no": notice.ref_notice_no,
                "url": notice.url,
                # Tokens for each valid action from current state
                "tokens": _action_tokens_for(notice),
                # Undo support — user-initiated decisions can be rolled back
                "can_undo": state_val in UNDO_TARGET_VALUES,
                "undo_target": UNDO_TARGET_VALUES.get(state_val),
            }
            all_data.append(d)
            groups[d["lifecycle_state"]].append(d)

        # Hero stats — based on all notices
        stats = {
            "total": len(all_data),
            "dday": sum(1 for n in all_data if n["days_left"] == 0 and n["lifecycle_state"] in ("DISCOVERED", "DECIDED_PARTICIPATE", "REPOST_DETECTED")),
            "urgent": sum(1 for n in all_data if n["days_left"] is not None and 0 <= n["days_left"] <= 3 and n["lifecycle_state"] in ("DISCOVERED", "DECIDED_PARTICIPATE", "REPOST_DETECTED")),
            "pending": sum(1 for n in all_data if n["lifecycle_state"] == "DISCOVERED"),
            "expired": sum(1 for n in all_data if n["lifecycle_state"] == "EXPIRED"),
        }

        # Build ordered sections list for the template. Note: key is `notices`
        # (not `items`) — Jinja resolves `.items` to dict.items() instead of
        # the key lookup, breaking the {% for %} loop.
        sections = []
        for state_key, label, group, tier in LIFECYCLE_SECTIONS:
            section_notices = groups.get(state_key, [])
            sections.append({
                "state": state_key,
                "label": label,
                "group": group,
                "tier": tier,
                "notices": section_notices,
                "count": len(section_notices),
                # active sections default-open + EXPIRED only if non-empty
                "default_open": tier == "active" or (state_key == "EXPIRED" and len(section_notices) > 0),
            })

        return templates.TemplateResponse(
            "dashboard.html",
            {
                "request": {"url": "/"},
                "sections": sections,
                "hero_stats": stats,
                "next_sync_time": _next_sync_time(),
            },
        )
    except Exception as exc:
        logger.exception("Dashboard render failed")
        return HTMLResponse(content=f"<h1>Error</h1><p>{exc}</p>", status_code=500)


def _action_tokens_for(notice: Notice) -> dict[str, str]:
    """Return {transition_value: token} for every transition allowed from this
    notice's current lifecycle_state. Empty dict if no transitions available."""
    current = notice.lifecycle_state or LifecycleState.DISCOVERED
    tokens = {}
    for trans, (allowed_from, _) in ALLOWED_TRANSITIONS.items():
        if current in allowed_from:
            tokens[trans.value] = make_decision_token(notice.id, trans)
    return tokens


# ---------------------------------------------------------------------
# Decision endpoint — one-click GET from email / dashboard
# ---------------------------------------------------------------------

@app.get("/decide/{notice_id}/{action}/{token}", response_class=HTMLResponse)
def decide(notice_id: int, action: str, token: str, db: Session = Depends(get_db)):
    """
    Idempotent one-click decision. Click-from-email lands here.
    GET is required (mail clients can't POST). Token is single-use:
    first click stamps Decision.used_at, repeat clicks return 'already done'.
    """
    # Verify token first (cheapest gate)
    try:
        token_nid, token_transition = verify_decision_token(token)
    except ValueError as e:
        reason = str(e)
        message = {
            "expired": "결정 링크가 만료됐습니다 (7일 경과).",
            "invalid_signature": "잘못된 결정 링크입니다.",
            "malformed": "결정 링크 형식 오류.",
        }.get(reason, "결정 링크 검증 실패.")
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": f"/decide/{notice_id}/{action}/{token}"},
                "status": "error",
                "message": message,
                "notice": None,
            },
            status_code=410 if reason == "expired" else 400,
        )

    # Cross-check URL params vs token contents (defense in depth)
    if token_nid != notice_id or token_transition.value != action:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "error",
                "message": "결정 링크가 URL과 일치하지 않습니다.",
                "notice": None,
            },
            status_code=400,
        )

    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "error",
                "message": f"공고 {notice_id}을(를) 찾을 수 없습니다.",
                "notice": None,
            },
            status_code=404,
        )

    # Check if this token has already been used
    existing = db.query(Decision).filter(Decision.token == token).first()
    if existing and existing.used_at is not None:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "already_done",
                "message": f"이미 처리됨: {token_transition.value} (처리 시각: {existing.used_at.strftime('%Y-%m-%d %H:%M')})",
                "notice": notice,
                "transition": token_transition.value,
            },
        )

    # Lifecycle transition validation
    current = notice.lifecycle_state or LifecycleState.DISCOVERED
    allowed_from, target_state = ALLOWED_TRANSITIONS[token_transition]
    if current not in allowed_from:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "invalid_transition",
                "message": f"현재 상태({current.value})에서는 '{token_transition.value}' 액션을 할 수 없습니다.",
                "notice": notice,
                "transition": token_transition.value,
            },
            status_code=409,
        )

    # Apply transition
    notice.lifecycle_state = target_state
    notice.updated_at = datetime.utcnow()

    if existing is None:
        db.add(Decision(
            notice_id=notice.id,
            transition_type=token_transition,
            token=token,
            decided_at=datetime.utcnow(),
            used_at=datetime.utcnow(),
        ))
    else:
        existing.used_at = datetime.utcnow()

    db.commit()
    db.refresh(notice)

    logger.info(
        "Notice %s transitioned to %s via %s",
        notice.bid_notice_no, target_state.value, token_transition.value,
    )

    # Side-effect: PARTICIPATE → immediately email 주니어 (execution team).
    # Monitor cc included by send_executor_confirmation if MONITOR_EMAIL set.
    if token_transition == TransitionType.PARTICIPATE:
        try:
            send_executor_confirmation(notice)
        except Exception:
            logger.exception("send_executor_confirmation failed (non-fatal)")

    return templates.TemplateResponse(
        "decide.html",
        {
            "request": {"url": "/"},
            "status": "ok",
            "message": _success_message(token_transition),
            "notice": notice,
            "transition": token_transition.value,
        },
    )


def _success_message(transition: TransitionType) -> str:
    return {
        TransitionType.PARTICIPATE: "참여로 저장되었습니다. 처리 시작 알림 메일이 발송됐습니다.",
        TransitionType.PASS: "패스로 저장되었습니다.",
        TransitionType.SUBMITTED: "제출완료로 저장되었습니다. 결과 통지를 기다립니다.",
        TransitionType.RESUBMITTED: "재제출 완료로 저장되었습니다.",
    }[transition]


# ---------------------------------------------------------------------
# Background sync infra (preserved from prior cycle)
# ---------------------------------------------------------------------

_sync_lock = threading.Lock()
_sync_state = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "last_result": None,
    "error": None,
}


def _run_sync_background() -> None:
    try:
        result = trigger_sync_now()
        with _sync_lock:
            _sync_state["last_result"] = result
            _sync_state["error"] = None
    except Exception as exc:  # noqa: BLE001
        logger.exception("Background sync failed")
        with _sync_lock:
            _sync_state["error"] = str(exc)
    finally:
        with _sync_lock:
            _sync_state["running"] = False
            _sync_state["finished_at"] = datetime.utcnow().isoformat()


@app.post("/sync")
def manual_sync(background_tasks: BackgroundTasks):
    with _sync_lock:
        if _sync_state["running"]:
            return {"status": "already_running", "started_at": _sync_state["started_at"]}
        _sync_state["running"] = True
        _sync_state["started_at"] = datetime.utcnow().isoformat()
        _sync_state["finished_at"] = None
        _sync_state["error"] = None
    logger.info("Manual sync endpoint called — running in background")
    background_tasks.add_task(_run_sync_background)
    return {"status": "started", "started_at": _sync_state["started_at"]}


@app.get("/sync/status")
def sync_status():
    with _sync_lock:
        return dict(_sync_state)


# ---------------------------------------------------------------------
# Manual triggers — useful for prototype-cycle verification
# ---------------------------------------------------------------------

@app.post("/notify/test-email")
def trigger_test_email(db: Session = Depends(get_db)):
    """Send a digest email with the 5 most recent passing notices."""
    recent = (
        db.query(Notice)
        .filter(Notice.passes_filters == True)  # noqa: E712
        .order_by(Notice.created_at.desc())
        .limit(5)
        .all()
    )
    payload = [_notice_to_email_dict(n) for n in recent]
    sent = send_digest_email(payload, force=True)
    return {"ok": sent, "sampled": len(payload)}


def _notice_to_email_dict(n: Notice) -> dict:
    return {
        "id": n.id,
        "bid_notice_no": n.bid_notice_no,
        "bid_notice_name": n.bid_notice_name,
        "institution_name": n.institution_name,
        "bid_amount_min": n.bid_amount_min,
        "bid_amount_max": n.bid_amount_max,
        "bid_close_date": n.bid_close_date,
        "notice_date": n.notice_date,
        "url": n.url,
        "lifecycle_state": n.lifecycle_state.value if n.lifecycle_state else "DISCOVERED",
        "ref_notice_no": n.ref_notice_no,
        "tokens": _action_tokens_for(n),
    }


@app.post("/notify/escalate-now")
def trigger_escalation():
    """Legacy 48h Slack escalation. Kept for backwards-compat; superseded by Ticket #2."""
    return escalate_stale_notices()


@app.post("/expire-now")
def trigger_expire_now():
    """Run the EXPIRED sweep immediately (cron normally runs at 09:30)."""
    return expire_stale_notices()


@app.post("/decide/{notice_id}/undo", response_class=HTMLResponse)
def undo_decision(notice_id: int, db: Session = Depends(get_db)):
    """
    되돌리기. User-initiated lifecycle 결정만 가능
    (DECIDED_PASS/DECIDED_PARTICIPATE/SUBMITTED/RESUBMITTED → 직전 상태).
    """
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "error",
                "message": f"공고 {notice_id}을(를) 찾을 수 없습니다.",
                "notice": None,
            },
            status_code=404,
        )

    current = notice.lifecycle_state
    if current not in UNDO_TARGET:
        return templates.TemplateResponse(
            "decide.html",
            {
                "request": {"url": "/"},
                "status": "invalid_transition",
                "message": f"현재 상태({current.value})에서는 되돌리기를 할 수 없습니다.",
                "notice": notice,
                "transition": "undo",
            },
            status_code=409,
        )

    prior = UNDO_TARGET[current]
    notice.lifecycle_state = prior
    notice.updated_at = datetime.utcnow()

    # Remove the latest Decision row so the token becomes "fresh" again for
    # re-decision via mail (audit deferred — would add undone_at column).
    latest = (
        db.query(Decision)
        .filter(Decision.notice_id == notice_id)
        .order_by(Decision.decided_at.desc())
        .first()
    )
    if latest:
        db.delete(latest)

    # Reset reminder dedup so cron can re-remind once the notice is back in
    # DISCOVERED (e.g. user undid a wrongly-pressed 패스).
    if prior == LifecycleState.DISCOVERED:
        notice.decision_reminder_sent_at = None
    elif prior == LifecycleState.DECIDED_PARTICIPATE:
        # Reset deadline reminders so they can re-fire if relevant
        notice.deadline_d3_sent_at = None
        notice.deadline_d1_sent_at = None

    db.commit()
    db.refresh(notice)

    logger.info(
        "Notice %s reverted: %s → %s (decision row deleted)",
        notice.bid_notice_no, current.value, prior.value,
    )

    return templates.TemplateResponse(
        "decide.html",
        {
            "request": {"url": "/"},
            "status": "ok",
            "message": f"{current.value} → {prior.value}로 되돌렸습니다.",
            "notice": notice,
            "transition": "undo",
        },
    )


# Persona-별 reminder 강제 트리거 (e2e 메일 검증용)
@app.post("/notify/decision-reminder-now")
def trigger_decision_reminder():
    """48h 무결정 reminder 즉시 실행. 영업일 기준 48시간 룰은 그대로 적용됨."""
    return send_decision_reminders_48h()


@app.post("/notify/deadline-reminders-now")
def trigger_deadline_reminders():
    """D-3 / D-1 마감 임박 reminder 즉시 실행. bid_close_date 기준."""
    return send_deadline_reminders()


@app.post("/notify/repost-alert-now/{notice_id}")
def trigger_repost_alert(notice_id: int, db: Session = Depends(get_db)):
    """특정 공고에 대해 재공고 알림 메일 강제 발송 (테스트용)."""
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(404, f"Notice {notice_id} not found")
    sent = send_repost_alert(notice)
    return {"ok": sent, "notice_id": notice_id}


@app.post("/notify/executor-confirmation-now/{notice_id}")
def trigger_executor_confirmation(notice_id: int, db: Session = Depends(get_db)):
    """특정 공고에 대해 참여확정 메일 강제 발송 (테스트용)."""
    notice = db.query(Notice).filter(Notice.id == notice_id).first()
    if not notice:
        raise HTTPException(404, f"Notice {notice_id} not found")
    sent = send_executor_confirmation(notice)
    return {"ok": sent, "notice_id": notice_id}


@app.on_event("startup")
async def startup_event():
    logger.info("Application startup...")
    try:
        init_db()
        logger.info("Database tables initialized")
    except Exception:
        logger.exception("Error initializing database")
    try:
        scheduler_enabled = os.getenv("CRON_ENABLED", "true").lower() == "true"
        start_scheduler(enabled=scheduler_enabled)
        logger.info("Scheduler started")
    except Exception:
        logger.exception("Error starting scheduler")


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Application shutdown...")
    try:
        stop_scheduler()
    except Exception:
        logger.exception("Error stopping scheduler")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
