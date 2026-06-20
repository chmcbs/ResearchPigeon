"""
Paper-level LLM blurbs for digest picks
"""

from __future__ import annotations

import json
import re
import time
import uuid
import psycopg
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request

from core.config import (
    get_llm_abstract_max_chars,
    get_llm_base_url,
    get_llm_batch_concurrency,
    get_llm_batch_max_tokens,
    get_llm_batch_timeout_s,
    get_llm_model,
    get_openai_api_key,
    get_openai_base_url,
    get_openai_model,
    get_llm_prompt_version,
    get_llm_provider_name,
    get_llm_request_timeout_s,
)
from core.db import connection_scope
from core.db import get_database_url
from core.arxiv_text import format_arxiv_display_text
from core.logging import get_logger

logger = get_logger(__name__)

_WORD_RE = re.compile(r"[a-z0-9]+", re.IGNORECASE)

########################################
################ SQL ###################
########################################

FETCH_CANDIDATES_SQL = """
SELECT
    p.arxiv_id,
    p.title,
    COALESCE(p.abstract, '') AS abstract,
    MAX(rec.final_score) AS max_score
FROM recommendations rec
JOIN papers p ON p.arxiv_id = rec.arxiv_id
LEFT JOIN descriptions d ON d.arxiv_id = rec.arxiv_id
WHERE rec.run_id::text = ANY(%(run_ids)s)
  AND (
    %(profile_ids)s::text[] IS NULL
    OR rec.profile_id::text = ANY(%(profile_ids)s::text[])
  )
  AND d.arxiv_id IS NULL
GROUP BY p.arxiv_id, p.title, p.abstract
ORDER BY max_score DESC, p.arxiv_id ASC;
"""

INSERT_BATCH_START_SQL = """
INSERT INTO description_batches (
    batch_id,
    started_at,
    finished_at,
    attempted,
    succeeded,
    failed,
    skipped_budget,
    skipped_locked,
    skipped_timeout,
    skipped_validation,
    total_input_tokens,
    total_output_tokens,
    provider,
    model
)
VALUES (
    %(batch_id)s,
    %(started_at)s,
    NULL,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    %(provider)s,
    %(model)s
);
"""

UPDATE_BATCH_SQL = """
UPDATE description_batches
SET
    finished_at = %(finished_at)s,
    attempted = %(attempted)s,
    succeeded = %(succeeded)s,
    failed = %(failed)s,
    skipped_budget = %(skipped_budget)s,
    skipped_locked = %(skipped_locked)s,
    skipped_timeout = %(skipped_timeout)s,
    skipped_validation = %(skipped_validation)s,
    total_input_tokens = %(total_input_tokens)s,
    total_output_tokens = %(total_output_tokens)s
WHERE batch_id = %(batch_id)s;
"""

DESCRIPTION_EXISTS_SQL = """
SELECT 1
FROM descriptions
WHERE arxiv_id = %(arxiv_id)s
LIMIT 1;
"""

INSERT_DESCRIPTION_SQL = """
INSERT INTO descriptions (
    arxiv_id,
    batch_id,
    description,
    source,
    model,
    prompt_version,
    input_tokens,
    output_tokens,
    latency_ms
)
VALUES (
    %(arxiv_id)s,
    %(batch_id)s,
    %(description)s,
    'llm',
    %(model)s,
    %(prompt_version)s,
    %(input_tokens)s,
    %(output_tokens)s,
    %(latency_ms)s
)
ON CONFLICT (arxiv_id) DO NOTHING;
"""


########################################
############### TYPES ##################
########################################

@dataclass(frozen=True)
class PaperCandidate:
    arxiv_id: str
    title: str
    abstract: str
    max_score: float


@dataclass(frozen=True)
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class PaperOutcome:
    arxiv_id: str
    status: str
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: int = 0


class LLMProvider(Protocol):
    provider_name: str
    model_name: str

    def generate(self, prompt: str, *, timeout_s: float) -> LLMResult: ...


class LLMProviderError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


########################################
############# PROVIDERS ################
########################################

def _clean_sentence(text: str) -> str:
    cleaned = text.strip().strip("\"'")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return format_arxiv_display_text(cleaned)


