"""
Fetches papers from arXiv and stores them idempotently
"""

import re
import uuid

import arxiv
import psycopg

from core.config import get_arxiv_categories, get_ingestion_max_results
from core.arxiv_text import format_arxiv_display_text
from core.db import get_database_url
from core.logging import get_logger
from core.pipeline_progress import set_step

logger = get_logger(__name__)

UPSERT_PAPER_SQL = """
INSERT INTO papers (
    arxiv_id,
    title,
    abstract,
    authors,
    published_at,
    updated_at,
    pdf_url,
    entry_url,
    categories
)
VALUES (
    %(arxiv_id)s,
    %(title)s,
    %(abstract)s,
    %(authors)s,
    %(published_at)s,
    %(updated_at)s,
    %(pdf_url)s,
    %(entry_url)s,
    %(categories)s
)
ON CONFLICT (arxiv_id)
DO UPDATE SET
    title = EXCLUDED.title,
    abstract = EXCLUDED.abstract,
    authors = EXCLUDED.authors,
    published_at = EXCLUDED.published_at,
    updated_at = EXCLUDED.updated_at,
    pdf_url = EXCLUDED.pdf_url,
    entry_url = EXCLUDED.entry_url,
    categories = EXCLUDED.categories;
"""

INSERT_RUN_SQL = """
INSERT INTO runs (run_id, status, category, max_results)
VALUES (%s, 'running', %s, %s);
"""

COMPLETE_RUN_SQL = """
UPDATE runs
SET status = 'completed',
    fetched_count = %s,
    saved_count = %s,
    finished_at = NOW()
WHERE run_id = %s;
"""

FAIL_RUN_SQL = """
UPDATE runs
SET status = 'failed',
    finished_at = NOW(),
    error_message = %s
WHERE run_id = %s;
"""

FETCH_RUN_CATEGORIES_SQL = """
SELECT run_id::text, category
FROM runs
WHERE run_id::text = ANY(%s);
"""


def fetch_papers(
    category: str = "cs.AI",
    max_results: int | None = None,
    # SubmittedDate sorts by the v1 original submission date (paper.published /
    # published_at), NOT by latest version activity. Ranking recency windows
    # (7d / 30d / 1y) use the same published_at clock. Do not switch this to
    # LastUpdatedDate, which would order by paper.updated/updated_at and
    # silently desync ingest from ranking. max_results is fetch size only.
    sort_by: arxiv.SortCriterion = arxiv.SortCriterion.SubmittedDate,
    sort_order: arxiv.SortOrder = arxiv.SortOrder.Descending,
    *,
    client: arxiv.Client | None = None,
):
    resolved_max_results = (
        get_ingestion_max_results() if max_results is None else max_results
    )
    resolved_client = client or arxiv.Client(delay_seconds=3.0, num_retries=5)
    search = arxiv.Search(
        query=f"cat:{category}",
        max_results=resolved_max_results,
        sort_by=sort_by,
        sort_order=sort_order,
    )

    return list(resolved_client.results(search))


def clean_id(arxiv_id: str) -> str:
    return re.sub(r"v\d+$", "", arxiv_id)


def save_papers(papers: list[arxiv.Result]) -> int:
    rows = [
        {
            "arxiv_id": clean_id(paper.get_short_id()),
            "title": format_arxiv_display_text(paper.title),
            "abstract": format_arxiv_display_text(paper.summary),
            "authors": [str(author) for author in paper.authors],
            "published_at": paper.published,
            "updated_at": paper.updated,
            "pdf_url": paper.pdf_url,
            "entry_url": paper.entry_id,
            "categories": paper.categories,
        }
        for paper in papers
    ]
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.executemany(UPSERT_PAPER_SQL, rows)
    return len(rows)


def start_run(category: str, max_results: int) -> str:
    run_id = str(uuid.uuid4())

    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(INSERT_RUN_SQL, (run_id, category, max_results))

    return run_id


def complete_run(run_id: str, fetched_count: int, saved_count: int) -> None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(COMPLETE_RUN_SQL, (fetched_count, saved_count, run_id))


def fail_run(run_id: str, error_message: str) -> None:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(FAIL_RUN_SQL, (error_message, run_id))


def run_ingestion(
    categories: list[str] | None = None, max_results: int | None = None
) -> list[str]:
    if categories is None:
        categories = get_arxiv_categories()
    resolved_max_results = (
        get_ingestion_max_results() if max_results is None else max_results
    )

    run_ids = []
    total_categories = len(categories)
    client = arxiv.Client(delay_seconds=3.0, num_retries=5)

    for index, category in enumerate(categories):
        set_step(
            "ingestion",
            detail=f"{index + 1}/{total_categories}: {category}…",
        )
        run_id = start_run(category, resolved_max_results)

        try:
            papers = fetch_papers(
                category=category,
                max_results=resolved_max_results,
                client=client,
            )
            saved_count = save_papers(papers)
            complete_run(run_id, len(papers), saved_count)
            logger.info(
                "Category ingestion completed",
                extra={
                    "event": "pipeline.step.completed",
                    "step": "ingestion",
                    "run_id": run_id,
                    "category": category,
                    "fetched_count": len(papers),
                    "saved_count": saved_count,
                },
            )
        except Exception as error:
            fail_run(run_id, str(error))
            logger.exception(
                "Category ingestion failed",
                extra={
                    "event": "pipeline.step.failed",
                    "step": "ingestion",
                    "run_id": run_id,
                    "category": category,
                    "error_type": error.__class__.__name__,
                },
            )

        run_ids.append(run_id)

    return run_ids


def fetch_run_categories(run_ids: list[str], conn=None) -> dict[str, str]:
    if not run_ids:
        return {}

    if conn is not None:
        with conn.cursor() as cur:
            cur.execute(FETCH_RUN_CATEGORIES_SQL, (run_ids,))
            rows = cur.fetchall()
        return {row[0]: row[1] for row in rows}

    with psycopg.connect(get_database_url()) as owned_conn:
        with owned_conn.cursor() as cur:
            cur.execute(FETCH_RUN_CATEGORIES_SQL, (run_ids,))
            rows = cur.fetchall()
    return {row[0]: row[1] for row in rows}


if __name__ == "__main__":
    run_ingestion()
