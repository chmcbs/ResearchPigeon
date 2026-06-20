"""
Tests for LLM description batch helpers
"""

import io
import json
import time
from contextlib import contextmanager
from unittest.mock import MagicMock, Mock
from urllib import error as urllib_error

import pytest

from core.descriptions import (
    LLMProviderError,
    MockLLMProvider,
    LLMResult,
    OpenAIProvider,
    PaperCandidate,
    _extract_openai_text,
    _generate_with_retries,
    _build_prompt,
    _process_paper,
    _validation_failures,
    get_llm_provider,
    repeats_title,
    run_description_batch_for_recommendations,
)


@contextmanager
def _fake_scope(connection):
    yield connection


@pytest.fixture(autouse=True)
def _default_paper_claim(monkeypatch):
    @contextmanager
    def _claim(_arxiv_id: str):
        yield True

    monkeypatch.setattr("core.descriptions._paper_generation_claim", _claim)
    monkeypatch.setattr("core.descriptions._description_exists", Mock(return_value=False))


def test_repeats_title_detects_high_overlap():
    title = "Scaling Laws for Neural Language Models"
    description = "Scaling laws for neural language models on large datasets"
    assert repeats_title(title, description) is True


def test_repeats_title_allows_complementary_sentence():
    title = "Scaling Laws for Neural Language Models"
    description = (
        "Empirical analysis shows loss scales predictably with compute, data, and model size."
    )
    assert repeats_title(title, description) is False


def test_build_prompt_includes_title_retry_note():
    prompt = _build_prompt(
        title="Example Title",
        abstract="Example abstract body.",
        retry_reasons=frozenset({"title"}),
    )
    assert "repeated the title" in prompt
    assert "Example Title" in prompt


def test_build_prompt_includes_empty_retry_note():
    prompt = _build_prompt(
        title="Example Title",
        abstract="Example abstract body.",
        retry_reasons=frozenset({"empty"}),
    )
    assert "was empty" in prompt
    assert "Output exactly one sentence" in prompt
    assert "repeated the title" not in prompt


def test_build_prompt_includes_length_retry_note():
    prompt = _build_prompt(
        title="Example Title",
        abstract="Example abstract body.",
        retry_reasons=frozenset({"length"}),
    )
    assert "too long" in prompt
    assert "no more than 35 words" in prompt
    assert "was empty" not in prompt


def test_build_prompt_includes_both_retry_notes():
    prompt = _build_prompt(
        title="Example Title",
        abstract="Example abstract body.",
        retry_reasons=frozenset({"title", "length"}),
    )
    assert "repeated the title" in prompt
    assert "no more than 35 words" in prompt


def test_validation_failures_detects_empty_length_and_title():
    title = "Transformers Improve Benchmark Accuracy"
    too_long = " ".join(["word"] * 51)
    assert _validation_failures(title=title, description=too_long) == frozenset(
        {"length"}
    )
    assert _validation_failures(
        title=title,
        description="Transformers improve benchmark accuracy on standard tasks.",
    ) == frozenset({"title"})
    assert _validation_failures(title=title, description="") == frozenset({"empty"})


def test_get_llm_provider_returns_mock():
    provider = get_llm_provider("mock")
    assert provider.provider_name == "mock"


def test_get_llm_provider_returns_openai():
    provider = get_llm_provider("openai")
    assert provider.provider_name == "openai"


def test_extract_openai_text_reads_output_text_field():
    body = {"output_text": "Generated summary sentence."}
    assert _extract_openai_text(body) == "Generated summary sentence."


def test_generate_with_retries_retries_retryable_errors(monkeypatch):
    provider = MockLLMProvider()
    provider.generate = Mock(
        side_effect=[
            LLMProviderError("temporary", retryable=True),
            LLMResult(text="Recovered sentence.", input_tokens=5, output_tokens=3, latency_ms=1),
        ]
    )
    sleep_mock = Mock()
    monkeypatch.setattr("core.descriptions.time.sleep", sleep_mock)

    result = _generate_with_retries(
        provider,
        "prompt",
        started_at=time.monotonic(),
        request_timeout_s=30.0,
    )

    assert result.text == "Recovered sentence."
    assert provider.generate.call_count == 2
    sleep_mock.assert_called_once()


