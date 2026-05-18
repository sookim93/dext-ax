"""
G2B (나라장터) Open API client for fetching bidding notices.

Endpoint: PubDataOpnStdService / getDataSetOpnStdBidPblancInfo
  Base URL: https://apis.data.go.kr/1230000/ao/PubDataOpnStdService
  Service:  공공데이터개방표준서비스 (입찰공고정보)

This is the service approved on the dext data.go.kr account (verified
2026-05-13). Other candidate services (BidPublicInfoService,
BidPublicInfoService04/05, BdBidInfoService) return 404 or 500 for this key.
"""

import logging
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# Date format used by the open-std endpoint: YYYYMMDDHHMM
DATE_FMT = "%Y%m%d%H%M"


class G2BAPIClient:
    """Client for the data.go.kr `PubDataOpnStdService` bidding-notice API."""

    def __init__(self):
        self.api_key = os.getenv("G2B_API_KEY")
        if not self.api_key:
            raise ValueError("G2B_API_KEY environment variable not set")

        self.base_url = "https://apis.data.go.kr/1230000/ao/PubDataOpnStdService"
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    def search_notices(
        self,
        keyword: Optional[str] = None,           # server-side filter on bidNtceNm
        institution_type: Optional[str] = None,  # accepted for compat; API has no such field
        days_back: int = 30,
        since_dt: Optional[datetime] = None,
        page_no: int = 1,
        num_of_rows: int = 100,
    ) -> Dict:
        """
        Fetch a page of notices.

        Returns ``{notices, total_count, page_no, num_of_rows}`` or ``{}`` on
        error. ``institution_type`` is accepted for backward compatibility but
        ignored — the open-std response does not expose institution type, so the
        UNIVERSITY check is done in ``filters.py`` via name pattern.
        ``since_dt`` takes precedence over ``days_back`` — used by the
        incremental sync to only fetch notices newer than the last successful run.
        """
        end_dt = datetime.now()
        if since_dt is not None:
            start_dt = since_dt
        else:
            start_dt = end_dt - timedelta(days=days_back)

        params = {
            "serviceKey": self.api_key,
            "pageNo": page_no,
            "numOfRows": num_of_rows,
            "type": "json",
            "inqryDiv": "1",  # 1 = 등록일 기준
            "inqryBgnDt": start_dt.strftime(DATE_FMT),
            "inqryEndDt": end_dt.strftime(DATE_FMT),
        }
        if keyword:
            params["bidNtceNm"] = keyword

        try:
            logger.info(
                "G2B: fetching notices keyword=%s days_back=%s page=%s",
                keyword, days_back, page_no,
            )
            response = self.session.get(
                f"{self.base_url}/getDataSetOpnStdBidPblancInfo",
                params=params,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            header = data.get("response", {}).get("header", {})
            if header.get("resultCode") != "00":
                logger.error("G2B API error: %s", header.get("resultMsg", "Unknown"))
                return {}

            body = data.get("response", {}).get("body", {}) or {}
            raw_items = body.get("items", []) or []
            # Older format wrapped items in {"item": [...]}; tolerate both.
            if isinstance(raw_items, dict):
                raw_items = raw_items.get("item", [])
            if isinstance(raw_items, dict):
                raw_items = [raw_items]

            notices: List[Dict] = []
            for item in raw_items:
                parsed = self._parse_notice(item)
                if parsed:
                    notices.append(parsed)

            return {
                "notices": notices,
                "total_count": body.get("totalCount", 0),
                "page_no": page_no,
                "num_of_rows": num_of_rows,
            }
        except requests.RequestException as exc:
            logger.error("G2B fetch failed: %s", exc)
            return {}
        except (ValueError, KeyError) as exc:
            logger.error("G2B response parse error: %s", exc)
            return {}

    def get_notice_detail(self, bid_notice_no: str) -> Optional[Dict]:
        """
        Look up a single notice by ``bidNtceNo``. The PubDataOpnStd service does
        not expose a by-id operation, so we scan a recent page and filter — keeps
        the call site stable for the dashboard.
        """
        result = self.search_notices(days_back=90, page_no=1, num_of_rows=100)
        for notice in result.get("notices", []):
            if notice.get("bid_notice_no") == bid_notice_no:
                return notice
        return None

    def _parse_notice(self, item: Dict) -> Optional[Dict]:
        """Map the PubDataOpnStd JSON row to the dashboard's notice schema."""
        try:
            notice_date = _parse_date(item.get("bidNtceDate"))
            bid_close_date = _parse_date_with_time(
                item.get("bidClseDate"), item.get("bidClseTm")
            )

            # asignBdgtAmt = 배정예산, presmptPrce = 추정/예정가격
            bid_amount_min = _to_float(item.get("presmptPrce"))
            bid_amount_max = _to_float(item.get("asignBdgtAmt")) or bid_amount_min

            bid_notice_no = item.get("bidNtceNo", "") or ""
            # refNtceNo: present on every row. When equal to bidNtceNo it's
            # the notice referencing itself (not a repost). When different
            # it's a repost pointing at the original. Normalize to None for
            # the self-reference case so the scheduler can treat truthy == repost.
            raw_ref = (item.get("refNtceNo") or "").strip()
            ref_notice_no = raw_ref if raw_ref and raw_ref != bid_notice_no else None

            return {
                "bid_notice_no": bid_notice_no,
                "bid_notice_name": item.get("bidNtceNm", ""),
                "notice_status": item.get("bidNtceSttusNm", ""),
                "notice_date": notice_date,
                "institution_name": item.get("ntceInsttNm", ""),
                # Open-std response has no institution_type — filters.py matches by name.
                "institution_type": "",
                "bid_amount_min": bid_amount_min,
                "bid_amount_max": bid_amount_max,
                "bid_close_date": bid_close_date,
                "ref_notice_no": ref_notice_no,
                "description": item.get("bsnsDivNm", ""),
                "url": item.get("bidNtceUrl") or "",
            }
        except (AttributeError, TypeError) as exc:
            logger.error("Notice parse error: %s", exc)
            return None


def _parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _parse_date_with_time(date_str: Optional[str], time_str: Optional[str]) -> Optional[datetime]:
    """Combine "YYYY-MM-DD" + "HH:MM" into a datetime. Falls back to midnight
    when only the date is present."""
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


def _to_float(value) -> Optional[float]:
    if value in (None, "", "0"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
