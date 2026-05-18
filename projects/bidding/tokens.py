"""
Token helpers for the one-click decision URLs embedded in digest emails.

Both ``app.py`` (verifier) and ``notifier.py`` (issuer) import from here so
they agree on the encoding without circular imports.

Token format: itsdangerous URLSafeTimedSerializer payload of
``"{notice_id}:{transition_value}"``. Single-use (Decision.used_at gates
replay), 7-day expiry.
"""

from __future__ import annotations

import os

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from models import TransitionType

TOKEN_MAX_AGE_SECONDS = 7 * 24 * 3600
_TOKEN_SALT = "bidding-decide-v1"


def _serializer() -> URLSafeTimedSerializer:
    secret = os.getenv("DECIDE_TOKEN_SECRET")
    if not secret:
        raise RuntimeError("DECIDE_TOKEN_SECRET env var not set")
    return URLSafeTimedSerializer(secret, salt=_TOKEN_SALT)


def make_decision_token(notice_id: int, transition: TransitionType) -> str:
    """Generate a single-use 7-day token for one (notice, transition) pair."""
    return _serializer().dumps(f"{notice_id}:{transition.value}")


def verify_decision_token(token: str) -> tuple[int, TransitionType]:
    """
    Decode and validate. Returns (notice_id, transition).
    Raises ``ValueError`` on expiry, bad signature, or malformed payload.
    """
    try:
        payload = _serializer().loads(token, max_age=TOKEN_MAX_AGE_SECONDS)
    except SignatureExpired as exc:
        raise ValueError("expired") from exc
    except BadSignature as exc:
        raise ValueError("invalid_signature") from exc
    try:
        nid_str, action_str = payload.split(":", 1)
        return int(nid_str), TransitionType(action_str)
    except (ValueError, KeyError) as exc:
        raise ValueError("malformed") from exc
