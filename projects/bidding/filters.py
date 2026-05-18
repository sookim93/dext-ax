"""
Multi-level filtering logic for bidding notices.
Evaluates notices against multiple criteria:
1. Keyword filtering (notice name contains keywords)
2. Institution type filtering (only UNIVERSITY)
3. Budget range filtering (min >= 1M, max <= 500M)
4. Custom rule filtering (extensible)
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable

logger = logging.getLogger(__name__)


class NoticeFilter:
    """Multi-level filter for bidding notices."""

    def __init__(
        self,
        keywords: Optional[List[str]] = None,
        exclude_keywords: Optional[List[str]] = None,
        institution_types: Optional[List[str]] = None,
        budget_min: Optional[float] = None,
        budget_max: Optional[float] = None,
        max_age_days: Optional[int] = 14,
        custom_rules: Optional[List[Callable]] = None
    ):
        """
        Initialize filter with criteria.

        Args:
            keywords: Include keywords matched against notice name
            exclude_keywords: Disqualifying keywords (e.g. ['병원']) — checked against
                both notice name and institution name. A match in either drops the notice.
            institution_types: Institution types to include (e.g., ['UNIVERSITY'])
            budget_min: Minimum budget amount (won)
            budget_max: Maximum budget amount (won)
            custom_rules: Custom filter functions that take a notice dict and return bool
        """
        # Default keywords from README
        self.keywords = keywords or ['논술', '실기', '입학', '입시', '전자채점', '전자평가', '면접', '평가']

        # Default exclusion list — terms that disqualify a notice when matched in
        # the bid name or institution name. The dext bid team only handles
        # academic-evaluation work (논술 채점, 평가 시스템, etc.), not facility
        # work or marketing/communication contracts.
        self.exclude_keywords = (
            exclude_keywords if exclude_keywords is not None
            else ['병원', '건설', '건축', '공사', '디자인', '홍보', '모집요강']
        )

        # Default institution types from README
        self.institution_types = institution_types or ['UNIVERSITY', 'UNIVERSITY_KOREAN']

        # Default budget range from README (in won)
        self.budget_min = budget_min if budget_min is not None else 1_000_000  # 1M won
        self.budget_max = budget_max if budget_max is not None else 500_000_000  # 500M won

        # Drop notices whose notice_date is older than this many days from now.
        # Set to None to disable. PubDataOpnStdService returns up to ~30 days of
        # rows regardless of inqryBgnDt, so this is the only way to enforce a
        # tight recency window.
        self.max_age_days = max_age_days

        # Custom filtering rules
        self.custom_rules = custom_rules or []

    def apply(self, notice: Dict) -> bool:
        """
        Apply all filters to a notice.

        Args:
            notice: Notice dictionary from G2BAPIClient.search_notices()

        Returns:
            True if notice passes all filters, False otherwise
        """
        # Age check — drop notices older than max_age_days (default 14).
        if not self._check_age(notice):
            logger.debug(f"Notice {notice.get('bid_notice_no')} failed max_age filter")
            return False

        # Exclusion check — drops the notice if any exclude_keyword matches the
        # name or the institution. Runs first so we short-circuit hospitals etc.
        if not self._check_excluded(notice):
            logger.debug(f"Notice {notice.get('bid_notice_no')} hit exclude keyword filter")
            return False

        # Check keyword filter
        if not self._check_keywords(notice):
            logger.debug(f"Notice {notice.get('bid_notice_no')} failed keyword filter")
            return False

        # Check institution type filter
        if not self._check_institution_type(notice):
            logger.debug(f"Notice {notice.get('bid_notice_no')} failed institution type filter")
            return False

        # Check budget range filter
        if not self._check_budget_range(notice):
            logger.debug(f"Notice {notice.get('bid_notice_no')} failed budget range filter")
            return False

        # Apply custom rules
        for rule in self.custom_rules:
            try:
                if not rule(notice):
                    logger.debug(f"Notice {notice.get('bid_notice_no')} failed custom rule: {rule.__name__}")
                    return False
            except Exception as e:
                logger.error(f"Error applying custom rule {rule.__name__}: {str(e)}")
                return False

        return True

    def _check_age(self, notice: Dict) -> bool:
        """
        Return False if the notice's ``notice_date`` is older than
        ``self.max_age_days`` days ago. Missing dates pass through (we don't
        want to drop a notice silently just because the API omitted the field).
        """
        if not self.max_age_days:
            return True
        notice_date = notice.get("notice_date")
        if not isinstance(notice_date, datetime):
            return True  # unknown age → don't drop
        cutoff = datetime.utcnow() - timedelta(days=self.max_age_days)
        return notice_date >= cutoff

    def _check_excluded(self, notice: Dict) -> bool:
        """
        Return False (i.e. fail) if any exclude_keyword appears in the notice
        name or the institution name. Case-insensitive substring match.
        """
        if not self.exclude_keywords:
            return True

        haystack = " ".join(
            (notice.get("bid_notice_name") or "", notice.get("institution_name") or "")
        ).lower()
        for term in self.exclude_keywords:
            if term and term.lower() in haystack:
                return False
        return True

    def _check_keywords(self, notice: Dict) -> bool:
        """
        Check if notice name contains any of the keywords.

        Args:
            notice: Notice dictionary

        Returns:
            True if notice name contains at least one keyword, False otherwise
        """
        notice_name = notice.get('bid_notice_name', '').lower()

        if not notice_name:
            logger.debug("Notice has no name")
            return False

        # Check if any keyword is in the notice name
        for keyword in self.keywords:
            if keyword.lower() in notice_name:
                logger.debug(f"Notice {notice.get('bid_notice_no')} matched keyword: {keyword}")
                return True

        return False

    def _check_institution_type(self, notice: Dict) -> bool:
        """
        Decide whether the notice was issued by a university.

        Per user direction (2026-05-14): match only when the institution name
        ENDS with "대학교" or "대학". Substring match was too loose — it
        accepted attached units like "...대학교 산학협력단" which the bid
        team often did not want. Trailing-whitespace tolerant via .rstrip().

        Side-effect: attached units (산학협력단 등) are now dropped. Tune via
        adding patterns to this check or moving to a code-based whitelist if
        the first sync misses notices the user actually wants.
        """
        name = (notice.get('institution_name') or '').rstrip()
        if name.endswith('대학교') or name.endswith('대학'):
            return True

        # Backwards-compat: if a caller still sets institution_type explicitly
        # (tests or future API change), honor it.
        institution_type = (notice.get('institution_type') or '').upper()
        if institution_type:
            for allowed_type in self.institution_types:
                if institution_type == allowed_type.upper():
                    return True
        return False

    def _check_budget_range(self, notice: Dict) -> bool:
        """
        Check if budget amounts fall within the allowed range.
        Budget range check:
        - bid_amount_min >= budget_min (1M won)
        - bid_amount_max <= budget_max (500M won)

        Args:
            notice: Notice dictionary

        Returns:
            True if budget is within range, False otherwise
        """
        bid_amount_min = notice.get('bid_amount_min')
        bid_amount_max = notice.get('bid_amount_max')

        # If either amount is missing, we can't evaluate
        if bid_amount_min is None or bid_amount_max is None:
            logger.debug(f"Notice {notice.get('bid_notice_no')} missing budget information")
            return False

        # Check minimum budget constraint
        if bid_amount_min < self.budget_min:
            logger.debug(f"Notice {notice.get('bid_notice_no')} min budget {bid_amount_min} below threshold {self.budget_min}")
            return False

        # Check maximum budget constraint
        if bid_amount_max > self.budget_max:
            logger.debug(f"Notice {notice.get('bid_notice_no')} max budget {bid_amount_max} above threshold {self.budget_max}")
            return False

        logger.debug(f"Notice {notice.get('bid_notice_no')} passed budget range filter: {bid_amount_min}-{bid_amount_max}")
        return True

    def add_custom_rule(self, rule: Callable):
        """
        Add a custom filter rule.

        Args:
            rule: Callable that takes a notice dict and returns bool
        """
        self.custom_rules.append(rule)

    def remove_custom_rule(self, rule: Callable):
        """
        Remove a custom filter rule.

        Args:
            rule: Callable to remove
        """
        if rule in self.custom_rules:
            self.custom_rules.remove(rule)

    def get_stats(self) -> Dict:
        """
        Get filter configuration statistics.

        Returns:
            Dict with filter configuration
        """
        return {
            "keywords": self.keywords,
            "exclude_keywords": self.exclude_keywords,
            "institution_types": self.institution_types,
            "budget_min": self.budget_min,
            "budget_max": self.budget_max,
            "max_age_days": self.max_age_days,
            "custom_rules_count": len(self.custom_rules)
        }


# Global filter instance (can be customized by app.py at startup)
_default_filter = NoticeFilter()


def get_default_filter() -> NoticeFilter:
    """Get the global default filter instance."""
    return _default_filter


def set_default_filter(filter_instance: NoticeFilter):
    """Set the global default filter instance."""
    global _default_filter
    _default_filter = filter_instance


def apply_filters(notice: Dict, filter_instance: Optional[NoticeFilter] = None) -> bool:
    """
    Convenience function to apply filters to a notice.

    Args:
        notice: Notice dictionary from G2BAPIClient
        filter_instance: Optional custom filter instance (uses default if None)

    Returns:
        True if notice passes all filters, False otherwise
    """
    if filter_instance is None:
        filter_instance = get_default_filter()

    return filter_instance.apply(notice)
