"""
HTTP route definitions for the API service
"""

from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import (
    add_profile_keyword_payload,
    create_profile_payload,
    debug_reset_digest_data_payload,
    debug_reset_profile_data_payload,
    delete_profile_payload,
    generate_daily_picks_payload,
    get_auth_session_payload,
    get_daily_picks_payload,
    get_debug_daily_picks_payload,
    get_metrics_payload,
    list_profile_keywords_payload,
    list_profiles_payload,
    remove_profile_keyword_payload,
    request_magic_link_payload,
    get_feedback_hub_payload,
    remove_feedback_payload,
    save_feedback_payload,
    update_digest_selection_payload,
    update_profile_payload,
    verify_magic_link_payload,
)
from api.schemas import (
    AuthSessionResponse,
    CreateProfileRequest,
    CreateProfileResponse,
    DailyPicksResponse,
    DebugDailyPicksResponse,
    DebugDigestDataResetResponse,
    DebugProfileDataResetResponse,
    DeleteProfileRequest,
    DeleteProfileResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackHubResponse,
    RemoveFeedbackRequest,
    RemoveFeedbackResponse,
    GenerateDailyPicksRequest,
    GenerateDailyPicksResponse,
    ListProfilesResponse,
    ManageProfileKeywordRequest,
    ManageProfileKeywordResponse,
    RequestMagicLinkRequest,
    RequestMagicLinkResponse,
    UpdateDigestSelectionRequest,
    UpdateDigestSelectionResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
)
from core.config import DEFAULT_USER_ID, get_arxiv_categories


########################################
############### SETUP ##################
########################################

app = FastAPI(title="arXiv Assistant API")
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")


def _resolve_user_id(explicit_user_id: str, request: Request) -> str:
    if explicit_user_id != DEFAULT_USER_ID:
        return explicit_user_id
    session = get_auth_session_payload(request.cookies.get("session_id"))
    if session["authenticated"]:
        return str(session["user_id"])
    return explicit_user_id


########################################
################# UI ###################
########################################

@app.get("/", response_class=FileResponse)
def landing_page() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/preferences", response_class=FileResponse)
def preferences_page() -> FileResponse:
    return FileResponse(frontend_dir / "preferences.html")


@app.get("/digest", response_class=FileResponse)
def digest_page() -> FileResponse:
    return FileResponse(frontend_dir / "digest.html")


@app.get("/feedback", response_class=FileResponse)
def feedback_page() -> FileResponse:
    return FileResponse(frontend_dir / "feedback.html")


@app.get("/validate", response_class=FileResponse)
def validate() -> FileResponse:
    return FileResponse(frontend_dir / "validate.html")


@app.get("/categories")
def categories() -> dict:
    return {"categories": get_arxiv_categories()}


########################################
################# AUTH #################
########################################

@app.post("/auth/magic-link/request", response_model=RequestMagicLinkResponse)
def auth_request_magic_link(request: RequestMagicLinkRequest) -> dict:
    return request_magic_link_payload(request)


