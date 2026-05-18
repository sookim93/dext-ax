#!/usr/bin/env python3
"""
입찰공고 일일 다이제스트 — Phase 1 MVP

What it does:
- 나라장터 PubDataOpnStdService에서 어제~오늘 신규 공고 fetch
- 필터: 발주기관 endswith(대학교|대학) + 키워드 include/exclude + 예산 범위
- refNtceNo 기반 재공고 별도 분류 (메일 상단)
- Daum SMTP로 다이제스트 메일 1통 발송 + retry 3회

What it intentionally does NOT do (Phase 2+):
- 결정 추적 / 라이프사이클 state / 대시보드
- 자동 reminder / escalation
- DB 상태 저장 (state-free cron)
- 인프라 (GitHub Actions cron 사용)
"""

from __future__ import annotations

import html as html_lib
import logging
import os
import smtplib
import ssl
import sys
import time
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("daily_digest")

# ---------------------------------------------------------------------
# Config (env-driven)
# ---------------------------------------------------------------------
load_dotenv()

G2B_API_KEY = os.environ["G2B_API_KEY"]
SMTP_USER = os.environ["SMTP_USER"]
SMTP_PASSWORD = os.environ["SMTP_PASSWORD"]
EMAIL_SENDER_NAME = os.getenv("EMAIL_SENDER_NAME", "덱스트 입찰공고 봇")
EMAIL_RECIPIENTS = [
    a.strip() for a in os.environ["EMAIL_RECIPIENTS"].split(",") if a.strip()
]
SUBJECT_PREFIX = os.getenv("SUBJECT_PREFIX", "")  # 예: "(테스트) " — 테스트 발송 표기용

# 필터 — 코드 변경 없이 바꾸려면 .env 또는 GitHub secrets에 두는 것도 가능 (Phase 2)
INCLUDE_KEYWORDS = ["논술", "실기", "입학", "입시", "전자채점", "전자평가", "면접", "평가"]
EXCLUDE_KEYWORDS = ["병원", "건설", "건축", "공사", "디자인", "홍보", "모집요강", "인쇄업체"]
BUDGET_MIN = 1_000_000          # 1M
BUDGET_MAX = 500_000_000        # 500M
DAYS_BACK = int(os.getenv("DAYS_BACK", "3"))  # 오전 cron=3, 오후 cron=1

DAUM_SMTP_HOST = "smtp.daum.net"
DAUM_SMTP_PORT = 465
G2B_BASE = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
DATE_FMT = "%Y%m%d%H%M"
ROWS_PER_PAGE = 100
MAX_PAGES = 30                  # safety cap


# ---------------------------------------------------------------------
# G2B API fetch
# ---------------------------------------------------------------------
def fetch_notices(days_back: int) -> List[Dict]:
    """Fetch all notices posted within the last ``days_back`` days. Paginate
    until exhaustion or MAX_PAGES cap."""
    end_dt = datetime.now()
    start_dt = end_dt - timedelta(days=days_back)
    all_notices: List[Dict] = []
    seen: set = set()

    for page in range(1, MAX_PAGES + 1):
        params = {
            "serviceKey": G2B_API_KEY,
            "pageNo": page,
            "numOfRows": ROWS_PER_PAGE,
            "type": "json",
            "inqryDiv": "1",
            "inqryBgnDt": start_dt.strftime(DATE_FMT),
            "inqryEndDt": end_dt.strftime(DATE_FMT),
        }
        try:
            r = requests.get(
                f"{G2B_BASE}/getDataSetOpnStdBidPblancInfo",
                params=params, timeout=30,
            )
            r.raise_for_status()
            data = r.json()
        except (requests.RequestException, ValueError) as exc:
            logger.error("G2B fetch page=%d failed: %s", page, exc)
            break

        header = data.get("response", {}).get("header", {})
        if header.get("resultCode") != "00":
            logger.error("G2B API error: %s", header.get("resultMsg"))
            break

        body = data.get("response", {}).get("body", {}) or {}
        raw_items = body.get("items", []) or []
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("item", []) or []
        if isinstance(raw_items, dict):
            raw_items = [raw_items]

        if not raw_items:
            logger.info("Page %d empty — pagination done", page)
            break

        new_count = 0
        for item in raw_items:
            n = _parse_item(item)
            if n and n["bid_notice_no"] not in seen:
                seen.add(n["bid_notice_no"])
                all_notices.append(n)
                new_count += 1
        logger.info("Page %d → %d new (total %d)", page, new_count, len(all_notices))

        if len(raw_items) < ROWS_PER_PAGE:
            break

    return all_notices


