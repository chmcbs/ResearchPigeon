"""
Runs the end-to-end recommendation pipeline
"""

from core.config import (
    get_embedding_limit,
    get_ingestion_max_results,
)
from core.embeddings import run_embeddings
from core.ingestion import fetch_run_categories, run_ingestion
from core.logging import configure_logging, get_logger
from core.descriptions import run_description_batch_for_recommendations
from core.pipeline_progress import set_step
from core.profiles import categories_for_profile_ids, get_profile
from core.recommendations import generate_recommendations

logger = get_logger(__name__)


def _stringify_error(error: Exception) -> str:
    text = str(error).strip()
    return text or error.__class__.__name__


def _normalize_profile_ids(
    profile_id: str | None,
    profile_ids: list[str] | None,
) -> list[str]:
    if profile_id is not None and profile_ids is not None:
        raise ValueError("provide either profile_id or profile_ids, not both")

    if profile_ids is not None:
        target_profile_ids = list(dict.fromkeys(profile_ids))
        if not target_profile_ids:
            raise ValueError("profile_ids must contain at least one profile")
    elif profile_id is not None:
        target_profile_ids = [profile_id]
    else:
        raise ValueError("provide either profile_id or profile_ids")

    return target_profile_ids


def _matching_run_ids_for_profile(
    *,
    user_id: str,
    profile_id: str,
    run_ids: list[str],
    run_categories: dict[str, str],
) -> list[str]:
    profile = get_profile(profile_id)
    if profile is None or profile.user_id != user_id:
        raise ValueError("profile not found for user")

    return [
        run_id
        for run_id in run_ids
        if run_categories.get(run_id) == profile.category
    ]


def run_shared_pipeline_steps(
    *,
    categories: list[str] | None = None,
    max_results: int | None = None,
    embedding_limit: int | None = None,
) -> dict:
    configure_logging()
    resolved_max_results = (
        get_ingestion_max_results() if max_results is None else max_results
    )
    resolved_embedding_limit = (
        get_embedding_limit() if embedding_limit is None else embedding_limit
    )

    set_step("ingestion")
    logger.info(
        "Running ingestion",
        extra={
            "event": "pipeline.step.started",
            "step": "ingestion",
            "max_results": resolved_max_results,
        },
    )
    run_ids = run_ingestion(
        categories=categories,
        max_results=resolved_max_results,
    )
    logger.info(
        "Ingestion finished",
        extra={
            "event": "pipeline.step.completed",
            "step": "ingestion",
            "run_count": len(run_ids),
            "run_ids": run_ids,
        },
    )

    set_step("embeddings")
    logger.info(
        "Generating embeddings",
        extra={
            "event": "pipeline.step.started",
            "step": "embeddings",
            "embedding_limit": resolved_embedding_limit,
        },
    )
    embedded_count = run_embeddings(limit=resolved_embedding_limit)
    set_step("embeddings", detail=f"Embedded {embedded_count} paper(s)")
    logger.info(
        "Embeddings finished",
        extra={
            "event": "pipeline.step.completed",
            "step": "embeddings",
            "embedded_count": embedded_count,
        },
    )

    return {
        "run_ids": run_ids,
        "embedded_count": embedded_count,
    }


