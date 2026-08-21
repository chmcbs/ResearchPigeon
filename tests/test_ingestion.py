"""
Tests the ingestion pipeline
"""

from unittest.mock import MagicMock, Mock

import pytest

from core import ingestion
from core.ingestion import clean_id


def test_clean_id_removes_arxiv_version_suffix():
    assert clean_id("2401.12345v2") == "2401.12345"


def test_clean_id_leaves_unversioned_id_unchanged():
    assert clean_id("2401.12345") == "2401.12345"


def test_run_ingestion_completes_run(monkeypatch):
    papers = [object(), object()]

    monkeypatch.setattr(ingestion, "start_run", Mock(return_value="run-123"))
    monkeypatch.setattr(ingestion, "fetch_papers", Mock(return_value=papers))
    monkeypatch.setattr(ingestion, "save_papers", Mock(return_value=2))
    monkeypatch.setattr(ingestion, "complete_run", Mock())
    monkeypatch.setattr(ingestion, "fail_run", Mock())

    run_ids = ingestion.run_ingestion(["cs.AI"], 10)

    assert run_ids == ["run-123"]
    ingestion.start_run.assert_called_once_with("cs.AI", 10)
    ingestion.fetch_papers.assert_called_once()
    assert ingestion.fetch_papers.call_args.kwargs["category"] == "cs.AI"
    assert ingestion.fetch_papers.call_args.kwargs["max_results"] == 10
    assert ingestion.fetch_papers.call_args.kwargs["client"] is not None
    ingestion.save_papers.assert_called_once_with(papers)
    ingestion.complete_run.assert_called_once_with("run-123", 2, 2)
    ingestion.fail_run.assert_not_called()


def test_fetch_papers_sorts_by_submitted_date(monkeypatch):
    captured = {}

    class FakeSearch:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    fake_client = Mock()
    fake_client.results.return_value = []
    monkeypatch.setattr(ingestion.arxiv, "Search", FakeSearch)

    ingestion.fetch_papers(category="cs.AI", max_results=10, client=fake_client)

    assert captured["query"] == "cat:cs.AI"
    assert captured["max_results"] == 10
    assert captured["sort_by"] == ingestion.arxiv.SortCriterion.SubmittedDate
    fake_client.results.assert_called_once()


def test_run_ingestion_marks_run_failed(monkeypatch):
    error = RuntimeError("arxiv failed")

    monkeypatch.setattr(ingestion, "start_run", Mock(return_value="run-123"))
    monkeypatch.setattr(ingestion, "fetch_papers", Mock(side_effect=error))
    monkeypatch.setattr(ingestion, "save_papers", Mock())
    monkeypatch.setattr(ingestion, "complete_run", Mock())
    monkeypatch.setattr(ingestion, "fail_run", Mock())

    run_ids = ingestion.run_ingestion(["cs.AI"], 10)

    assert run_ids == ["run-123"]
    ingestion.fail_run.assert_called_once_with("run-123", "arxiv failed")
    ingestion.save_papers.assert_not_called()
    ingestion.complete_run.assert_not_called()


def test_run_ingestion_continues_after_category_failure(monkeypatch):
    papers = [object(), object()]

    monkeypatch.setattr(ingestion, "start_run", Mock(side_effect=["run-1", "run-2"]))
    monkeypatch.setattr(
        ingestion,
        "fetch_papers",
        Mock(
            side_effect=[RuntimeError("failed"), papers],
        ),
    )
    monkeypatch.setattr(ingestion, "save_papers", Mock(return_value=2))
    monkeypatch.setattr(ingestion, "complete_run", Mock())
    monkeypatch.setattr(ingestion, "fail_run", Mock())

    run_ids = ingestion.run_ingestion(["cs.AI", "cs.CL"], 10)

    assert run_ids == ["run-1", "run-2"]
    ingestion.fail_run.assert_called_once_with("run-1", "failed")
    ingestion.complete_run.assert_called_once_with("run-2", 2, 2)


def test_save_papers_maps_arxiv_results_to_database_rows(monkeypatch):
    paper = Mock()
    paper.get_short_id.return_value = "2401.12345v2"
    paper.title = "Test Paper"
    paper.summary = "Test abstract"
    paper.authors = ["Alice", "Bob"]
    paper.published = "published-date"
    paper.updated = "updated-date"
    paper.pdf_url = "https://example.com/paper.pdf"
    paper.entry_id = "https://arxiv.org/abs/2401.12345"
    paper.categories = ["cs.AI"]

    cursor = MagicMock()
    connection = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor

    connect = MagicMock()
    connect.return_value.__enter__.return_value = connection
    monkeypatch.setattr(ingestion.psycopg, "connect", connect)

    saved_count = ingestion.save_papers([paper])

    assert saved_count == 1
    cursor.executemany.assert_called_once()
    rows = cursor.executemany.call_args.args[1]
    assert rows == [
        {
            "arxiv_id": "2401.12345",
            "title": "Test Paper",
            "abstract": "Test abstract",
            "authors": ["Alice", "Bob"],
            "published_at": "published-date",
            "updated_at": "updated-date",
            "pdf_url": "https://example.com/paper.pdf",
            "entry_url": "https://arxiv.org/abs/2401.12345",
            "categories": ["cs.AI"],
        }
    ]
