"""
Preference embedding and feedback handling
"""

import uuid
from dataclasses import dataclass

import psycopg

from core.db import connection_scope
from core.embeddings import embed_texts
from core.profiles import require_profile_id
from core.vector_helper import vector_literal


@dataclass(frozen=True)
class PreferenceFeedbackRow:
    initial_interest_embedding: object
    embedding: object
    label: str | None


UPSERT_PREFERENCE_EMBEDDING_SQL = """
INSERT INTO profile_preferences (
    profile_id,
    initial_interest_embedding,
    preference_embedding
)
VALUES (
    %s,
    %s::vector,
    %s::vector
)
ON CONFLICT (profile_id)
DO UPDATE SET
    initial_interest_embedding = EXCLUDED.initial_interest_embedding,
    preference_embedding = EXCLUDED.preference_embedding,
    updated_at = NOW();
"""

UPSERT_FEEDBACK_SQL = """
INSERT INTO paper_feedback (
    feedback_id,
    profile_id,
    arxiv_id,
    label
)
VALUES (%s, %s, %s, %s)
ON CONFLICT (profile_id, arxiv_id)
DO UPDATE SET
    label = EXCLUDED.label,
    created_at = NOW()
RETURNING feedback_id;
"""

FETCH_PREFERENCE_AND_FEEDBACK_SQL = """
SELECT
    pp.initial_interest_embedding,
    e.embedding,
    f.label
FROM profile_preferences pp
LEFT JOIN paper_feedback f ON f.profile_id = pp.profile_id
LEFT JOIN paper_embeddings e ON e.arxiv_id = f.arxiv_id
WHERE pp.profile_id = %s;
"""

UPDATE_PREFERENCE_EMBEDDING_SQL = """
UPDATE profile_preferences
SET preference_embedding = %s::vector,
    updated_at = NOW()
WHERE profile_id = %s;
"""

RESET_ALL_PREFERENCE_EMBEDDINGS_SQL = """
UPDATE profile_preferences
SET preference_embedding = initial_interest_embedding,
    updated_at = NOW();
"""

DELETE_FEEDBACK_SQL = """
DELETE FROM paper_feedback
WHERE profile_id = %s
  AND arxiv_id = %s;
"""


# Convert pgvector strings to lists
def coerce_vector(raw_vector) -> list[float]:
    if isinstance(raw_vector, str):
        cleaned = raw_vector.strip()
        if cleaned.startswith("[") and cleaned.endswith("]"):
            cleaned = cleaned[1:-1]

        if not cleaned:
            return []

        return [float(value.strip()) for value in cleaned.split(",") if value.strip()]

    return [float(value) for value in raw_vector]


# Cold start preference embedding
def initialize_preference_embedding(
    interest_text: str,
    user_id: str,
    profile_id: str | None = None,
    conn=None,
) -> str:
    resolved_profile_id = require_profile_id(
        user_id=user_id, profile_id=profile_id, conn=conn
    )
    preference_vector = vector_literal(embed_texts([interest_text])[0])

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPSERT_PREFERENCE_EMBEDDING_SQL,
                (
                    resolved_profile_id,
                    preference_vector,
                    preference_vector,
                ),
            )

    return resolved_profile_id


def save_feedback(
    arxiv_id: str,
    label: str,
    user_id: str,
    profile_id: str | None = None,
    conn=None,
) -> str:
    if label not in {"like", "dislike"}:
        raise ValueError("label must be 'like' or 'dislike'")

    resolved_profile_id = require_profile_id(
        user_id=user_id, profile_id=profile_id, conn=conn
    )
    feedback_id = str(uuid.uuid4())

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPSERT_FEEDBACK_SQL, (feedback_id, resolved_profile_id, arxiv_id, label)
            )
            row = cur.fetchone()

    return str(row[0])