def run_recommendations_for_profiles(
    *,
    user_id: str,
    profile_ids: list[str],
    run_ids: list[str],
) -> dict:
    target_profile_ids = _normalize_profile_ids(profile_id=None, profile_ids=profile_ids)
    run_categories = fetch_run_categories(run_ids)

    set_step("recommendations")
    logger.info(
        "Generating recommendations",
        extra={
            "event": "pipeline.step.started",
            "step": "recommendations",
            "user_id": user_id,
            "profile_ids": target_profile_ids,
            "run_ids": run_ids,
        },
    )

    recommendations_by_run_profile: dict[str, dict[str, list[dict]]] = {}
    recommendation_status_by_run_profile: dict[str, dict[str, dict]] = {}
    for target_profile_id in target_profile_ids:
        matching_run_ids = _matching_run_ids_for_profile(
            user_id=user_id,
            profile_id=target_profile_id,
            run_ids=run_ids,
            run_categories=run_categories,
        )
        if not matching_run_ids:
            logger.warning(
                "No ingestion run matches profile category",
                extra={
                    "event": "pipeline.step.skipped",
                    "step": "recommendations",
                    "user_id": user_id,
                    "profile_id": target_profile_id,
                    "run_ids": run_ids,
                },
            )
            continue

        for run_id in matching_run_ids:
            recommendations_by_run_profile.setdefault(run_id, {})
            recommendation_status_by_run_profile.setdefault(run_id, {})
            try:
                recommendations = generate_recommendations(
                    run_id,
                    user_id=user_id,
                    profile_id=target_profile_id,
                )
                recommendations_by_run_profile[run_id][
                    target_profile_id
                ] = recommendations
                recommendation_status_by_run_profile[run_id][target_profile_id] = {
                    "status": "succeeded",
                    "recommendation_count": len(recommendations),
                    "error_message": None,
                }
                logger.info(
                    "Recommendations saved",
                    extra={
                        "event": "pipeline.step.completed",
                        "step": "recommendations",
                        "run_id": run_id,
                        "profile_id": target_profile_id,
                        "recommendation_count": len(recommendations),
                    },
                )
            except Exception as error:
                recommendations_by_run_profile[run_id][target_profile_id] = []
                recommendation_status_by_run_profile[run_id][target_profile_id] = {
                    "status": "failed",
                    "recommendation_count": 0,
                    "error_message": _stringify_error(error),
                }
                logger.exception(
                    "Recommendation step failed",
                    extra={
                        "event": "pipeline.step.failed",
                        "step": "recommendations",
                        "run_id": run_id,
                        "profile_id": target_profile_id,
                        "error_type": error.__class__.__name__,
                    },
                )

    return {
        "recommendations_by_run_profile": recommendations_by_run_profile,
        "recommendation_status_by_run_profile": recommendation_status_by_run_profile,
    }


def run_pipeline(
    user_id: str,
    profile_id: str | None = None,
    profile_ids: list[str] | None = None,
    max_results: int | None = None,
    embedding_limit: int | None = None,
) -> dict:
    target_profile_ids = _normalize_profile_ids(
        profile_id=profile_id,
        profile_ids=profile_ids,
    )

    configure_logging()

    logger.info(
        "Pipeline started",
        extra={
            "event": "pipeline.started",
            "user_id": user_id,
            "profile_ids": target_profile_ids,
            "max_results": max_results,
            "embedding_limit": embedding_limit,
        },
    )

    ingest_categories = categories_for_profile_ids(
        user_id=user_id,
        profile_ids=target_profile_ids,
    )

    shared = run_shared_pipeline_steps(
        categories=ingest_categories,
        max_results=max_results,
        embedding_limit=embedding_limit,
    )
    recommendations = run_recommendations_for_profiles(
        user_id=user_id,
        profile_ids=target_profile_ids,
        run_ids=shared["run_ids"],
    )

    set_step("descriptions")
    description_batch = run_description_batch_for_recommendations(
        run_ids=shared["run_ids"],
        profile_ids=target_profile_ids,
    )
    succeeded = description_batch.get("succeeded", 0)
    if succeeded:
        set_step(
            "descriptions",
            detail=f"Wrote {succeeded} summary sentence(s)",
        )

    logger.info(
        "Pipeline finished",
        extra={
            "event": "pipeline.completed",
            "run_ids": shared["run_ids"],
            "embedded_count": shared["embedded_count"],
            "description_batch": description_batch,
        },
    )

    return {
        "run_ids": shared["run_ids"],
        "embedded_count": shared["embedded_count"],
        "description_batch": description_batch,
        **recommendations,
    }


if __name__ == "__main__":
    raise SystemExit(
        "Usage: import and call run_pipeline(user_id=..., profile_id=... or profile_ids=[...])"
    )