def _parse_item(item: Dict) -> Optional[Dict]:
    try:
        bid_no = item.get("bidNtceNo") or ""
        raw_ref = (item.get("refNtceNo") or "").strip()
        ref_no = raw_ref if raw_ref and raw_ref != bid_no else None
        return {
            "bid_notice_no": bid_no,
            "bid_notice_name": item.get("bidNtceNm", "") or "",
            "notice_date": _parse_date(item.get("bidNtceDate")),
            "institution_name": item.get("ntceInsttNm", "") or "",
            "bid_amount_min": _to_float(item.get("presmptPrce")),
            "bid_amount_max": (
                _to_float(item.get("asignBdgtAmt"))
                or _to_float(item.get("presmptPrce"))
            ),
            "bid_close_date": _parse_close(
                item.get("bidClseDate"), item.get("bidClseTm"),
            ),
            "ref_notice_no": ref_no,
            "url": item.get("bidNtceUrl") or "",
        }
    except Exception as exc:  # noqa: BLE001
        logger.debug("parse failed: %s", exc)
        return None


def _parse_date(value):
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_close(date_str, time_str):
    base = _parse_date(date_str)
    if not base:
        return None
    if time_str:
        try:
            t = datetime.strptime(time_str, "%H:%M").time()
            return datetime.combine(base.date(), t)
        except ValueError:
            pass
    return base


