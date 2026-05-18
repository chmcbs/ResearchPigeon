"""
Mapping for query rows and API payload fragments
"""

from api.queries.daily_picks import DailyPickRow
from api.queries.metrics import LatestRunRow, MetricsRowSet
from api.queries.profiles import ProfileSummaryRow


def to_public_pick(row: DailyPickRow) -> dict:
    return {
        "rank": row.rank,
        "arxiv_id": row.arxiv_id,
        "title": row.title,
        "abstract": row.abstract,
        "pdf_url": row.pdf_url,
        "final_score": row.final_score,
    }


def to_debug_pick(row: DailyPickRow) -> dict:
    return {
        **to_public_pick(row),
        "run_id": row.run_id,
        "category": row.category,
        "generated_at": row.generated_at,
        "base_dense_score": row.base_dense_score,
        "keyword_boost": row.keyword_boost,
        "final_score": row.final_score,
        "candidate_window": row.candidate_window,
        "fallback_stage": row.fallback_stage,
    }


def to_profile_summary(row: ProfileSummaryRow) -> dict:
    return {
        "profile_id": row.profile_id,
        "user_id": row.user_id,
        "profile_slot": row.profile_slot,
        "profile_name": row.profile_name,
        "category": row.category,
        "interest_sentence": row.interest_sentence,
        "digest_enabled": row.digest_enabled,
        "created_at": row.created_at,
        "preference_updated_at": getattr(row, "preference_updated_at", None),
        "keywords": list(getattr(row, "keywords", [])),
    }


def to_metrics_payload(metrics_rows: MetricsRowSet) -> dict:
    return {
        "run_status_counts": metrics_rows.run_status_counts,
        "latest_runs": [
            {
                "run_id": row.run_id,
                "status": row.status,
                "category": row.category,
                "max_results": row.max_results,
                "fetched_count": row.fetched_count,
                "saved_count": row.saved_count,
                "started_at": row.started_at,
                "finished_at": row.finished_at,
                "error_message": row.error_message,
            }
            for row in metrics_rows.latest_runs
        ],
        "total_recommendations": metrics_rows.total_recommendations,
        "recommendations_by_profile": metrics_rows.recommendations_by_profile,
    }
