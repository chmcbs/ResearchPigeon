"""
Scheduled digest generation for all subscribed users
"""

from email.message import EmailMessage

from core.db import connection_scope
from core.logging import configure_logging, get_logger
from core.config import (
    get_debug_admin_emails,
    get_embedding_limit,
    get_email_from,
    get_ingestion_max_results,
    get_product_name,
    is_email_delivery_configured,
)
from core.pipeline import run_recommendations_for_profiles, run_shared_pipeline_steps
from core.descriptions import run_description_batch_for_recommendations
from core.digest_email import deliver_digest_email_for_user
from core.email import deliver_email_message
from core.profiles import list_digest_categories, list_digest_selected_profile_ids

logger = get_logger(__name__)

LIST_DIGEST_USER_IDS_SQL = """
SELECT DISTINCT up.user_id
FROM user_profiles up
LEFT JOIN user_email_settings ues ON ues.user_id = up.user_id
WHERE up.digest_enabled = TRUE
  AND COALESCE(ues.digest_subscribed, TRUE) = TRUE
ORDER BY up.user_id ASC;
"""


def list_users_with_digest_selection(conn=None) -> list[str]:
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(LIST_DIGEST_USER_IDS_SQL)
            rows = cur.fetchall()
    return [row[0] for row in rows]


def _notify_admins_of_blurb_failure(*, run_ids: list[str], error: Exception) -> None:
    admin_emails = sorted(get_debug_admin_emails())
    if not admin_emails:
        logger.warning(
            "LLM blurb batch failed but no admin recipients are configured",
            extra={
                "event": "llm.batch.admin_alert_skipped",
                "run_ids": run_ids,
            },
        )
        return
    if not is_email_delivery_configured():
        logger.warning(
            "LLM blurb batch failed but SMTP is not configured",
            extra={
                "event": "llm.batch.admin_alert_skipped_unconfigured",
                "run_ids": run_ids,
            },
        )
        return

    subject = f"[{get_product_name()}] LLM blurb batch failed"
    body = (
        "The digest pipeline failed to generate LLM descriptions.\n\n"
        f"Run IDs: {', '.join(run_ids) if run_ids else 'none'}\n"
        f"Error: {error.__class__.__name__}: {str(error).strip() or 'unknown'}\n\n"
        "User digests continued to send without descriptions."
    )

    for admin_email in admin_emails:
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = get_email_from()
        message["To"] = admin_email
        message.set_content(body)
        try:
            deliver_email_message(message)
        except Exception:
            logger.exception(
                "Failed to send LLM blurb failure alert",
                extra={
                    "event": "llm.batch.admin_alert_failed",
                    "to_email": admin_email,
                    "run_ids": run_ids,
                },
            )


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
            ingest_categories = list_digest_categories(conn=conn)
            shared = run_shared_pipeline_steps(
                categories=ingest_categories,
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
                "description_batch": {},
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

    description_batch = {}
    if shared_run_ids and users_to_process:
        try:
            description_batch = run_description_batch_for_recommendations(
                run_ids=shared_run_ids,
                conn=conn,
            )
        except Exception as error:
            logger.exception(
                "Daily digest blurb batch failed",
                extra={
                    "event": "llm.batch.failed",
                    "run_ids": shared_run_ids,
                    "error_type": error.__class__.__name__,
                },
            )
            _notify_admins_of_blurb_failure(run_ids=shared_run_ids, error=error)

    if shared_run_ids:
        for entry in results:
            if entry.get("status") != "succeeded":
                continue
            email_result = deliver_digest_email_for_user(
                user_id=entry["user_id"],
                profile_ids=entry["profile_ids"],
                run_ids=shared_run_ids,
                conn=conn,
            )
            entry["email_status"] = email_result["status"]
            entry["email_error"] = email_result["error_message"]

    payload = {
        "users_seen": len(user_ids),
        "users_succeeded": succeeded,
        "users_failed": failed,
        "users_skipped": skipped,
        "description_batch": description_batch,
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
