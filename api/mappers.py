"""
Mapping for query rows and API payload fragments
"""

from api.queries.daily_picks import DailyPickRow
from api.queries.metrics import MetricsRowSet
from api.queries.profiles import ProfileSummaryRow
from core.arxiv_text import format_arxiv_display_text


def to_public_pick(row: DailyPickRow) -> dict:
    description = row.description
    return {
        "rank": row.rank,
        "arxiv_id": row.arxiv_id,
        "title": format_arxiv_display_text(row.title),
        "abstract": format_arxiv_display_text(row.abstract),
        "description": format_arxiv_display_text(description) if description else None,
        "pdf_url": row.pdf_url,
        "final_score": row.final_score,
        "published_at": row.published_at,
        "authors": list(row.authors or []),
    }


def to_debug_pick(row: DailyPickRow) -> dict:
    return {
        **to_public_pick(row),
        "run_id": row.run_id,
        "category": row.category,
        "generated_at": row.generated_at,
        "base_dense_score": row.base_dense_score,
        "keyword_boost": row.keyword_boost,
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
        "preference_updated_at": row.preference_updated_at,
        "keywords": list(row.keywords),
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
