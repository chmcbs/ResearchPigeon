"""
Tests config module helpers
"""

import pytest

from core import config


def test_get_product_name_defaults_to_placeholder(monkeypatch):
    monkeypatch.delenv("PRODUCT_NAME", raising=False)
    assert config.get_product_name() == "ResearchPigeon"


def test_get_product_name_uses_environment(monkeypatch):
    monkeypatch.setenv("PRODUCT_NAME", "Paper Radar")
    assert config.get_product_name() == "Paper Radar"


def test_get_arxiv_categories_uses_default(monkeypatch):
    monkeypatch.delenv("ARXIV_CATEGORIES", raising=False)

    assert config.get_arxiv_categories() == ["cs.AI"]


def test_get_arxiv_categories_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("ARXIV_CATEGORIES", "cs.AI, cs.CL, cs.LG")

    assert config.get_arxiv_categories() == ["cs.AI", "cs.CL", "cs.LG"]


def test_get_arxiv_categories_rejects_empty(monkeypatch):
    monkeypatch.setenv("ARXIV_CATEGORIES", "  ,  , ")

    with pytest.raises(ValueError, match="At least one"):
        config.get_arxiv_categories()


def test_get_arxiv_category_options_include_labels(monkeypatch):
    monkeypatch.setenv("ARXIV_CATEGORIES", "cs.AI, cs.CL")
    config._get_arxiv_category_labels.cache_clear()

    options = config.get_arxiv_category_options()

    assert options == [
        {"id": "cs.AI", "label": "cs.AI (Artificial Intelligence)"},
        {"id": "cs.CL", "label": "cs.CL (Computation and Language)"},
    ]


def test_format_arxiv_category_label_falls_back_to_id(monkeypatch):
    config._get_arxiv_category_labels.cache_clear()
    assert config.format_arxiv_category_label("cs.ZZ") == "cs.ZZ"


def test_get_daily_picks_k_uses_default():
    assert config.get_daily_picks_k() >= 1


def test_get_daily_picks_k_rejects_invalid_value(monkeypatch):
    monkeypatch.setattr(config, "DEFAULT_DAILY_K", 0)

    with pytest.raises(ValueError, match="must be >= 1"):
        config.get_daily_picks_k()


def test_get_keyword_boost_cap_uses_default(monkeypatch):
    monkeypatch.delenv("KEYWORD_BOOST_CAP", raising=False)
    assert config.get_keyword_boost_cap() == 0.25


def test_get_keyword_boost_cap_reads_environment(monkeypatch):
    monkeypatch.setenv("KEYWORD_BOOST_CAP", "0.4")
    assert config.get_keyword_boost_cap() == 0.4


def test_get_keyword_boost_cap_rejects_negative(monkeypatch):
    monkeypatch.setenv("KEYWORD_BOOST_CAP", "-0.1")
    with pytest.raises(ValueError, match="non-negative"):
        config.get_keyword_boost_cap()


def test_get_debug_admin_emails_parses_comma_separated(monkeypatch):
    monkeypatch.setenv("DEBUG_ADMIN_EMAILS", " Admin@Example.com , dev@test.io ")

    assert config.get_debug_admin_emails() == frozenset(
        {"admin@example.com", "dev@test.io"}
    )


def test_get_debug_admin_emails_empty_when_unset(monkeypatch):
    monkeypatch.delenv("DEBUG_ADMIN_EMAILS", raising=False)

    assert config.get_debug_admin_emails() == frozenset()


def test_is_production_reads_app_env(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    assert config.is_production() is True

    monkeypatch.setenv("APP_ENV", "development")
    assert config.is_production() is False


def test_is_email_delivery_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("EMAIL_FROM", raising=False)
    assert config.is_email_delivery_configured() is False

    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("EMAIL_FROM", "noreply@example.com")
    assert config.is_email_delivery_configured() is True


def test_get_smtp_use_starttls_defaults_off_for_mailpit_port(monkeypatch):
    monkeypatch.delenv("SMTP_USE_STARTTLS", raising=False)
    monkeypatch.setenv("SMTP_PORT", "1025")
    assert config.get_smtp_use_starttls() is False

    monkeypatch.setenv("SMTP_PORT", "587")
    assert config.get_smtp_use_starttls() is True


def test_pipeline_limit_getters_use_environment(monkeypatch):
    monkeypatch.setenv("INGESTION_MAX_RESULTS", "200")
    monkeypatch.setenv("EMBEDDING_LIMIT", "900")
    monkeypatch.setenv("TEST_GENERATION_LIMIT_PER_USER", "7")

    assert config.get_ingestion_max_results() == 200
    assert config.get_embedding_limit() == 900
    assert config.get_test_generation_limit_per_user() == 7


def test_llm_config_getters_use_environment(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_BASE_URL", "http://example:11434")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_BATCH_CONCURRENCY", "5")
    monkeypatch.setenv("LLM_BATCH_TIMEOUT_S", "90")
    monkeypatch.setenv("LLM_REQUEST_TIMEOUT_S", "12")
    monkeypatch.setenv("LLM_PROMPT_VERSION", "2")
    monkeypatch.setenv("LLM_ABSTRACT_MAX_CHARS", "2000")

    assert config.get_llm_provider_name() == "mock"
    assert config.get_llm_base_url() == "http://example:11434"
    assert config.get_llm_model() == "test-model"
    assert config.get_llm_batch_concurrency() == 5
    assert config.get_llm_batch_timeout_s() == 90
    assert config.get_llm_request_timeout_s() == 12
    assert config.get_llm_prompt_version() == 2
    assert config.get_llm_abstract_max_chars() == 2000


def test_get_llm_provider_name_defaults_to_mock(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert config.get_llm_provider_name() == "mock"


def test_openai_getters_use_defaults(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert config.get_openai_api_key() == ""
    assert config.get_openai_base_url() == "https://api.openai.com/v1"
    assert config.get_openai_model() == "gpt-4.1-nano"


def test_llm_budget_and_threshold_getters(monkeypatch):
    monkeypatch.setenv("LLM_BATCH_MAX_TOKENS", "1234")
    monkeypatch.setenv("LLM_FAILURE_ALERT_THRESHOLD", "0.25")
    assert config.get_llm_batch_max_tokens() == 1234
    assert config.get_llm_failure_alert_threshold() == 0.25


def test_llm_failure_threshold_rejects_out_of_range(monkeypatch):
    monkeypatch.setenv("LLM_FAILURE_ALERT_THRESHOLD", "1.1")
    with pytest.raises(ValueError, match="between 0 and 1"):
        config.get_llm_failure_alert_threshold()


def test_is_database_rate_limit_enabled_defaults_to_production(monkeypatch):
    monkeypatch.delenv("RATE_LIMIT_USE_DATABASE", raising=False)
    monkeypatch.setenv("APP_ENV", "production")
    assert config.is_database_rate_limit_enabled() is True

    monkeypatch.setenv("APP_ENV", "development")
    assert config.is_database_rate_limit_enabled() is False