def _extract_openai_text(body: dict) -> str:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    output_items = body.get("output")
    if not isinstance(output_items, list):
        return ""

    for item in output_items:
        if not isinstance(item, dict):
            continue
        contents = item.get("content")
        if not isinstance(contents, list):
            continue
        for content in contents:
            if not isinstance(content, dict):
                continue
            if content.get("type") == "output_text":
                text = content.get("text")
                if isinstance(text, str) and text.strip():
                    return text
    return ""


class OllamaProvider:
    provider_name = "ollama"

    def __init__(self, *, base_url: str | None = None, model: str | None = None) -> None:
        self.base_url = (base_url or get_llm_base_url()).rstrip("/")
        self.model_name = model or get_llm_model()

    # Parse the JSON response into an LLMResult
    def generate(self, prompt: str, *, timeout_s: float) -> LLMResult:
        payload = json.dumps(
            {
                "model": self.model_name,
                "prompt": prompt,
                "stream": False,
                "options": {"num_predict": 80, "temperature": 0.2},
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib_request.urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.URLError as error:
            raise LLMProviderError(
                f"Ollama request failed: {error}",
                retryable=True,
            ) from error
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=_clean_sentence(str(body.get("response", ""))),
            input_tokens=int(body.get("prompt_eval_count") or 0),
            output_tokens=int(body.get("eval_count") or 0),
            latency_ms=latency_ms,
        )


class OpenAIProvider:
    provider_name = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
    ) -> None:
        self.api_key = (api_key or get_openai_api_key()).strip()
        self.base_url = (base_url or get_openai_base_url()).rstrip("/")
        self.model_name = model or get_openai_model()

    def generate(self, prompt: str, *, timeout_s: float) -> LLMResult:
        if not self.api_key:
            raise LLMProviderError(
                "OpenAI request failed: OPENAI_API_KEY is not configured",
                retryable=False,
            )

        payload = json.dumps(
            {
                "model": self.model_name,
                "input": prompt,
                "temperature": 0.2,
                "max_output_tokens": 80,
            }
        ).encode("utf-8")
        request = urllib_request.Request(
            f"{self.base_url}/responses",
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
            method="POST",
        )
        started = time.monotonic()
        try:
            with urllib_request.urlopen(request, timeout=timeout_s) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib_error.HTTPError as error:
            error_body = ""
            try:
                raw = error.read().decode("utf-8")
                payload = json.loads(raw)
                if isinstance(payload, dict):
                    parsed_error = payload.get("error")
                    if isinstance(parsed_error, dict):
                        error_body = str(parsed_error.get("message") or "").strip()
            except Exception:
                error_body = ""
            retryable = error.code in (408, 409, 429) or error.code >= 500
            detail = f": {error_body}" if error_body else ""
            raise LLMProviderError(
                f"OpenAI request failed with status {error.code}{detail}",
                retryable=retryable,
            ) from error
        except (urllib_error.URLError, TimeoutError) as error:
            raise LLMProviderError(
                f"OpenAI request failed: {error}",
                retryable=True,
            ) from error

        usage = body.get("usage") if isinstance(body, dict) else {}
        if not isinstance(usage, dict):
            usage = {}
        latency_ms = int((time.monotonic() - started) * 1000)
        return LLMResult(
            text=_clean_sentence(_extract_openai_text(body)),
            input_tokens=int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
            output_tokens=int(
                usage.get("output_tokens") or usage.get("completion_tokens") or 0
            ),
            latency_ms=latency_ms,
        )


class MockLLMProvider:
    provider_name = "mock"
    model_name = "mock-model"

    def __init__(self, *, response_text: str | None = None) -> None:
        self.response_text = response_text or (
            "Uses a controlled benchmark to quantify scaling limits under realistic workloads."
        )

    def generate(self, prompt: str, *, timeout_s: float) -> LLMResult:
        del prompt, timeout_s
        return LLMResult(
            text=self.response_text,
            input_tokens=120,
            output_tokens=24,
            latency_ms=5,
        )


