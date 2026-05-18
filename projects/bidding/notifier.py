"""
Notification module — persona-separated mail channels.

Channels:
  1. send_decision_digest   — 박이사 (DECISION_RECIPIENTS) 신규 공고 [참여]/[불참]
  2. send_executor_confirmation — 주니어 (EXECUTOR_RECIPIENTS) 즉시 알림 [제출완료]
  3. send_decision_reminder — 박이사 48h 무결정 reminder (주말 제외)
  4. send_executor_deadline_reminder — 주니어 D-3 / D-1 (D-1엔 박이사 cc)
  5. send_repost_alert      — 박이사 + 주니어 (재공고 자동 감지)

MONITOR_EMAIL은 모든 메일에 cc로 자동 추가 — 운영 안정화 후 비우면 OFF.

All channels degrade silently when env vars are missing — no exceptions
bubble up to the scheduler.
"""

from __future__ import annotations

import html
import json
import logging
import os
import smtplib
import ssl
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Iterable, List, Optional, Sequence
from urllib import error as urllib_error
from urllib import request as urllib_request

from models import LifecycleState, TransitionType
from tokens import make_decision_token

logger = logging.getLogger(__name__)

DAUM_SMTP_HOST = "smtp.daum.net"
DAUM_SMTP_PORT = 465
SLACK_TIMEOUT_SECONDS = 10


# ---------------------------------------------------------------------
# Recipient helpers (role-based)
# ---------------------------------------------------------------------

def _split_recipients(raw: Optional[str]) -> List[str]:
    if not raw:
        return []
    return [addr.strip() for addr in raw.split(",") if addr.strip()]


def _recipients_decision() -> List[str]:
    """박이사 (결정자). Falls back to EMAIL_RECIPIENTS if DECISION_RECIPIENTS unset."""
    r = _split_recipients(os.getenv("DECISION_RECIPIENTS"))
    return r if r else _split_recipients(os.getenv("EMAIL_RECIPIENTS"))


def _recipients_executor() -> List[str]:
    """주니어 (실행자). Falls back to EMAIL_RECIPIENTS if EXECUTOR_RECIPIENTS unset."""
    r = _split_recipients(os.getenv("EXECUTOR_RECIPIENTS"))
    return r if r else _split_recipients(os.getenv("EMAIL_RECIPIENTS"))


def _monitor_cc() -> List[str]:
    """모니터링 (본인). cc on everything when set. Empty → OFF in production."""
    return _split_recipients(os.getenv("MONITOR_EMAIL"))


# ---------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------

def _format_amount(amount: Optional[float]) -> str:
    if amount is None:
        return "-"
    try:
        return f"{int(amount):,}원"
    except (TypeError, ValueError):
        return "-"


