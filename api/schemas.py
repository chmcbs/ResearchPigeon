"""
Pydantic models used by API routes and helper payloads
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from core.config import DEFAULT_INTEREST_TEXT, get_arxiv_categories


class PublicPick(BaseModel):
    rank: int
    arxiv_id: str
    title: str
    abstract: str
    description: str | None = None
    pdf_url: str | None
    final_score: float


class DebugPick(PublicPick):
    run_id: str
    category: str
    generated_at: datetime
    base_dense_score: float
    keyword_boost: float
    candidate_window: str
    fallback_stage: int


class ProfileSummary(BaseModel):
    profile_id: str
    user_id: str
    profile_slot: int
    profile_name: str | None = None
    category: str
    interest_sentence: str
    digest_enabled: bool
    keywords: list[str]
    created_at: datetime
    preference_updated_at: datetime | None = None


class DigestSection(BaseModel):
    profile_id: str
    profile_slot: int
    profile_name: str | None = None
    category: str
    interest_sentence: str
    needs_generation: bool
    picks: list[PublicPick]


class DailyPicksResponse(BaseModel):
    user_id: str
    profile_id: str
    needs_generation: bool
    picks: list[PublicPick]
    sections: list[DigestSection]


class DebugDailyPicksResponse(BaseModel):
    user_id: str
    profile_id: str
    needs_generation: bool
    run_id: str | None = None
    category: str | None = None
    generated_at: datetime | None = None
    picks: list[DebugPick]


class GenerateDailyPicksRequest(BaseModel):
    profile_ids: list[str] = Field(min_length=1)
    max_results: int = Field(default=150, ge=1)
    embedding_limit: int = Field(default=600, ge=1)


class GenerationProfileStatus(BaseModel):
    profile_id: str
    status: Literal["succeeded", "failed"]
    recommendation_count: int = Field(ge=0)
    error_message: str | None = None


class GenerationRunStatus(BaseModel):
    run_id: str
    profile_statuses: list[GenerationProfileStatus]


class GenerateDailyPicksProgressResponse(BaseModel):
    active: bool
    step: str | None = None
    label: str | None = None
    detail: str | None = None
    updated_at: datetime | None = None


class GenerateDailyPicksResponse(BaseModel):
    user_id: str
    primary_profile_id: str
    requested_profile_ids: list[str]
    run_ids: list[str]
    embedded_count: int
    generation_runs: list[GenerationRunStatus]
    has_failures: bool
    needs_generation: bool
    picks: list[PublicPick]
    sections: list[DigestSection]


class FeedbackRequest(BaseModel):
    arxiv_id: str
    label: Literal["like", "dislike"]
    profile_id: str


class FeedbackResponse(BaseModel):
    feedback_id: str
    user_id: str
    profile_id: str
    arxiv_id: str
    label: Literal["like", "dislike"]
    preference_updated: bool


class RemoveFeedbackRequest(BaseModel):
    arxiv_id: str
    profile_id: str


class RemoveFeedbackResponse(BaseModel):
    user_id: str
    profile_id: str
    arxiv_id: str
    removed: bool
    preference_updated: bool


class DeletePaperRequest(BaseModel):
    arxiv_id: str
    profile_id: str


class DeletePaperResponse(BaseModel):
    user_id: str
    profile_id: str
    arxiv_id: str
    dismissed: bool
    feedback_removed: bool
    recommendations_removed: int
    preference_updated: bool


class FeedbackHubPaper(BaseModel):
    arxiv_id: str
    title: str
    pdf_url: str | None = None
    profile_id: str
    profile_name: str
    category: str
    generated_at: datetime
    final_score: float
    rank: int


class FeedbackHubResponse(BaseModel):
    user_id: str
    seen: list[FeedbackHubPaper]
    liked: list[FeedbackHubPaper]
    disliked: list[FeedbackHubPaper]


class CreateProfileRequest(BaseModel):
    profile_name: str = "Profile"
    category: str = Field(default_factory=lambda: get_arxiv_categories()[0])
    interest_sentence: str = DEFAULT_INTEREST_TEXT


class CreateProfileResponse(BaseModel):
    profile: ProfileSummary


class ListProfilesResponse(BaseModel):
    user_id: str
    profiles: list[ProfileSummary]


class UpdateProfileRequest(BaseModel):
    profile_name: str | None = None
    category: str | None = None
    digest_enabled: bool | None = None


class UpdateProfileResponse(BaseModel):
    profile: ProfileSummary


class DeleteProfileResponse(BaseModel):
    profile_id: str
    deleted: bool


class ManageProfileKeywordRequest(BaseModel):
    keyword: str


class ManageProfileKeywordResponse(BaseModel):
    user_id: str
    profile_id: str
    keywords: list[str]


class UpdateDigestSelectionRequest(BaseModel):
    profile_ids: list[str]


class UpdateDigestSelectionResponse(BaseModel):
    user_id: str
    selected_profile_ids: list[str]


class ReorderProfilesRequest(BaseModel):
    profile_ids: list[str] = Field(min_length=1)


class ReorderProfilesResponse(BaseModel):
    user_id: str
    profile_ids: list[str]


class RequestMagicLinkRequest(BaseModel):
    email: str


class RequestMagicLinkResponse(BaseModel):
    sent: bool
    magic_link: str | None = None


class AuthSessionResponse(BaseModel):
    authenticated: bool
    user_id: str | None = None
    email: str | None = None
    can_debug_access: bool = False


class DebugDigestDataResetResponse(BaseModel):
    deleted_runs: int
    deleted_papers: int


class DebugProfileDataResetResponse(BaseModel):
    deleted_profiles: int


class CronDailyDigestUserResult(BaseModel):
    user_id: str
    status: Literal["succeeded", "failed", "skipped"]
    profile_ids: list[str]
    run_ids: list[str] = Field(default_factory=list)
    error_message: str | None = None


class CronDailyDigestResponse(BaseModel):
    users_seen: int
    users_succeeded: int
    users_failed: int
    users_skipped: int
    results: list[CronDailyDigestUserResult]
