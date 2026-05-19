"""
Scheduled digest generation for all subscribed users
"""

from core.db import connection_scope
from core.logging import configure_logging, get_logger
from core.config import (
    get_embedding_limit,
    get_ingestion_max_results,
)
from core.pipeline import run_recommendations_for_profiles, run_shared_pipeline_steps
from core.profiles import list_digest_selected_profile_ids

logger = get_logger(__name__)

LIST_DIGEST_USER_IDS_SQL = """
SELECT DISTINCT user_id
FROM user_profiles
WHERE digest_enabled = TRUE
ORDER BY user_id ASC;
"""


def list_users_with_digest_selection(conn=None) -> list[str]:
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LIST_DIGEST_USER_IDS_SQL)
            rows = cur.fetchall()
    return [row[0] for row in rows]


def run_daily_digest_for_all_users(
    *,
    max_results: int | None = None,
    embedding_limit: int | None = None,
    conn=None,
) -> dict:
    configure_logging()
    resolved_max_results = (
        get_ingestion_max_results() if max_results is None else max_results
    )
    resolved_embedding_limit = (
        get_embedding_limit() if embedding_limit is None else embedding_limit
    )
    user_ids = list_users_with_digest_selection(conn=conn)
    results: list[dict] = []
    succeeded = 0
    failed = 0
    skipped = 0
    users_to_process: list[tuple[str, list[str]]] = []

    logger.info(
        "Daily digest cron started",
        extra={
            "event": "cron.daily_digest.started",
            "user_count": len(user_ids),
        },
    )

    for user_id in user_ids:
        profile_ids = list_digest_selected_profile_ids(user_id=user_id, conn=conn)
        if not profile_ids:
            skipped += 1
            results.append(
                {
                    "user_id": user_id,
                    "status": "skipped",
                    "profile_ids": [],
                    "error_message": "no digest-selected profiles",
                }
            )
            continue
        users_to_process.append((user_id, profile_ids))

    shared_run_ids: list[str] = []
    if users_to_process:
        try:
            shared = run_shared_pipeline_steps(
                max_results=resolved_max_results,
                embedding_limit=resolved_embedding_limit,
            )
            shared_run_ids = shared["run_ids"]
        except Exception as error:
            message = str(error).strip() or error.__class__.__name__
            logger.exception(
                "Daily digest cron failed during shared pipeline steps",
                extra={"event": "cron.daily_digest.shared_failed"},
            )
            for user_id, profile_ids in users_to_process:
                failed += 1
                results.append(
                    {
                        "user_id": user_id,
                        "status": "failed",
                        "profile_ids": profile_ids,
                        "run_ids": [],
                        "error_message": message,
                    }
                )
            payload = {
                "users_seen": len(user_ids),
                "users_succeeded": succeeded,
                "users_failed": failed,
                "users_skipped": skipped,
                "results": results,
            }
            logger.info(
                "Daily digest cron finished",
                extra={
                    "event": "cron.daily_digest.completed",
                    **{key: payload[key] for key in payload if key != "results"},
                },
            )
            return payload

    for user_id, profile_ids in users_to_process:
        try:
            run_recommendations_for_profiles(
                user_id=user_id,
                profile_ids=profile_ids,
                run_ids=shared_run_ids,
            )
            succeeded += 1
            results.append(
                {
                    "user_id": user_id,
                    "status": "succeeded",
                    "profile_ids": profile_ids,
                    "run_ids": shared_run_ids,
                    "error_message": None,
                }
            )
        except Exception as error:
            failed += 1
            message = str(error).strip() or error.__class__.__name__
            logger.exception(
                "Daily digest cron failed for user",
                extra={
                    "event": "cron.daily_digest.user_failed",
                    "user_id": user_id,
                    "profile_ids": profile_ids,
                },
            )
            results.append(
                {
                    "user_id": user_id,
                    "status": "failed",
                    "profile_ids": profile_ids,
                    "run_ids": shared_run_ids,
                    "error_message": message,
                }
            )

    payload = {
        "users_seen": len(user_ids),
        "users_succeeded": succeeded,
        "users_failed": failed,
        "users_skipped": skipped,
        "results": results,
    }
    logger.info(
        "Daily digest cron finished",
        extra={
            "event": "cron.daily_digest.completed",
            **{key: payload[key] for key in payload if key != "results"},
        },
    )
    return payload


def main() -> None:
    result = run_daily_digest_for_all_users()
    print(result)


if __name__ == "__main__":
    main()