def _format_date(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d")
    return str(value)


def _safe_url(value: Optional[str], fallback: str) -> str:
    """Block javascript:/data: schemes in href attributes."""
    if not value:
        return html.escape(fallback, quote=True)
    if value.startswith(("http://", "https://")):
        return html.escape(value, quote=True)
    return html.escape(fallback, quote=True)


def _format_close_with_dday(value) -> str:
    if not value:
        return "-"
    if not isinstance(value, datetime):
        return str(value)
    delta_days = (value - datetime.utcnow()).days
    if delta_days < 0:
        dday = "마감"
    elif delta_days == 0:
        dday = "D-DAY"
    else:
        dday = f"D-{delta_days}"
    return f"{value.strftime('%Y-%m-%d %H:%M')} ({dday})"


def _dashboard_url() -> str:
    return os.getenv("DASHBOARD_URL", "http://localhost:8000/")


def _decision_link(notice_id: int, transition: TransitionType) -> str:
    """Build absolute URL for a single-use decision link (token-protected)."""
    base = _dashboard_url().rstrip("/")
    token = make_decision_token(notice_id, transition)
    return f"{base}/decide/{notice_id}/{transition.value}/{token}"


def _btn(href: str, label: str, color: str) -> str:
    return (
        f'<a href="{html.escape(href, quote=True)}" '
        f'style="display:inline-block;padding:8px 16px;background:{color};color:#fff;'
        f'text-decoration:none;border-radius:4px;font-weight:600;margin-right:6px;">'
        f'{label}</a>'
    )


def _decision_buttons(notice_id: int) -> str:
    p = _decision_link(notice_id, TransitionType.PARTICIPATE)
    x = _decision_link(notice_id, TransitionType.PASS)
    return _btn(p, "참여", "#27ae60") + _btn(x, "불참", "#95a5a6")


def _submit_button(notice_id: int) -> str:
    link = _decision_link(notice_id, TransitionType.SUBMITTED)
    return _btn(link, "제출완료", "#1a73e8")


def _resubmit_button(notice_id: int) -> str:
    link = _decision_link(notice_id, TransitionType.RESUBMITTED)
    return _btn(link, "재제출 완료", "#e67e22")


# ---------------------------------------------------------------------
# Generic SMTP send (to + cc)
# ---------------------------------------------------------------------

def _send_smtp(subject: str, html_body: str, to: List[str], cc: Optional[List[str]] = None) -> bool:
    """Send HTML mail via Daum SMTP. Retries up to 3 times on transient errors
    (Daum occasionally times out on larger bodies or rapid bursts)."""
    if cc is None:
        cc = []
    smtp_user = os.getenv("SMTP_USER")
    smtp_pass = os.getenv("SMTP_PASSWORD") or os.getenv("SMTP_PASS")
    if not smtp_user or not smtp_pass or not to:
        logger.warning(
            "SMTP send skipped: SMTP_USER/PASSWORD or 'to' missing (subject=%r)", subject
        )
        return False
    sender_name = os.getenv("EMAIL_SENDER_NAME", "덱스트 입찰공고 봇")
    cc = [a for a in cc if a not in to]
    all_recipients = list(to) + cc
    message = MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = formataddr((sender_name, smtp_user))
    message["To"] = ", ".join(to)
    if cc:
        message["Cc"] = ", ".join(cc)
    message.attach(MIMEText(html_body, "html", "utf-8"))

    import time as _time
    backoffs = [0, 3, 8]  # immediate, 3s, 8s — Daum hiccups usually clear in <10s
    last_exc = None
    for attempt, delay in enumerate(backoffs, start=1):
        if delay:
            _time.sleep(delay)
        try:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(DAUM_SMTP_HOST, DAUM_SMTP_PORT, context=context, timeout=60) as smtp:
                smtp.login(smtp_user, smtp_pass)
                smtp.sendmail(smtp_user, all_recipients, message.as_string())
            logger.info(
                "Mail sent (attempt %d): '%s' to=%s cc=%s",
                attempt, subject, to, cc,
            )
            return True
        except (smtplib.SMTPException, OSError) as exc:
            last_exc = exc
            logger.warning(
                "SMTP send attempt %d/%d failed (%r): %s",
                attempt, len(backoffs), subject, exc,
            )
    logger.error("SMTP send giving up (%r): %s", subject, last_exc)
    return False


# ---------------------------------------------------------------------
# Notice → dict helper (for digest rendering)
# ---------------------------------------------------------------------

def _notice_to_dict(notice) -> dict:
    return {
        "id": notice.id,
        "bid_notice_no": notice.bid_notice_no,
        "bid_notice_name": notice.bid_notice_name,
        "institution_name": notice.institution_name,
        "bid_amount_min": notice.bid_amount_min,
        "bid_amount_max": notice.bid_amount_max,
        "bid_close_date": getattr(notice, "bid_close_date", None),
        "notice_date": notice.notice_date,
        "url": notice.url,
        "created_at": getattr(notice, "created_at", None),
        "lifecycle_state": (
            notice.lifecycle_state.value
            if getattr(notice, "lifecycle_state", None) is not None
            else LifecycleState.DISCOVERED.value
        ),
        "ref_notice_no": getattr(notice, "ref_notice_no", None),
    }


def notices_iter_to_dicts(notices: Iterable) -> List[dict]:
    return [_notice_to_dict(n) for n in notices]


# ---------------------------------------------------------------------
# Common row renderer
# ---------------------------------------------------------------------

def _row(n: dict, action_html: str) -> str:
    href = _safe_url(n.get("url"), _dashboard_url())
    name = html.escape(n.get("bid_notice_name") or "(제목 없음)")
    inst = html.escape(n.get("institution_name") or "-")
    amount = html.escape(_format_amount(n.get("bid_amount_max") or n.get("bid_amount_min")))
    close_str = html.escape(_format_close_with_dday(n.get("bid_close_date")))
    ref_info = ""
    if n.get("ref_notice_no"):
        ref_info = (
            f'<div style="font-size:11px;color:#999;margin-top:2px;">'
            f'원공고: {html.escape(n["ref_notice_no"])}</div>'
        )
    return f"""
    <tr>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;">
        <a href="{href}" style="color:#1a73e8;text-decoration:none;font-weight:500;">{name}</a>
        {ref_info}
      </td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;color:#555;">{inst}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;text-align:right;font-family:Monaco,monospace;">{amount}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;color:#555;">{close_str}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;white-space:nowrap;">{action_html}</td>
    </tr>
    """


def _table_html(rows_html: List[str]) -> str:
    return f"""
    <table style="width:100%;border-collapse:collapse;border-top:2px solid #ddd;font-size:13px;">
      <thead>
        <tr style="background:#f5f5f5;">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">공고명</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">발주기관</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid #ddd;">예가</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">입찰마감</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">액션</th>
        </tr>
      </thead>
      <tbody>
        {''.join(rows_html)}
      </tbody>
    </table>
    """


def _wrap(title: str, intro_html: str, body_html: str) -> str:
    dash = _safe_url(_dashboard_url(), "about:blank")
    return f"""
    <html>
      <body style="font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;color:#222;max-width:780px;margin:0 auto;">
        <h2 style="margin:0 0 8px;">{title}</h2>
        <p style="color:#666;margin:0 0 4px;font-size:13px;">
          발송 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')}
        </p>
        {intro_html}
        {body_html}
        <p style="margin-top:24px;">
          <a href="{dash}" style="display:inline-block;padding:10px 16px;background:#2c3e50;color:#fff;text-decoration:none;border-radius:4px;">
            모니터 대시보드 열기
          </a>
        </p>
      </body>
    </html>
    """


# ---------------------------------------------------------------------
# (1) 박이사 신규 공고 결정 다이제스트
# ---------------------------------------------------------------------

def send_decision_digest(notices: Sequence[dict], *, force: bool = False) -> bool:
    """DISCOVERED 신규 공고만 모아 박이사에게 [참여]/[불참] 결정 요청.
    Monitor cc."""
    notices = list(notices)
    if not notices and not force:
        logger.info("Decision digest skipped: empty")
        return False
    to = _recipients_decision()
    cc = _monitor_cc()
    rows = [_row(n, _decision_buttons(n["id"])) for n in notices]
    intro = (
        '<p style="color:#888;margin:8px 0 16px;font-size:12px;">'
        '아래 공고 각각에 대해 [참여] 또는 [불참] 버튼을 한 번 클릭하시면 결정이 저장됩니다. '
        '클릭 시 새 브라우저 탭에서 확인 페이지가 열립니다.'
        '</p>'
    )
    body = _table_html(rows) if rows else (
        '<p style="padding:20px;text-align:center;color:#888;">신규 공고가 없습니다.</p>'
    )
    subject = f"[입찰공고] 신규 결정 요청 {len(notices)}건 — {datetime.now().strftime('%m/%d %H:%M')}"
    html_body = _wrap(f"🆕 신규 공고 결정 요청 ({len(notices)}건)", intro, body)
    return _send_smtp(subject, html_body, to=to, cc=cc)


# ---------------------------------------------------------------------
# (2) 주니어 참여확정 즉시 알림
# ---------------------------------------------------------------------

def send_executor_confirmation(notice) -> bool:
    """박이사가 [참여] 결정한 직후 주니어한테 즉시 발송. [제출완료] 버튼."""
    to = _recipients_executor()
    cc = _monitor_cc()
    href = _safe_url(getattr(notice, "url", None), _dashboard_url())
    name = html.escape(notice.bid_notice_name or "(제목 없음)")
    inst = html.escape(notice.institution_name or "-")
    amount = html.escape(_format_amount(notice.bid_amount_max or notice.bid_amount_min))
    close_str = html.escape(_format_close_with_dday(notice.bid_close_date))
    submit_link = _decision_link(notice.id, TransitionType.SUBMITTED)
    body = f"""
    <p style="color:#666;margin:16px 0;">
      박이사님이 [참여] 결정하셨습니다. 아래 공고에 대해 서류 다운로드 → 7번 서버 저장
      → 스프레드시트 정리 → 제안서 작성 → 제출 후 [제출완료] 버튼을 눌러주세요.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">
      <tr><td style="padding:8px;color:#888;width:90px;">공고명</td>
          <td style="padding:8px;font-weight:600;"><a href="{href}" style="color:#1a73e8;text-decoration:none;">{name}</a></td></tr>
      <tr><td style="padding:8px;color:#888;">발주기관</td><td style="padding:8px;">{inst}</td></tr>
      <tr><td style="padding:8px;color:#888;">예가</td><td style="padding:8px;font-family:Monaco,monospace;">{amount}</td></tr>
      <tr><td style="padding:8px;color:#888;">입찰마감</td><td style="padding:8px;">{close_str}</td></tr>
    </table>
    <p style="margin:24px 0;text-align:center;">
      <a href="{html.escape(submit_link, quote=True)}"
         style="display:inline-block;padding:14px 28px;background:#1a73e8;color:#fff;text-decoration:none;border-radius:6px;font-weight:700;font-size:16px;">
        ✅ 제출완료
      </a>
    </p>
    <p style="font-size:12px;color:#999;text-align:center;">
      이 버튼은 일회용입니다. 클릭하면 시스템에 제출 완료로 기록됩니다.
    </p>
    """
    subject = f"[참여확정] {(notice.bid_notice_name or '')[:40]} — 제출 준비"
    html_body = _wrap(f"✅ 참여 결정: 제출 처리 시작", "", body)
    return _send_smtp(subject, html_body, to=to, cc=cc)


# Backwards-compat alias for app.py /decide handler
def send_decision_notification(notice, transition_value: str) -> bool:
    if transition_value != TransitionType.PARTICIPATE.value:
        return False
    return send_executor_confirmation(notice)


# ---------------------------------------------------------------------
# (3) 박이사 48h 무결정 reminder (주말 제외, scheduler가 호출 전 시간 계산)
# ---------------------------------------------------------------------

def send_decision_reminder(notices: Sequence[dict]) -> bool:
    """DISCOVERED 상태 48시간(주말 제외) 경과한 공고들. 박이사 reminder."""
    notices = list(notices)
    if not notices:
        return False
    to = _recipients_decision()
    cc = _monitor_cc()
    rows = [_row(n, _decision_buttons(n["id"])) for n in notices]
    intro = (
        '<p style="color:#c0392b;margin:8px 0 16px;font-size:14px;font-weight:600;">'
        '⏰ 영업일 기준 48시간 이상 결정이 미정인 공고입니다. 결정 부탁드립니다.'
        '</p>'
    )
    body = _table_html(rows)
    subject = f"[리마인더] 결정 대기 공고 {len(notices)}건 — 결정 부탁드립니다"
    html_body = _wrap(f"⏰ 결정 대기 reminder ({len(notices)}건)", intro, body)
    return _send_smtp(subject, html_body, to=to, cc=cc)


# ---------------------------------------------------------------------
# (4) 주니어 마감 임박 reminder — D-3, D-1 (D-1엔 박이사 cc)
# ---------------------------------------------------------------------

def send_executor_deadline_reminder(notices: Sequence[dict], *, dday: int) -> bool:
    """DECIDED_PARTICIPATE 중 마감 임박. D-1엔 박이사도 cc."""
    notices = list(notices)
    if not notices:
        return False
    to = _recipients_executor()
    cc = _monitor_cc()
    if dday <= 1:
        # D-1: 박이사도 cc — 사회적 압력 layer
        decision_list = _recipients_decision()
        cc = cc + [a for a in decision_list if a not in cc and a not in to]
    rows = [_row(n, _submit_button(n["id"])) for n in notices]
    label = "D-1 (하루 전)" if dday <= 1 else f"D-{dday} ({dday}일 전)"
    color = "#e74c3c" if dday <= 1 else "#e67e22"
    intro = (
        f'<p style="color:{color};margin:8px 0 16px;font-size:14px;font-weight:600;">'
        f'⏳ 입찰 마감 {label} — 제출 처리 확인 부탁드립니다. 제출하셨으면 [제출완료] 버튼을 눌러주세요.'
        f'</p>'
    )
    if dday <= 1:
        intro += (
            '<p style="color:#666;margin:8px 0 16px;font-size:12px;">'
            '* 박이사님도 함께 받으셨습니다.'
            '</p>'
        )
    body = _table_html(rows)
    subject = f"[마감 {label}] 제출 임박 공고 {len(notices)}건"
    html_body = _wrap(f"⏳ 마감 임박 {label} ({len(notices)}건)", intro, body)
    return _send_smtp(subject, html_body, to=to, cc=cc)


# ---------------------------------------------------------------------
# (5) 재공고 자동 감지 — 박이사 + 주니어 둘 다 즉시
# ---------------------------------------------------------------------

def send_repost_alert(notice) -> bool:
    """REPOST_DETECTED 진입 즉시 박이사 + 주니어 알림. 주니어한테 [재제출완료] 버튼."""
    decision_to = _recipients_decision()
    executor_to = _recipients_executor()
    to = list(dict.fromkeys(decision_to + executor_to))
    cc = _monitor_cc()
    href = _safe_url(getattr(notice, "url", None), _dashboard_url())
    name = html.escape(notice.bid_notice_name or "(제목 없음)")
    inst = html.escape(notice.institution_name or "-")
    amount = html.escape(_format_amount(notice.bid_amount_max or notice.bid_amount_min))
    close_str = html.escape(_format_close_with_dday(notice.bid_close_date))
    ref_no = html.escape(getattr(notice, "ref_notice_no", "") or "-")
    resubmit_link = _decision_link(notice.id, TransitionType.RESUBMITTED)
    body = f"""
    <p style="color:#c0392b;margin:16px 0;font-weight:600;">
      🔁 우리가 [참여] 결정했던 공고가 재공고로 다시 떴습니다. 재제출이 필요합니다.
    </p>
    <table style="width:100%;border-collapse:collapse;margin:16px 0;font-size:14px;">
      <tr><td style="padding:8px;color:#888;width:90px;">재공고명</td>
          <td style="padding:8px;font-weight:600;"><a href="{href}" style="color:#1a73e8;text-decoration:none;">{name}</a></td></tr>
      <tr><td style="padding:8px;color:#888;">원공고</td><td style="padding:8px;font-family:Monaco,monospace;color:#888;">{ref_no}</td></tr>
      <tr><td style="padding:8px;color:#888;">발주기관</td><td style="padding:8px;">{inst}</td></tr>
      <tr><td style="padding:8px;color:#888;">예가</td><td style="padding:8px;font-family:Monaco,monospace;">{amount}</td></tr>
      <tr><td style="padding:8px;color:#888;">입찰마감</td><td style="padding:8px;">{close_str}</td></tr>
    </table>
    <p style="margin:24px 0;text-align:center;">
      <a href="{html.escape(resubmit_link, quote=True)}"
         style="display:inline-block;padding:14px 28px;background:#e67e22;color:#fff;text-decoration:none;border-radius:6px;font-weight:700;font-size:16px;">
        ↩️ 재제출 완료
      </a>
    </p>
    <p style="font-size:12px;color:#999;text-align:center;">
      재제출이 끝나면 위 버튼을 한 번 눌러주세요.
    </p>
    """
    subject = f"[재공고 발생] {(notice.bid_notice_name or '')[:40]} — 재제출 필요"
    html_body = _wrap(f"🔁 재공고 자동 감지", "", body)
    return _send_smtp(subject, html_body, to=to, cc=cc)


# ---------------------------------------------------------------------
# Legacy / backwards-compat
# ---------------------------------------------------------------------

def send_digest_email(
    notices: Sequence[dict] = (),
    sections: Optional[dict] = None,
    *,
    force: bool = False,
) -> bool:
    """Legacy entry point. New code should call send_decision_digest directly.
    Maps to decision digest with DISCOVERED notices only."""
    if sections is not None:
        # Pull DISCOVERED out of sections for backwards-compat
        notices = sections.get(LifecycleState.DISCOVERED.value, [])
    return send_decision_digest(notices, force=force)


def send_slack_escalation(notices: Sequence[dict]) -> bool:
    """Legacy Slack channel — kept for backwards-compat but no longer wired
    into cron (replaced by send_decision_reminder + send_executor_deadline_reminder)."""
    if not notices:
        return False
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        logger.warning("Slack escalation skipped: SLACK_WEBHOOK_URL not set")
        return False
    dashboard_url = _dashboard_url()
    lines = [f"🚨 48시간 이상 미처리 입찰공고 {len(notices)}건"]
    for n in notices[:10]:
        lines.append(
            f"• <{n.get('url') or dashboard_url}|{n.get('bid_notice_name') or '(제목 없음)'}> — "
            f"{n.get('institution_name') or '-'} · {_format_amount(n.get('bid_amount_max') or n.get('bid_amount_min'))}"
        )
    if len(notices) > 10:
        lines.append(f"…외 {len(notices) - 10}건")
    lines.append(f"<{dashboard_url}|대시보드 열기>")
    payload = json.dumps({"text": "\n".join(lines)}).encode("utf-8")
    req = urllib_request.Request(
        webhook_url,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib_request.urlopen(req, timeout=SLACK_TIMEOUT_SECONDS) as resp:
            if 200 <= resp.status < 300:
                return True
            return False
    except (urllib_error.URLError, urllib_error.HTTPError, OSError):
        return False


def find_stale_notices(db_session, threshold_hours: int = 48) -> List[dict]:
    """Legacy helper — kept for backwards-compat tests."""
    from models import Decision, Notice
    cutoff = datetime.utcnow() - timedelta(hours=threshold_hours)
    rows = (
        db_session.query(Notice)
        .outerjoin(Decision, Decision.notice_id == Notice.id)
        .filter(Notice.passes_filters == True)  # noqa: E712
        .filter(Notice.created_at <= cutoff)
        .filter(Decision.id.is_(None))
        .all()
    )
    return [_notice_to_dict(n) for n in rows]