def _to_float(value):
    if value in (None, "", "0"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------
# Filter
# ---------------------------------------------------------------------
def passes_filter(n: Dict) -> bool:
    name = (n.get("bid_notice_name") or "")
    inst = (n.get("institution_name") or "").rstrip()
    haystack = (name + " " + inst).lower()

    # age — PubDataOpnStdService가 inqryBgnDt 서버 필터를 무시하므로 클라이언트에서
    # notice_date 기준 cutoff 적용. **영업일 기준** (월요일 cron이 직전 금/목 잡도록).
    nd = n.get("notice_date")
    if isinstance(nd, datetime):
        if nd.date() < _oldest_business_day(DAYS_BACK):
            return False

    # exclude — 한 마디라도 걸리면 drop
    for excl in EXCLUDE_KEYWORDS:
        if excl.lower() in haystack:
            return False

    # include — 적어도 하나 매치해야 함
    if not any(kw.lower() in name.lower() for kw in INCLUDE_KEYWORDS):
        return False

    # institution endswith
    if not (inst.endswith("대학교") or inst.endswith("대학")):
        return False

    # budget range
    bmin = n.get("bid_amount_min")
    bmax = n.get("bid_amount_max")
    if bmin is None or bmax is None:
        return False
    if bmin < BUDGET_MIN or bmax > BUDGET_MAX:
        return False

    return True


def _oldest_business_day(business_days_back: int):
    """오늘 포함, N 영업일 거꾸로 셌을 때 가장 오래된 날짜.
    DAYS_BACK=1 → 오늘만 (오늘이 평일이면 오늘, 주말이면 직전 평일)
    DAYS_BACK=3 → 오늘 + 직전 2 영업일. 월요일이면 → 금요일.
    """
    if business_days_back <= 0:
        return datetime.now().date()
    d = datetime.now().date()
    biz_left = business_days_back
    if d.weekday() < 5:
        biz_left -= 1
    while biz_left > 0:
        d -= timedelta(days=1)
        if d.weekday() < 5:
            biz_left -= 1
    return d


def split_notices(notices: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Split into (new, reposts) based on ref_notice_no presence."""
    new_list = [n for n in notices if not n.get("ref_notice_no")]
    repost_list = [n for n in notices if n.get("ref_notice_no")]
    return new_list, repost_list


# ---------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------
def _fmt_amount(v) -> str:
    if v is None:
        return "-"
    try:
        return f"{int(v):,}원"
    except (TypeError, ValueError):
        return "-"


def _fmt_close(v) -> str:
    if not isinstance(v, datetime):
        return "-"
    delta = (v - datetime.utcnow()).days
    if delta < 0:
        dday = "마감"
    elif delta == 0:
        dday = "D-DAY"
    else:
        dday = f"D-{delta}"
    return f"{v.strftime('%Y-%m-%d %H:%M')} ({dday})"


def _safe_url(value: Optional[str]) -> str:
    if value and value.startswith(("http://", "https://")):
        return html_lib.escape(value, quote=True)
    return "#"


def _row(n: Dict) -> str:
    href = _safe_url(n.get("url"))
    name = html_lib.escape(n.get("bid_notice_name") or "(제목 없음)")
    inst = html_lib.escape(n.get("institution_name") or "-")
    amount = html_lib.escape(
        _fmt_amount(n.get("bid_amount_max") or n.get("bid_amount_min")),
    )
    close = html_lib.escape(_fmt_close(n.get("bid_close_date")))
    ref = ""
    if n.get("ref_notice_no"):
        ref = (
            '<div style="font-size:11px;color:#999;margin-top:2px;">'
            f'원공고: {html_lib.escape(n["ref_notice_no"])}</div>'
        )
    return f"""
    <tr>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;">
        <a href="{href}" style="color:#1a73e8;text-decoration:none;font-weight:500;">{name}</a>
        {ref}
      </td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;color:#555;">{inst}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;text-align:right;font-family:Monaco,monospace;">{amount}</td>
      <td style="padding:10px 8px;border-bottom:1px solid #eee;color:#555;">{close}</td>
    </tr>
    """


_WEEKDAY_KR = ["월", "화", "수", "목", "금", "토", "일"]


def _group_by_date(rows: List[Dict]) -> List[Tuple[Optional[datetime], List[Dict]]]:
    """공고 등록일(notice_date) 기준 그룹화 — 최근 날짜부터.
    날짜 없는 항목은 마지막 '(날짜 미상)' 그룹으로 모음."""
    buckets: Dict[Optional[datetime], List[Dict]] = {}
    for n in rows:
        nd = n.get("notice_date")
        key = nd.date() if isinstance(nd, datetime) else None
        buckets.setdefault(key, []).append(n)
    dated = sorted(
        [(k, v) for k, v in buckets.items() if k is not None],
        key=lambda kv: kv[0],
        reverse=True,
    )
    undated = [(None, buckets[None])] if None in buckets else []
    return dated + undated


def _fmt_date_header(d) -> str:
    if d is None:
        return "(날짜 미상)"
    today = datetime.now().date()
    delta = (today - d).days
    wd = _WEEKDAY_KR[d.weekday()]
    suffix = ""
    if delta == 0:
        suffix = " · 오늘"
    elif delta == 1:
        suffix = " · 어제"
    elif delta > 1:
        suffix = f" · {delta}일 전"
    return f"{d.strftime('%Y-%m-%d')} ({wd}){suffix}"


def _section(rows: List[Dict], label: str, color: str) -> str:
    if not rows:
        return ""
    groups = _group_by_date(rows)
    blocks = []
    for date_key, group_rows in groups:
        body = "".join(_row(n) for n in group_rows)
        date_header = _fmt_date_header(date_key)
        blocks.append(f"""
    <div style="margin-top:14px;font-size:12px;color:#666;font-weight:600;padding:4px 8px;background:#f5f5f5;border-radius:4px;">
      📅 {date_header} — {len(group_rows)}건
    </div>
    <table style="width:100%;border-collapse:collapse;border-top:1px solid #ddd;font-size:13px;margin-bottom:8px;">
      <thead>
        <tr style="background:#fafafa;">
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">공고명</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">발주기관</th>
          <th style="padding:6px 8px;text-align:right;border-bottom:1px solid #ddd;">예가</th>
          <th style="padding:6px 8px;text-align:left;border-bottom:1px solid #ddd;">입찰마감</th>
        </tr>
      </thead>
      <tbody>{body}</tbody>
    </table>
    """)
    return f"""
    <h3 style="margin:24px 0 8px;color:{color};border-left:4px solid {color};padding-left:8px;">
      {label} — {len(rows)}건
    </h3>
    {''.join(blocks)}
    """


def _render_filter_chips() -> str:
    """현재 적용 중인 필터를 시각화. 박이사·운영자가 메일 보고 즉시 인지."""
    def _chip(text: str, color: str) -> str:
        return (
            f'<span style="display:inline-block;padding:2px 8px;margin:2px 3px 2px 0;'
            f'background:{color};color:#fff;border-radius:12px;font-size:11px;'
            f'font-weight:500;">{html_lib.escape(text)}</span>'
        )

    include_chips = "".join(_chip(k, "#27ae60") for k in INCLUDE_KEYWORDS)
    exclude_chips = "".join(_chip(k, "#95a5a6") for k in EXCLUDE_KEYWORDS)
    inst_chips = _chip("대학교", "#1a73e8") + _chip("대학", "#1a73e8")
    budget = f"{BUDGET_MIN/1_000_000:.0f}M ~ {BUDGET_MAX/1_000_000:.0f}M원"

    return f"""
    <div style="background:#fafbfc;border:1px solid #e1e4e8;border-radius:6px;padding:12px 14px;margin:0 0 20px;font-size:12px;">
      <div style="margin-bottom:6px;">
        <span style="color:#666;font-weight:600;width:80px;display:inline-block;">포함 키워드</span>
        {include_chips}
      </div>
      <div style="margin-bottom:6px;">
        <span style="color:#666;font-weight:600;width:80px;display:inline-block;">제외 키워드</span>
        {exclude_chips}
      </div>
      <div style="margin-bottom:6px;">
        <span style="color:#666;font-weight:600;width:80px;display:inline-block;">발주기관</span>
        {inst_chips}
      </div>
      <div>
        <span style="color:#666;font-weight:600;width:80px;display:inline-block;">예가 범위</span>
        <span style="font-family:Monaco,monospace;color:#444;">{budget}</span>
      </div>
    </div>
    """


def render_digest(new_list: List[Dict], repost_list: List[Dict]) -> str:
    total = len(new_list) + len(repost_list)
    sections = ""
    if repost_list:
        sections += _section(repost_list, "🔁 재공고 (재제출 필요)", "#e67e22")
    if new_list:
        sections += _section(new_list, "🆕 신규 공고", "#27ae60")
    if not sections:
        sections = (
            '<p style="padding:20px;text-align:center;color:#888;">'
            '오늘 도착한 신규/재공고 없음.</p>'
        )

    return f"""
    <html>
      <body style="font-family:-apple-system,BlinkMacSystemFont,'Apple SD Gothic Neo',sans-serif;color:#222;max-width:780px;margin:0 auto;">
        <h2 style="margin:0 0 8px;">📋 오늘의 입찰공고 다이제스트 ({total}건)</h2>
        <p style="color:#666;margin:0 0 12px;font-size:13px;">
          발송 시각: {datetime.now().strftime('%Y-%m-%d %H:%M')} · 검색 범위: 최근 {DAYS_BACK} 영업일 (≥ {_oldest_business_day(DAYS_BACK).strftime('%Y-%m-%d')})
        </p>
        {_render_filter_chips()}
        <p style="color:#888;margin:0 0 16px;font-size:12px;">
          공고명을 클릭하면 나라장터 원문 페이지로 이동합니다. 결정·진행은 별도로 관리해주세요.
        </p>
        {sections}
      </body>
    </html>
    """


# ---------------------------------------------------------------------
# Mail
# ---------------------------------------------------------------------
def send_mail(subject: str, html_body: str, recipients: List[str]) -> bool:
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = formataddr((EMAIL_SENDER_NAME, SMTP_USER))
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    backoffs = [0, 3, 8]
    last_exc: Optional[Exception] = None
    for attempt, delay in enumerate(backoffs, start=1):
        if delay:
            time.sleep(delay)
        try:
            ctx = ssl.create_default_context()
            with smtplib.SMTP_SSL(
                DAUM_SMTP_HOST, DAUM_SMTP_PORT,
                context=ctx, timeout=60,
            ) as smtp:
                smtp.login(SMTP_USER, SMTP_PASSWORD)
                smtp.sendmail(SMTP_USER, recipients, msg.as_string())
            logger.info("Mail sent (attempt %d) → %s", attempt, recipients)
            return True
        except (smtplib.SMTPException, OSError) as exc:
            last_exc = exc
            logger.warning(
                "SMTP attempt %d/%d failed: %s", attempt, len(backoffs), exc,
            )
    logger.error("SMTP giving up: %s", last_exc)
    return False


# ---------------------------------------------------------------------
# Entry
# ---------------------------------------------------------------------
def main() -> int:
    logger.info("=== 입찰공고 일일 다이제스트 시작 ===")
    logger.info(
        "Config: keywords=%s, exclude=%s, budget=%s-%s, days_back=%d, recipients=%s",
        INCLUDE_KEYWORDS, EXCLUDE_KEYWORDS,
        f"{BUDGET_MIN:,}", f"{BUDGET_MAX:,}",
        DAYS_BACK, EMAIL_RECIPIENTS,
    )

    notices = fetch_notices(DAYS_BACK)
    logger.info("Fetched %d total notices", len(notices))

    passed = [n for n in notices if passes_filter(n)]
    logger.info("Passed filter: %d/%d", len(passed), len(notices))

    new_list, repost_list = split_notices(passed)
    logger.info("Split: %d new, %d reposts", len(new_list), len(repost_list))

    if not passed:
        logger.info("No notices to send today. Exiting cleanly.")
        return 0

    html_body = render_digest(new_list, repost_list)
    today = datetime.now().strftime("%m/%d")
    subject = (
        f"{SUBJECT_PREFIX}[입찰공고] {today} 다이제스트 — {len(passed)}건"
        + (f" (재공고 {len(repost_list)})" if repost_list else "")
    )

    ok = send_mail(subject, html_body, EMAIL_RECIPIENTS)
    logger.info("Mail send: %s", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
