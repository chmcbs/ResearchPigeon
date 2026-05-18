"""
Runs the end-to-end recommendation pipeline
"""

from core.config import DEFAULT_USER_ID
from core.embeddings import run_embeddings
from core.ingestion import run_ingestion
from core.recommendations import generate_recommendations
from core.schema import main as setup_database


def _stringify_error(error: Exception) -> str:
    text = str(error).strip()
    return text or error.__class__.__name__


def run_pipeline(
    user_id: str = DEFAULT_USER_ID,
    profile_id: str | None = None,
    profile_ids: list[str] | None = None,
    max_results: int = 150,
    embedding_limit: int = 600,
) -> dict:
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

    print("1/4 Setting up database schema...")
    setup_database()

    print("2/4 Running ingestion...")
    run_ids = run_ingestion(max_results=max_results)
    print(f"Ingestion produced {len(run_ids)} run(s)")

    print("3/4 Generating embeddings...")
    embedded_count = run_embeddings(limit=embedding_limit)
    print(f"Embedded {embedded_count} paper(s)")

    print("4/4 Generating recommendations...")
    recommendations_by_run_profile: dict[str, dict[str, list[dict]]] = {}
    recommendation_status_by_run_profile: dict[str, dict[str, dict]] = {}
    for run_id in run_ids:
        recommendations_by_run_profile[run_id] = {}
        recommendation_status_by_run_profile[run_id] = {}
        for target_profile_id in target_profile_ids:
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
                print(
                    f"Run {run_id}, profile {target_profile_id}: "
                    f"saved {len(recommendations)} recommendation(s)"
                )
            except Exception as error:
                recommendations_by_run_profile[run_id][target_profile_id] = []
                recommendation_status_by_run_profile[run_id][target_profile_id] = {
                    "status": "failed",
                    "recommendation_count": 0,
                    "error_message": _stringify_error(error),
                }
                print(
                    f"Run {run_id}, profile {target_profile_id}: "
                    f"recommendation step failed: {error}"
                )

    recommendations_by_run = {}
    if len(target_profile_ids) == 1:
        only_profile_id = target_profile_ids[0]
        for run_id in run_ids:
            recommendations_by_run[run_id] = recommendations_by_run_profile[run_id][
                only_profile_id
            ]
    else:
        for run_id in run_ids:
            flattened = []
            for target_profile_id in target_profile_ids:
                for recommendation in recommendations_by_run_profile[run_id][
                    target_profile_id
                ]:
                    flattened.append(
                        {
                            "profile_id": target_profile_id,
                            **recommendation,
                        }
                    )
            recommendations_by_run[run_id] = flattened

    return {
        "run_ids": run_ids,
        "embedded_count": embedded_count,
        "recommendations_by_run": recommendations_by_run,
        "recommendations_by_run_profile": recommendations_by_run_profile,
        "recommendation_status_by_run_profile": recommendation_status_by_run_profile,
    }


if __name__ == "__main__":
    run_pipeline()