def test_openai_provider_parses_response_usage(monkeypatch):
    class _FakeHTTPResponse:
        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def read(self) -> bytes:
            return json.dumps(self._payload).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> bool:
            return False

    payload = {
        "output_text": "Benchmarks compare robustness under distribution shifts.",
        "usage": {"input_tokens": 11, "output_tokens": 7},
    }
    monkeypatch.setattr(
        "core.descriptions.urllib_request.urlopen",
        Mock(return_value=_FakeHTTPResponse(payload)),
    )
    provider = OpenAIProvider(
        api_key="test-key",
        base_url="https://api.openai.com/v1",
        model="gpt-4.1-nano",
    )

    result = provider.generate("prompt", timeout_s=5)
    assert result.text.startswith("Benchmarks compare")
    assert result.input_tokens == 11
    assert result.output_tokens == 7


def test_openai_provider_marks_429_retryable(monkeypatch):
    http_error = urllib_error.HTTPError(
        url="https://api.openai.com/v1/responses",
        code=429,
        msg="Too Many Requests",
        hdrs=None,
        fp=io.BytesIO(
            b'{"error":{"message":"Rate limit reached"}}'
        ),
    )
    monkeypatch.setattr(
        "core.descriptions.urllib_request.urlopen",
        Mock(side_effect=http_error),
    )
    provider = OpenAIProvider(api_key="test-key")

    try:
        provider.generate("prompt", timeout_s=5)
    except LLMProviderError as error:
        assert error.retryable is True
        assert "status 429" in str(error)
    else:
        raise AssertionError("Expected LLMProviderError")


def test_process_paper_persists_successful_description(monkeypatch):
    paper = PaperCandidate(
        arxiv_id="2601.00001",
        title="A Completely Different Headline About Widgets",
        abstract="We evaluate widget throughput on synthetic workloads.",
        max_score=0.91,
    )
    provider = MockLLMProvider(
        response_text=(
            "Synthetic workload experiments quantify widget throughput limits across hardware tiers."
        )
    )
    persist = Mock(return_value=True)
    monkeypatch.setattr("core.descriptions._persist_description", persist)

    outcome = _process_paper(
        paper,
        provider,
        batch_id="batch-1",
        request_timeout_s=5,
    )

    assert outcome.status == "succeeded"
    persist.assert_called_once()


def test_process_paper_retries_on_title_repetition(monkeypatch):
    paper = PaperCandidate(
        arxiv_id="2601.00002",
        title="Transformers Improve Benchmark Accuracy",
        abstract="We study benchmark accuracy under varied settings.",
        max_score=0.88,
    )
    provider = MockLLMProvider()
    provider.generate = Mock(
        side_effect=[
            LLMResult(
                text="Transformers improve benchmark accuracy on standard tasks.",
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            ),
            LLMResult(
                text="Benchmark accuracy gains come from a revised training schedule and data mix.",
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            ),
        ]
    )
    persist = Mock(return_value=True)
    monkeypatch.setattr("core.descriptions._persist_description", persist)

    outcome = _process_paper(
        paper,
        provider,
        batch_id="batch-2",
        request_timeout_s=5,
    )

    assert outcome.status == "succeeded"
    assert provider.generate.call_count == 2


def test_process_paper_retries_on_length_failure(monkeypatch):
    paper = PaperCandidate(
        arxiv_id="2601.00004",
        title="Efficient GPU Kernels for Sparse Attention",
        abstract="We benchmark sparse attention kernels across GPU generations.",
        max_score=0.87,
    )
    provider = MockLLMProvider()
    provider.generate = Mock(
        side_effect=[
            LLMResult(
                text=" ".join(["verbose"] * 55),
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            ),
            LLMResult(
                text="Benchmarks show sparse attention kernels scale best on newer GPUs.",
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            ),
        ]
    )
    persist = Mock(return_value=True)
    monkeypatch.setattr("core.descriptions._persist_description", persist)

    outcome = _process_paper(
        paper,
        provider,
        batch_id="batch-3",
        request_timeout_s=5,
    )

    assert outcome.status == "succeeded"
    assert provider.generate.call_count == 2
    retry_prompt = provider.generate.call_args_list[1].args[0]
    assert "too long" in retry_prompt
    assert "no more than 35 words" in retry_prompt
    assert "repeated the title" not in retry_prompt


def test_process_paper_retries_on_empty_response(monkeypatch):
    paper = PaperCandidate(
        arxiv_id="2601.00005",
        title="Robust Planning Under Uncertainty",
        abstract="We study planning algorithms for uncertain environments.",
        max_score=0.86,
    )
    provider = MockLLMProvider()
    provider.generate = Mock(
        side_effect=[
            LLMResult(text="   ", input_tokens=10, output_tokens=0, latency_ms=1),
            LLMResult(
                text="Planning experiments compare robustness across uncertain benchmark settings.",
                input_tokens=10,
                output_tokens=5,
                latency_ms=1,
            ),
        ]
    )
    persist = Mock(return_value=True)
    monkeypatch.setattr("core.descriptions._persist_description", persist)

    outcome = _process_paper(
        paper,
        provider,
        batch_id="batch-4",
        request_timeout_s=5,
    )

    assert outcome.status == "succeeded"
    assert provider.generate.call_count == 2
    retry_prompt = provider.generate.call_args_list[1].args[0]
    assert "was empty" in retry_prompt
    assert "repeated the title" not in retry_prompt


