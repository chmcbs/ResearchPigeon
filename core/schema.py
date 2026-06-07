"""
Creates the Postgres schema
"""

import psycopg

from core.db import get_database_url
from core.keyword_search import PAPER_SEARCH_VECTOR_SQL


########################################
############### PAPERS #################
########################################

CREATE_PAPERS_TABLE = """
CREATE TABLE IF NOT EXISTS papers (
    arxiv_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    abstract TEXT,
    authors TEXT[],
    published_at TIMESTAMPTZ,
    updated_at TIMESTAMPTZ,
    pdf_url TEXT,
    entry_url TEXT,
    categories TEXT[],
    inserted_at TIMESTAMPTZ DEFAULT NOW()
);
"""

CREATE_PAPERS_KEYWORD_INDEX = f"""
CREATE INDEX IF NOT EXISTS papers_keyword_idx
ON papers
USING GIN (
    ({PAPER_SEARCH_VECTOR_SQL})
);
"""


########################################
################ RUNS ##################
########################################

CREATE_RUNS_TABLE = """
CREATE TABLE IF NOT EXISTS runs (
    run_id UUID PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
    category TEXT NOT NULL,
    max_results INTEGER NOT NULL,
    fetched_count INTEGER DEFAULT 0,
    saved_count INTEGER DEFAULT 0,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    error_message TEXT
);
"""

CREATE_RATE_LIMIT_EVENTS_TABLE = """
CREATE TABLE IF NOT EXISTS rate_limit_events (
    bucket_key TEXT NOT NULL,
    attempted_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_RATE_LIMIT_EVENTS_INDEX = """