def remove_feedback(
    arxiv_id: str,
    user_id: str,
    profile_id: str | None = None,
    conn=None,
) -> bool:
    resolved_profile_id = require_profile_id(
        user_id=user_id, profile_id=profile_id, conn=conn
    )

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(DELETE_FEEDBACK_SQL, (resolved_profile_id, arxiv_id))
            return cur.rowcount > 0


def mean_vector(vectors: list[list[float]]) -> list[float]:
    if not vectors:
        return []

    dimension = len(vectors[0])

    return [
        sum(vector[index] for vector in vectors) / len(vectors)
        for index in range(dimension)
    ]


# Mix feedback with the initial preference embedding
def blend_vectors(
    initial_vector: list[float],
    feedback_vector: list[float],
    alpha: float,
) -> list[float]:
    return [
        alpha * initial_value + (1 - alpha) * feedback_value
        for initial_value, feedback_value in zip(initial_vector, feedback_vector)
    ]


# Decay initial weight
def feedback_alpha(num_feedbacks: int) -> float:
    return 1 / (1 + num_feedbacks)


# Normalise preference embedding so cosine distance compares direction rather than magnitude during ranking
def normalize_vector(vector: list[float]) -> list[float]:
    magnitude = sum(value * value for value in vector) ** 0.5

    if magnitude == 0:
        return vector

    return [value / magnitude for value in vector]


# Summarise overall feedback as a single vector
def compute_preference_vector(
    liked_vectors: list[list[float]],
    disliked_vectors: list[list[float]],
    dislike_weight: float = 0.5,
) -> list[float]:
    liked_mean = mean_vector(liked_vectors)

    if not liked_mean:
        raise ValueError("At least one liked paper is required to update preferences")

    disliked_mean = mean_vector(disliked_vectors)

    if not disliked_mean:
        return liked_mean

    return [
        liked_value - dislike_weight * disliked_value
        for liked_value, disliked_value in zip(liked_mean, disliked_mean)
    ]


def update_preference_embedding(
    user_id: str,
    profile_id: str | None = None,
    conn=None,
) -> None:
    resolved_profile_id = require_profile_id(
        user_id=user_id, profile_id=profile_id, conn=conn
    )

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(FETCH_PREFERENCE_AND_FEEDBACK_SQL, (resolved_profile_id,))
            raw_rows = cur.fetchall()

    if not raw_rows:
        raise ValueError(
            f"No preference profile found for profile_id={resolved_profile_id}"
        )

    feedback_rows = [
        PreferenceFeedbackRow(
            initial_interest_embedding=row[0],
            embedding=row[1],
            label=row[2],
        )
        for row in raw_rows
    ]

    initial_vector = coerce_vector(feedback_rows[0].initial_interest_embedding)

    liked_vectors = [
        coerce_vector(row.embedding)
        for row in feedback_rows
        if row.embedding is not None and row.label == "like"
    ]
    disliked_vectors = [
        coerce_vector(row.embedding)
        for row in feedback_rows
        if row.embedding is not None and row.label == "dislike"
    ]

    num_feedbacks = len(liked_vectors) + len(disliked_vectors)

    if not liked_vectors:
        preference_vector = initial_vector
    else:
        feedback_vector = compute_preference_vector(
            liked_vectors,
            disliked_vectors,
        )
        alpha = feedback_alpha(num_feedbacks)
        preference_vector = blend_vectors(
            initial_vector,
            feedback_vector,
            alpha,
        )

    preference_vector = normalize_vector(preference_vector)
    preference_vector_literal = vector_literal(preference_vector)

    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(
                UPDATE_PREFERENCE_EMBEDDING_SQL,
                (preference_vector_literal, resolved_profile_id),
            )


def reset_all_preference_embeddings(conn=None) -> int:
    with connection_scope(conn) as active_conn:
        with active_conn.cursor() as cur:
            cur.execute(RESET_ALL_PREFERENCE_EMBEDDINGS_SQL)
            return cur.rowcount