def test_run_description_batch_for_recommendations_records_stats(monkeypatch):
    candidates = [
        PaperCandidate(
            arxiv_id="2601.00003",
            title="Different Title About Systems",
            abstract="Abstract text.",
            max_score=0.95,
        )
    ]
    monkeypatch.setattr(
        "core.descriptions.fetch_paper_candidates",
        Mock(return_value=candidates),
    )
    monkeypatch.setattr(
        "core.descriptions._process_paper",
        Mock(
            return_value=Mock(
                arxiv_id="2601.00003",
                status="succeeded",
                input_tokens=10,
                output_tokens=5,
                latency_ms=3,
            )
        ),
    )

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(
        "core.descriptions.connection_scope",
        lambda conn=None: _fake_scope(connection),
    )

    stats = run_description_batch_for_recommendations(
        run_ids=["run-1"],
        provider=MockLLMProvider(),
    )

    assert stats["candidate_count"] == 1
    assert stats["attempted"] == 1
    assert stats["succeeded"] == 1
    cursor.execute.assert_called()


def test_run_description_batch_stops_when_token_budget_reached(monkeypatch):
    candidates = [
        PaperCandidate("2601.10001", "Title One", "Abstract one", 0.99),
        PaperCandidate("2601.10002", "Title Two", "Abstract two", 0.98),
        PaperCandidate("2601.10003", "Title Three", "Abstract three", 0.97),
    ]
    monkeypatch.setattr("core.descriptions.fetch_paper_candidates", Mock(return_value=candidates))
    monkeypatch.setattr("core.descriptions.get_llm_batch_concurrency", Mock(return_value=1))
    monkeypatch.setattr("core.descriptions.get_llm_batch_timeout_s", Mock(return_value=600))
    monkeypatch.setattr("core.descriptions.get_llm_request_timeout_s", Mock(return_value=10))
    monkeypatch.setattr("core.descriptions.get_llm_batch_max_tokens", Mock(return_value=20))
    monkeypatch.setattr("core.descriptions._estimated_tokens_per_candidate", Mock(return_value=1))
    monkeypatch.setattr(
        "core.descriptions._process_paper",
        Mock(
            side_effect=[
                Mock(
                    arxiv_id="2601.10001",
                    status="succeeded",
                    input_tokens=8,
                    output_tokens=7,
                    latency_ms=2,
                ),
                Mock(
                    arxiv_id="2601.10002",
                    status="succeeded",
                    input_tokens=8,
                    output_tokens=7,
                    latency_ms=2,
                ),
            ]
        ),
    )

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(
        "core.descriptions.connection_scope",
        lambda conn=None: _fake_scope(connection),
    )

    stats = run_description_batch_for_recommendations(
        run_ids=["run-1"],
        provider=MockLLMProvider(),
    )

    assert stats["attempted"] == 2
    assert stats["skipped_budget"] == 1


def test_run_description_batch_counts_skipped_locked(monkeypatch):
    candidates = [PaperCandidate("2601.20001", "Locked title", "Locked abstract", 0.95)]
    monkeypatch.setattr("core.descriptions.fetch_paper_candidates", Mock(return_value=candidates))
    monkeypatch.setattr("core.descriptions.get_llm_batch_concurrency", Mock(return_value=1))
    monkeypatch.setattr("core.descriptions.get_llm_batch_timeout_s", Mock(return_value=600))
    monkeypatch.setattr("core.descriptions.get_llm_request_timeout_s", Mock(return_value=10))
    monkeypatch.setattr("core.descriptions.get_llm_batch_max_tokens", Mock(return_value=1000))
    monkeypatch.setattr(
        "core.descriptions._process_paper",
        Mock(
            return_value=Mock(
                arxiv_id="2601.20001",
                status="skipped_locked",
                input_tokens=0,
                output_tokens=0,
                latency_ms=0,
            )
        ),
    )

    connection = MagicMock()
    cursor = MagicMock()
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setattr(
        "core.descriptions.connection_scope",
        lambda conn=None: _fake_scope(connection),
    )

    stats = run_description_batch_for_recommendations(
        run_ids=["run-1"],
        provider=MockLLMProvider(),
    )

    assert stats["attempted"] == 1
    assert stats["skipped_locked"] == 1