def get_llm_provider(provider_name: str | None = None) -> LLMProvider:
    resolved = (provider_name or get_llm_provider_name()).strip().lower()
    if resolved == "mock":
        return MockLLMProvider()
    if resolved == "openai":
        return OpenAIProvider()
    if resolved == "ollama":
        return OllamaProvider()
    raise ValueError(f"Unsupported LLM provider: {resolved}")


########################################
######## PROMPT VALIDATION #############
########################################

# Shorten long abstracts before they go into the prompt
def _truncate_abstract(abstract: str, max_chars: int) -> str:
    text = abstract.strip()
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3].rstrip() + "..."


def _normalize_words(text: str) -> list[str]:
    return [word.lower() for word in _WORD_RE.findall(text) if len(word) > 2]


# Checks whether a description repeats the title of the paper
def repeats_title(title: str, description: str) -> bool:
    title_text = title.strip().lower()
    description_text = description.strip().lower()
    if not description_text:
        return True
    if description_text in title_text or title_text in description_text:
        return True

    title_words = set(_normalize_words(title))
    description_words = _normalize_words(description)
    if not description_words:
        return True

    overlap = sum(1 for word in description_words if word in title_words)
    return (overlap / len(description_words)) > 0.55


def _is_empty_description(description: str) -> bool:
    return not description


def _is_too_long(description: str) -> bool:
    return len(description.split()) > 50


def _has_length_failure(description: str) -> bool:
    return _is_empty_description(description) or _is_too_long(description)


def _validation_failures(*, title: str, description: str) -> frozenset[str]:
    failures: set[str] = set()
    if _is_empty_description(description):
        failures.add("empty")
    elif _is_too_long(description):
        failures.add("length")
    if description and repeats_title(title, description):
        failures.add("title")
    return frozenset(failures)


def _build_prompt(
    *,
    title: str,
    abstract: str,
    retry_reasons: frozenset[str] | None = None,
) -> str:
    truncated = _truncate_abstract(abstract, get_llm_abstract_max_chars())
    retry_notes: list[str] = []
    if retry_reasons:
        if "empty" in retry_reasons:
            retry_notes.append(
                "Your previous answer was empty. Output exactly one sentence."
            )
        if "length" in retry_reasons:
            retry_notes.append(
                "Your previous answer was too long. Write exactly one sentence "
                "with no more than 35 words."
            )
        if "title" in retry_reasons:
            retry_notes.append(
                "Your previous answer repeated the title. Write a new sentence "
                "that adds different information from the abstract without "
                "repeating phrases from the title."
            )
    retry_note = ""
    if retry_notes:
        retry_note = "\nIMPORTANT: " + " ".join(retry_notes) + "\n"
    return (
        "You write one-sentence research paper summaries for a daily digest email.\n"
        f"{retry_note}\n"
        f"Title: {title.strip()}\n\n"
        f"Abstract:\n{truncated}\n\n"
        "Write exactly one sentence (max 35 words) that compresses the abstract "
        "into useful context for a reader who already read the title. Do NOT "
        "repeat or restate the title's main claim. Add the next most useful "
        "detail from the abstract (method, setting, result, limitation, etc.).\n\n"
        "Rules:\n"
        "- Neutral, factual tone\n"
        "- Do not start with \"This paper\"\n"
        "- No hype or superlatives\n"
        "- Do not include facts not supported by the abstract\n"
        "- Output only the sentence, no quotes or labels\n"
    )


def _is_valid_description(description: str) -> bool:
    return not _has_length_failure(description)


########################################
############ PERSISTENCE ###############
########################################

# Returns a list of papers sorted by highest final_score to determine batch priority order
def fetch_paper_candidates(
    *,
    run_ids: list[str],
    profile_ids: list[str] | None = None,
    conn=None,
) -> list[PaperCandidate]:
    if not run_ids:
        return []

    normalized_run_ids = list(dict.fromkeys(run_ids))
    normalized_profile_ids = (
        list(dict.fromkeys(profile_ids)) if profile_ids is not None else None
    )

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                FETCH_CANDIDATES_SQL,
                {
                    "run_ids": normalized_run_ids,
                    "profile_ids": normalized_profile_ids,
                },
            )
            rows = cur.fetchall()

    return [
        PaperCandidate(
            arxiv_id=row[0],
            title=row[1],
            abstract=row[2],
            max_score=float(row[3]),
        )
        for row in rows
    ]