@app.get("/auth/magic-link/verify")
def auth_verify_magic_link(token: str, next: str = "/preferences") -> RedirectResponse:
    payload = verify_magic_link_payload(token=token)
    redirect_target = next if next.startswith("/") else "/preferences"
    response = RedirectResponse(url=redirect_target, status_code=302)
    response.set_cookie(
        key="session_id",
        value=payload["session_id"],
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return response


@app.get("/auth/session", response_model=AuthSessionResponse)
def auth_session(request: Request) -> dict:
    return get_auth_session_payload(request.cookies.get("session_id"))


########################################
############# DAILY PICKS ##############
########################################

@app.get("/daily-picks", response_model=DailyPicksResponse)
def daily_picks(
    request: Request,
    user_id: str = DEFAULT_USER_ID,
    profile_id: str | None = None,
) -> dict:
    return get_daily_picks_payload(
        user_id=_resolve_user_id(user_id, request),
        profile_id=profile_id,
    )


@app.get("/daily-picks/debug", response_model=DebugDailyPicksResponse)
def daily_picks_debug(
    request: Request,
    profile_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    return get_debug_daily_picks_payload(
        user_id=_resolve_user_id(user_id, request),
        profile_id=profile_id,
    )


@app.post("/daily-picks/generate", response_model=GenerateDailyPicksResponse)
def daily_picks_generate(request: GenerateDailyPicksRequest, http_request: Request) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return generate_daily_picks_payload(request)


@app.post("/debug/digest-data/reset", response_model=DebugDigestDataResetResponse)
def debug_reset_digest_data(request: Request) -> dict:
    return debug_reset_digest_data_payload(request.cookies.get("session_id"))


########################################
############### FEEDBACK ###############
########################################

@app.get("/api/feedback/hub", response_model=FeedbackHubResponse)
def feedback_hub(
    request: Request,
    user_id: str = DEFAULT_USER_ID,
    profile_id: str | None = None,
) -> dict:
    return get_feedback_hub_payload(
        user_id=_resolve_user_id(user_id, request),
        profile_id=profile_id,
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
def feedback_create(request: FeedbackRequest, http_request: Request) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return save_feedback_payload(request)


@app.delete("/api/feedback", response_model=RemoveFeedbackResponse)
def feedback_delete(request: RemoveFeedbackRequest, http_request: Request) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return remove_feedback_payload(request)


########################################
############### PROFILES ###############
########################################

@app.post("/profiles", response_model=CreateProfileResponse)
def profiles_create(request: CreateProfileRequest, http_request: Request) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return create_profile_payload(request)


@app.get("/profiles", response_model=ListProfilesResponse)
def profiles_list(request: Request, user_id: str = DEFAULT_USER_ID) -> dict:
    return list_profiles_payload(user_id=_resolve_user_id(user_id, request))


@app.put("/profiles/digest-selection", response_model=UpdateDigestSelectionResponse)
def profiles_digest_selection_update(
    request: UpdateDigestSelectionRequest,
    http_request: Request,
) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return update_digest_selection_payload(request)


@app.put("/profiles/{profile_id}", response_model=UpdateProfileResponse)
def profiles_update(
    profile_id: str,
    request: UpdateProfileRequest,
    http_request: Request,
) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return update_profile_payload(profile_id=profile_id, request=request)


@app.delete("/profiles/{profile_id}", response_model=DeleteProfileResponse)
def profiles_delete(
    profile_id: str,
    http_request: Request,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    request = DeleteProfileRequest(
        user_id=_resolve_user_id(user_id, http_request),
    )
    return delete_profile_payload(profile_id=profile_id, request=request)


@app.post("/debug/profile-data/reset", response_model=DebugProfileDataResetResponse)
def debug_reset_profile_data(request: Request) -> dict:
    return debug_reset_profile_data_payload(request.cookies.get("session_id"))


########################################
############### KEYWORDS ###############
########################################

@app.get("/profiles/{profile_id}/keywords", response_model=ManageProfileKeywordResponse)
def profiles_keywords_list(
    request: Request,
    profile_id: str,
    user_id: str = DEFAULT_USER_ID,
) -> dict:
    return list_profile_keywords_payload(
        profile_id=profile_id,
        user_id=_resolve_user_id(user_id, request),
    )


@app.post(
    "/profiles/{profile_id}/keywords", response_model=ManageProfileKeywordResponse
)
def profiles_keywords_add(
    profile_id: str,
    request: ManageProfileKeywordRequest,
    http_request: Request,
) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return add_profile_keyword_payload(profile_id=profile_id, request=request)


@app.delete(
    "/profiles/{profile_id}/keywords", response_model=ManageProfileKeywordResponse
)
def profiles_keywords_remove(
    profile_id: str,
    request: ManageProfileKeywordRequest,
    http_request: Request,
) -> dict:
    request.user_id = _resolve_user_id(request.user_id, http_request)
    return remove_profile_keyword_payload(profile_id=profile_id, request=request)


########################################
############### METRICS ################
########################################

@app.get("/metrics")
def metrics(latest_runs_limit: int = 10) -> dict:
    if latest_runs_limit < 1:
        raise HTTPException(status_code=400, detail="latest_runs_limit must be >= 1")

    return get_metrics_payload(latest_runs_limit=latest_runs_limit)
