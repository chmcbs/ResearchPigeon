"""
User-level digest email subscription settings
"""

import hashlib
import hmac
from datetime import UTC, datetime

from core.config import get_app_base_url, get_email_unsubscribe_secret
from core.db import connection_scope

GET_EMAIL_SETTINGS_SQL = """
SELECT digest_subscribed, unsubscribed_at
FROM user_email_settings
WHERE user_id = %s;
"""

INSERT_EMAIL_SETTINGS_SQL = """
INSERT INTO user_email_settings (
    user_id,
    digest_subscribed,
    unsubscribe_token_hash
)
VALUES (%s, TRUE, %s)
ON CONFLICT (user_id) DO NOTHING;
"""

UPDATE_DIGEST_SUBSCRIBED_SQL = """
UPDATE user_email_settings
SET
    digest_subscribed = %s,
    unsubscribed_at = %s,
    updated_at = NOW()
WHERE user_id = %s
RETURNING digest_subscribed, unsubscribed_at;
"""

LOOKUP_USER_BY_TOKEN_HASH_SQL = """
SELECT user_id
FROM user_email_settings
WHERE unsubscribe_token_hash = %s;
"""


def _token_hash(value: str) -> str:
    return hashlib.sha256(value.strip().encode("utf-8")).hexdigest()


def derive_unsubscribe_token(user_id: str) -> str:
    normalized = user_id.strip().lower()
    return hmac.new(
        get_email_unsubscribe_secret().encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def build_unsubscribe_url(
    user_id: str,
    *,
    app_base_url: str | None = None,
) -> str:
    base_url = (app_base_url or get_app_base_url()).rstrip("/")
    token = derive_unsubscribe_token(user_id)
    return f"{base_url}/email/unsubscribe?token={token}"


def build_resubscribe_url(
    user_id: str,
    *,
    app_base_url: str | None = None,
) -> str:
    base_url = (app_base_url or get_app_base_url()).rstrip("/")
    token = derive_unsubscribe_token(user_id)
    return f"{base_url}/email/resubscribe?token={token}"


def ensure_email_settings(user_id: str, conn=None) -> None:
    token_hash = _token_hash(derive_unsubscribe_token(user_id))
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(INSERT_EMAIL_SETTINGS_SQL, (user_id, token_hash))


def get_digest_subscribed(user_id: str, conn=None) -> bool:
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(GET_EMAIL_SETTINGS_SQL, (user_id,))
            row = cur.fetchone()

    if row is None:
        return True
    return bool(row[0])


def get_email_settings(user_id: str, conn=None) -> dict:
    ensure_email_settings(user_id, conn=conn)
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(GET_EMAIL_SETTINGS_SQL, (user_id,))
            row = cur.fetchone()

    if row is None:
        return {"digest_subscribed": True, "unsubscribed_at": None}
    return {
        "digest_subscribed": bool(row[0]),
        "unsubscribed_at": row[1],
    }


def set_digest_subscribed(
    user_id: str,
    *,
    digest_subscribed: bool,
    conn=None,
) -> dict:
    ensure_email_settings(user_id, conn=conn)
    unsubscribed_at = None if digest_subscribed else datetime.now(UTC)

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPDATE_DIGEST_SUBSCRIBED_SQL,
                (digest_subscribed, unsubscribed_at, user_id),
            )
            row = cur.fetchone()

    if row is None:
        raise ValueError("email settings not found for user")
    return {
        "digest_subscribed": bool(row[0]),
        "unsubscribed_at": row[1],
    }


def resolve_user_id_from_token(token: str, conn=None) -> str | None:
    if not token or not token.strip():
        return None

    token_hash = _token_hash(token)
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LOOKUP_USER_BY_TOKEN_HASH_SQL, (token_hash,))
            row = cur.fetchone()

    if row is None:
        return None
    return row[0]


def unsubscribe_by_token(token: str, conn=None) -> str | None:
    user_id = resolve_user_id_from_token(token, conn=conn)
    if user_id is None:
        return None
    set_digest_subscribed(user_id, digest_subscribed=False, conn=conn)
    return user_id


def resubscribe_by_token(token: str, conn=None) -> str | None:
    user_id = resolve_user_id_from_token(token, conn=conn)
    if user_id is None:
        return None
    set_digest_subscribed(user_id, digest_subscribed=True, conn=conn)
    return user_id