def _persist_description(
    *,
    paper: PaperCandidate,
    description: str,
    batch_id: str,
    provider: LLMProvider,
    outcome: PaperOutcome,
    conn=None,
) -> bool:
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                INSERT_DESCRIPTION_SQL,
                {
                    "arxiv_id": paper.arxiv_id,
                    "batch_id": batch_id,
                    "description": description,
                    "model": provider.model_name,
                    "prompt_version": get_llm_prompt_version(),
                    "input_tokens": outcome.input_tokens,
                    "output_tokens": outcome.output_tokens,
                    "latency_ms": outcome.latency_ms,
                },
            )
            inserted = cur.rowcount == 1
        active_conn.commit()
    return inserted


########################################
########## BATCH EXECUTION #############
########################################

def _estimated_tokens_per_candidate() -> int:
    # Reserve a conservative per-paper token budget so concurrency cannot overshoot max tokens.
    prompt_tokens = (get_llm_abstract_max_chars() // 3) + 120
    return max(220, prompt_tokens + 80)


def _description_exists(arxiv_id: str) -> bool:
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(DESCRIPTION_EXISTS_SQL, {"arxiv_id": arxiv_id})
            return cur.fetchone() is not None


@contextmanager
def _paper_generation_claim(arxiv_id: str):
    lock_name = f"description:{arxiv_id}"
    acquired = False
    with psycopg.connect(get_database_url()) as lock_conn:
        with lock_conn.cursor() as cur:
            cur.execute(
                "SELECT pg_try_advisory_lock(hashtextextended(%s, 0));",
                (lock_name,),
            )
            row = cur.fetchone()
            acquired = bool(row and row[0])
        try:
            yield acquired
        finally:
            if acquired:
                with lock_conn.cursor() as cur:
                    cur.execute(
                        "SELECT pg_advisory_unlock(hashtextextended(%s, 0));",
                        (lock_name,),
                    )


def _generate_with_retries(
    provider: LLMProvider,
    prompt: str,
    *,
    started_at: float,
    request_timeout_s: float,
) -> LLMResult:
    # Keep retries short so one slow provider call does not consume the whole per-paper timeout
    backoff_schedule = (0.25, 0.75)
    attempt = 0
    while True:
        elapsed = time.monotonic() - started_at
        remaining = request_timeout_s - elapsed
        if remaining <= 0:
            raise LLMProviderError("LLM request timed out", retryable=False)
        try:
            return provider.generate(prompt, timeout_s=remaining)
        except Exception as error:
            retryable = bool(getattr(error, "retryable", False))
            if not retryable or attempt >= len(backoff_schedule):
                raise
            backoff_s = backoff_schedule[attempt]
            elapsed = time.monotonic() - started_at
            remaining = request_timeout_s - elapsed
            if remaining <= backoff_s:
                raise
            logger.warning(
                "Transient LLM call failed; retrying",
                extra={
                    "event": "llm.paper.retry",
                    "retry_attempt": attempt + 1,
                    "error_type": error.__class__.__name__,
                },
            )
            time.sleep(backoff_s)
            attempt += 1


# Process one paper end-to-end (this runs inside a thread during the batch)
def _process_paper(
    paper: PaperCandidate,
    provider: LLMProvider,
    *,
    batch_id: str,
    request_timeout_s: float,
) -> PaperOutcome:
    with _paper_generation_claim(paper.arxiv_id) as acquired:
        if not acquired:
            if _description_exists(paper.arxiv_id):
                return PaperOutcome(arxiv_id=paper.arxiv_id, status="succeeded")
            logger.info(
                "Skipping paper because another batch is generating its description",
                extra={
                    "event": "llm.paper.skipped_locked",
                    "arxiv_id": paper.arxiv_id,
                },
            )
            return PaperOutcome(arxiv_id=paper.arxiv_id, status="skipped_locked")

    started = time.monotonic()
    total_input_tokens = 0
    total_output_tokens = 0
    total_latency_ms = 0

    retry_reasons: frozenset[str] | None = None

    # Limit to one regeneration pass so validation failures do not loop indefinitely under load
    for attempt in range(2):
        remaining = request_timeout_s - (time.monotonic() - started)
        if remaining <= 0:
            return PaperOutcome(
                arxiv_id=paper.arxiv_id,
                status="skipped_timeout",
                input_tokens=total_input_tokens,
                output_tokens=total_output_tokens,
                latency_ms=total_latency_ms,
            )

        prompt = _build_prompt(
            title=paper.title,
            abstract=paper.abstract,
            retry_reasons=retry_reasons,
        )
        try:
            result = _generate_with_retries(
                provider,
                prompt,
                started_at=started,
                request_timeout_s=request_timeout_s,
            )
        except Exception as error:
            logger.warning(
                "LLM call failed for paper",
                extra={
                    "event": "llm.paper.failed",
                    "arxiv_id": paper.arxiv_id,
                    "retry": attempt == 1,
                    "error_type": error.__class__.__name__,
                },
            )
            if attempt == 1:
                return PaperOutcome(
                    arxiv_id=paper.arxiv_id,
                    status="failed",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    latency_ms=total_latency_ms,
                )
            continue

        total_input_tokens += result.input_tokens
        total_output_tokens += result.output_tokens
        total_latency_ms += result.latency_ms
        description = _clean_sentence(result.text)

        failures = _validation_failures(title=paper.title, description=description)
        if failures:
            if attempt == 1:
                return PaperOutcome(
                    arxiv_id=paper.arxiv_id,
                    status="skipped_validation",
                    input_tokens=total_input_tokens,
                    output_tokens=total_output_tokens,
                    latency_ms=total_latency_ms,
                )
            retry_reasons = failures
            continue

        outcome = PaperOutcome(
            arxiv_id=paper.arxiv_id,
            status="succeeded",
            input_tokens=total_input_tokens,
            output_tokens=total_output_tokens,
            latency_ms=total_latency_ms,
        )
        _persist_description(
            paper=paper,
            description=description,
            batch_id=batch_id,
            provider=provider,
            outcome=outcome,
        )
        return outcome

    return PaperOutcome(
        arxiv_id=paper.arxiv_id,
        status="skipped_validation",
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
        latency_ms=total_latency_ms,
    )


# Top-level function called by core/cron.py and core/pipeline.py
def run_description_batch_for_recommendations(
    *,
    run_ids: list[str],
    profile_ids: list[str] | None = None,
    provider: LLMProvider | None = None,
    conn=None,
) -> dict:
    batch_started = datetime.now(UTC)
    batch_started_monotonic = time.monotonic()
    batch_id = str(uuid.uuid4())
    candidates = fetch_paper_candidates(
        run_ids=run_ids,
        profile_ids=profile_ids,
        conn=conn,
    )

    stats = {
        "batch_id": batch_id,
        "candidate_count": len(candidates),
        "attempted": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped_budget": 0,
        "skipped_locked": 0,
        "skipped_timeout": 0,
        "skipped_validation": 0,
        "total_input_tokens": 0,
        "total_output_tokens": 0,
    }

    if not candidates:
        logger.info(
            "LLM description batch skipped — no candidates",
            extra={"event": "llm.batch.completed", "batch_id": batch_id},
        )
        return stats

    resolved_provider = provider or get_llm_provider()
    concurrency = get_llm_batch_concurrency()
    batch_timeout_s = get_llm_batch_timeout_s()
    batch_max_tokens = get_llm_batch_max_tokens()
    request_timeout_s = get_llm_request_timeout_s()
    reserved_tokens_per_candidate = _estimated_tokens_per_candidate()

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                INSERT_BATCH_START_SQL,
                {
                    "batch_id": batch_id,
                    "started_at": batch_started,
                    "provider": resolved_provider.provider_name,
                    "model": resolved_provider.model_name,
                },
            )
        active_conn.commit()

    logger.info(
        "LLM description batch started",
        extra={
            "event": "llm.batch.started",
            "batch_id": batch_id,
            "candidate_count": len(candidates),
            "provider": resolved_provider.provider_name,
            "model": resolved_provider.model_name,
        },
    )

    pending = list(candidates)
    active: dict[Future[PaperOutcome], tuple[PaperCandidate, int]] = {}
    reserved_tokens_in_flight = 0

    def _record_outcome(outcome: PaperOutcome) -> None:
        stats["attempted"] += 1
        stats["total_input_tokens"] += outcome.input_tokens
        stats["total_output_tokens"] += outcome.output_tokens
        if outcome.status == "succeeded":
            stats["succeeded"] += 1
        elif outcome.status == "failed":
            stats["failed"] += 1
        elif outcome.status == "skipped_locked":
            stats["skipped_locked"] += 1
        elif outcome.status == "skipped_timeout":
            stats["skipped_timeout"] += 1
        elif outcome.status == "skipped_validation":
            stats["skipped_validation"] += 1

    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        while pending or active:
            if (time.monotonic() - batch_started_monotonic) >= batch_timeout_s:
                stats["skipped_budget"] += len(pending) + len(active)
                for future in active:
                    future.cancel()
                break
            if (
                stats["total_input_tokens"]
                + stats["total_output_tokens"]
                + reserved_tokens_in_flight
                >= batch_max_tokens
            ):
                stats["skipped_budget"] += len(pending)
                if pending:
                    logger.warning(
                        "LLM description batch token budget reached",
                        extra={
                            "event": "llm.batch.budget_reached",
                            "batch_id": batch_id,
                            "remaining_candidates": len(pending),
                            "batch_max_tokens": batch_max_tokens,
                        },
                    )
                pending = []
                break

            while pending and len(active) < concurrency:
                if (time.monotonic() - batch_started_monotonic) >= batch_timeout_s:
                    stats["skipped_budget"] += len(pending)
                    pending = []
                    break
                if (
                    stats["total_input_tokens"] + stats["total_output_tokens"]
                    + reserved_tokens_in_flight
                    + reserved_tokens_per_candidate
                    > batch_max_tokens
                ):
                    stats["skipped_budget"] += len(pending)
                    logger.warning(
                        "LLM description batch token budget reached while scheduling",
                        extra={
                            "event": "llm.batch.budget_reached",
                            "batch_id": batch_id,
                            "remaining_candidates": len(pending),
                            "batch_max_tokens": batch_max_tokens,
                        },
                    )
                    pending = []
                    break
                paper = pending.pop(0)
                future = executor.submit(
                    _process_paper,
                    paper,
                    resolved_provider,
                    batch_id=batch_id,
                    request_timeout_s=request_timeout_s,
                )
                active[future] = (paper, reserved_tokens_per_candidate)
                reserved_tokens_in_flight += reserved_tokens_per_candidate

            if not active:
                break

            done, _not_done = wait(active, timeout=0.25, return_when=FIRST_COMPLETED)
            if not done:
                continue

            for future in done:
                paper, reserved_tokens = active.pop(future)
                reserved_tokens_in_flight = max(
                    0, reserved_tokens_in_flight - reserved_tokens
                )
                try:
                    outcome = future.result()
                except Exception as error:
                    logger.exception(
                        "Unexpected LLM worker failure",
                        extra={
                            "event": "llm.paper.failed",
                            "arxiv_id": paper.arxiv_id,
                            "error_type": error.__class__.__name__,
                        },
                    )
                    outcome = PaperOutcome(arxiv_id=paper.arxiv_id, status="failed")
                _record_outcome(outcome)

    finished_at = datetime.now(UTC)
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPDATE_BATCH_SQL,
                {
                    "batch_id": batch_id,
                    "finished_at": finished_at,
                    "attempted": stats["attempted"],
                    "succeeded": stats["succeeded"],
                    "failed": stats["failed"],
                    "skipped_budget": stats["skipped_budget"],
                    "skipped_locked": stats["skipped_locked"],
                    "skipped_timeout": stats["skipped_timeout"],
                    "skipped_validation": stats["skipped_validation"],
                    "total_input_tokens": stats["total_input_tokens"],
                    "total_output_tokens": stats["total_output_tokens"],
                },
            )
        active_conn.commit()

    logger.info(
        "LLM description batch completed",
        extra={
            "event": "llm.batch.completed",
            **stats,
            "provider": resolved_provider.provider_name,
            "model": resolved_provider.model_name,
            "duration_ms": int((time.monotonic() - batch_started_monotonic) * 1000),
        },
    )
    return stats