CREATE INDEX IF NOT EXISTS rate_limit_events_bucket_attempted_idx
ON rate_limit_events (bucket_key, attempted_at DESC);
"""


########################################
############# EMBEDDINGS ###############
########################################

CREATE_VECTOR_EXTENSION = """
CREATE EXTENSION IF NOT EXISTS vector;
"""

CREATE_PAPER_EMBEDDINGS_TABLE = """
CREATE TABLE IF NOT EXISTS paper_embeddings (
    arxiv_id TEXT PRIMARY KEY REFERENCES papers(arxiv_id) ON DELETE CASCADE,
    embedding vector(384) NOT NULL,
    model_name TEXT NOT NULL,
    embedded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


########################################
############### PROFILES ###############
########################################

CREATE_USER_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS user_profiles (
    profile_id UUID PRIMARY KEY,
    user_id TEXT NOT NULL,
    profile_slot SMALLINT NOT NULL CHECK (profile_slot BETWEEN 1 AND 6),
    profile_name TEXT NOT NULL DEFAULT 'Profile',
    category TEXT NOT NULL,
    interest_sentence TEXT NOT NULL,
    digest_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(user_id, profile_slot)
);
"""

CREATE_USER_PROFILES_USER_INDEX = """
CREATE INDEX IF NOT EXISTS user_profiles_user_created_idx
ON user_profiles (user_id, created_at ASC);
"""

ALTER_USER_PROFILES_ADD_DIGEST_ENABLED = """
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS digest_enabled BOOLEAN NOT NULL DEFAULT TRUE;
"""

ALTER_USER_PROFILES_ADD_PROFILE_NAME = """
ALTER TABLE user_profiles
ADD COLUMN IF NOT EXISTS profile_name TEXT NOT NULL DEFAULT 'Profile';
"""

ALTER_USER_PROFILES_EXPAND_PROFILE_SLOT_CHECK = """
ALTER TABLE user_profiles
DROP CONSTRAINT IF EXISTS user_profiles_profile_slot_check;

ALTER TABLE user_profiles
ADD CONSTRAINT user_profiles_profile_slot_check
CHECK (profile_slot BETWEEN 1 AND 6);
"""


########################################
####### PREFERENCES & FEEDBACK #########
########################################

CREATE_PROFILE_PREFERENCES_TABLE = """
CREATE TABLE IF NOT EXISTS profile_preferences (
    profile_id UUID PRIMARY KEY REFERENCES user_profiles(profile_id) ON DELETE CASCADE,
    initial_interest_embedding vector(384) NOT NULL,
    preference_embedding vector(384) NOT NULL,
    daily_k INTEGER CHECK (daily_k >= 1),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_PROFILE_KEYWORDS_TABLE = """
CREATE TABLE IF NOT EXISTS profile_keywords (
    profile_id UUID NOT NULL REFERENCES user_profiles(profile_id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_id, keyword)
);
"""

CREATE_PROFILE_KEYWORDS_PROFILE_INDEX = """
CREATE INDEX IF NOT EXISTS profile_keywords_profile_idx
ON profile_keywords (profile_id, created_at ASC);
"""

CREATE_PAPER_FEEDBACK_TABLE = """
CREATE TABLE IF NOT EXISTS paper_feedback (
    feedback_id UUID PRIMARY KEY,
    profile_id UUID NOT NULL REFERENCES user_profiles(profile_id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES papers(arxiv_id) ON DELETE CASCADE,
    label TEXT NOT NULL CHECK (label IN ('like', 'dislike')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_PAPER_FEEDBACK_PROFILE_PAPER_INDEX = """
CREATE UNIQUE INDEX IF NOT EXISTS paper_feedback_profile_paper_idx
ON paper_feedback (profile_id, arxiv_id);
"""

CREATE_PROFILE_DISMISSED_PAPERS_TABLE = """
CREATE TABLE IF NOT EXISTS profile_dismissed_papers (
    profile_id UUID NOT NULL REFERENCES user_profiles(profile_id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES papers(arxiv_id) ON DELETE CASCADE,
    dismissed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (profile_id, arxiv_id)
);
"""

CREATE_PROFILE_DISMISSED_PAPERS_PROFILE_INDEX = """
CREATE INDEX IF NOT EXISTS profile_dismissed_papers_profile_idx
ON profile_dismissed_papers (profile_id, dismissed_at DESC);
"""


########################################
################ AUTH ##################
########################################

CREATE_MAGIC_LINK_TOKENS_TABLE = """
CREATE TABLE IF NOT EXISTS magic_link_tokens (
    token_hash TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    consumed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_AUTH_SESSIONS_TABLE = """
CREATE TABLE IF NOT EXISTS auth_sessions (
    session_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    email TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""

CREATE_AUTH_SESSIONS_USER_INDEX = """
CREATE INDEX IF NOT EXISTS auth_sessions_user_idx
ON auth_sessions (user_id, created_at DESC);
"""


########################################
########### RECOMMENDATIONS ############
########################################

CREATE_RECOMMENDATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS recommendations (
    recommendation_id UUID PRIMARY KEY,
    run_id UUID NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
    profile_id UUID NOT NULL REFERENCES user_profiles(profile_id) ON DELETE CASCADE,
    arxiv_id TEXT NOT NULL REFERENCES papers(arxiv_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank >= 1),
    base_dense_score DOUBLE PRECISION NOT NULL DEFAULT 0,
    keyword_boost DOUBLE PRECISION NOT NULL DEFAULT 0,
    final_score DOUBLE PRECISION NOT NULL,
    candidate_window TEXT NOT NULL,
    fallback_stage SMALLINT NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(run_id, profile_id, rank),
    UNIQUE(run_id, profile_id, arxiv_id)
);
"""

ALTER_RECOMMENDATIONS_ADD_BASE_DENSE_SCORE = """
ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS base_dense_score DOUBLE PRECISION NOT NULL DEFAULT 0;
"""

ALTER_RECOMMENDATIONS_ADD_KEYWORD_BOOST = """
ALTER TABLE recommendations
ADD COLUMN IF NOT EXISTS keyword_boost DOUBLE PRECISION NOT NULL DEFAULT 0;
"""

CREATE_RECOMMENDATIONS_PROFILE_GENERATED_INDEX = """
CREATE INDEX IF NOT EXISTS recommendations_profile_generated_idx
ON recommendations (profile_id, generated_at DESC);
"""

CREATE_RECOMMENDATIONS_PROFILE_PAPER_GENERATED_INDEX = """
CREATE INDEX IF NOT EXISTS recommendations_profile_paper_generated_idx
ON recommendations (profile_id, arxiv_id, generated_at DESC);
"""


########################################
############# DESCRIPTIONS #############
########################################

CREATE_DESCRIPTION_BATCHES_TABLE = """
CREATE TABLE IF NOT EXISTS description_batches (
    batch_id UUID PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMPTZ,
    attempted INTEGER NOT NULL DEFAULT 0,
    succeeded INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    skipped_budget INTEGER NOT NULL DEFAULT 0,
    skipped_timeout INTEGER NOT NULL DEFAULT 0,
    skipped_validation INTEGER NOT NULL DEFAULT 0,
    total_input_tokens INTEGER NOT NULL DEFAULT 0,
    total_output_tokens INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL,
    model TEXT NOT NULL
);
"""

CREATE_DESCRIPTIONS_TABLE = """
CREATE TABLE IF NOT EXISTS descriptions (
    arxiv_id TEXT PRIMARY KEY REFERENCES papers(arxiv_id) ON DELETE CASCADE,
    batch_id UUID REFERENCES description_batches(batch_id) ON DELETE SET NULL,
    description TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('llm')),
    model TEXT NOT NULL,
    prompt_version INTEGER NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    latency_ms INTEGER NOT NULL DEFAULT 0,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
"""


def main():
    with psycopg.connect(get_database_url()) as conn:
        with conn.cursor() as cur:
            cur.execute(CREATE_VECTOR_EXTENSION)
            cur.execute(CREATE_PAPERS_TABLE)
            cur.execute(CREATE_RUNS_TABLE)
            cur.execute(CREATE_RATE_LIMIT_EVENTS_TABLE)
            cur.execute(CREATE_RATE_LIMIT_EVENTS_INDEX)
            cur.execute(CREATE_PAPER_EMBEDDINGS_TABLE)
            cur.execute(CREATE_PAPERS_KEYWORD_INDEX)
            cur.execute(CREATE_USER_PROFILES_TABLE)
            cur.execute(ALTER_USER_PROFILES_ADD_DIGEST_ENABLED)
            cur.execute(ALTER_USER_PROFILES_ADD_PROFILE_NAME)
            cur.execute(ALTER_USER_PROFILES_EXPAND_PROFILE_SLOT_CHECK)
            cur.execute(CREATE_USER_PROFILES_USER_INDEX)
            cur.execute(CREATE_PROFILE_PREFERENCES_TABLE)
            cur.execute(CREATE_PROFILE_KEYWORDS_TABLE)
            cur.execute(CREATE_PROFILE_KEYWORDS_PROFILE_INDEX)
            cur.execute(CREATE_MAGIC_LINK_TOKENS_TABLE)
            cur.execute(CREATE_AUTH_SESSIONS_TABLE)
            cur.execute(CREATE_AUTH_SESSIONS_USER_INDEX)
            cur.execute(CREATE_PAPER_FEEDBACK_TABLE)
            cur.execute(CREATE_PAPER_FEEDBACK_PROFILE_PAPER_INDEX)
            cur.execute(CREATE_PROFILE_DISMISSED_PAPERS_TABLE)
            cur.execute(CREATE_PROFILE_DISMISSED_PAPERS_PROFILE_INDEX)
            cur.execute(CREATE_RECOMMENDATIONS_TABLE)
            cur.execute(ALTER_RECOMMENDATIONS_ADD_BASE_DENSE_SCORE)
            cur.execute(ALTER_RECOMMENDATIONS_ADD_KEYWORD_BOOST)
            cur.execute(CREATE_RECOMMENDATIONS_PROFILE_GENERATED_INDEX)
            cur.execute(CREATE_RECOMMENDATIONS_PROFILE_PAPER_GENERATED_INDEX)
            cur.execute(CREATE_DESCRIPTION_BATCHES_TABLE)
            cur.execute(CREATE_DESCRIPTIONS_TABLE)


if __name__ == "__main__":
    main()
