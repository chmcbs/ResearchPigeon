"""
HTTP route definitions for the API service
"""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.dependencies import (
    add_profile_keyword_payload,
    create_profile_payload,
    debug_reset_digest_data_payload,
    debug_reset_profile_data_payload,
    delete_profile_payload,
    get_test_generation_debug_payload,
    get_test_generation_payload,
    get_test_generation_progress_payload,
    get_auth_session_payload,
    run_test_generation_payload,
    get_email_settings_payload,
    get_feedback_hub_payload,
    get_metrics_payload,
    list_profile_keywords_payload,
    list_profiles_payload,
    logout_payload,
    remove_profile_keyword_payload,
    request_magic_link_payload,
    remove_feedback_payload,
    delete_paper_payload,
    require_authenticated_user_id,
    require_debug_admin,
    save_feedback_payload,
    unsubscribe_by_token_payload,
    update_digest_selection_payload,
    update_email_settings_payload,
    reorder_profiles_payload,
    update_profile_payload,
    verify_magic_link_payload,
    _client_ip,
)
from api.middleware import CsrfMiddleware, SecurityHeadersMiddleware
from api.schemas import (
    AuthSessionResponse,
    CreateProfileRequest,
    CreateProfileResponse,
    TestGenerationDebugResponse,
    TestGenerationProgressResponse,
    TestGenerationRequest,
    TestGenerationResponse,
    TestGenerationRunResponse,
    DebugDigestDataResetResponse,
    DebugProfileDataResetResponse,
    FeedbackRequest,
    FeedbackResponse,
    FeedbackHubResponse,
    RemoveFeedbackRequest,
    RemoveFeedbackResponse,
    DeletePaperRequest,
    DeletePaperResponse,
    ListProfilesResponse,
    ManageProfileKeywordRequest,
    ManageProfileKeywordResponse,
    RequestMagicLinkRequest,
    RequestMagicLinkResponse,
    ReorderProfilesRequest,
    ReorderProfilesResponse,
    UpdateDigestSelectionRequest,
    UpdateDigestSelectionResponse,
    UpdateProfileRequest,
    UpdateProfileResponse,
    DeleteProfileResponse,
    EmailSettingsResponse,
    UpdateEmailSettingsRequest,
)
from core.config import get_arxiv_category_options, get_product_name, is_app_https, is_debug_features_enabled, is_production
from core.db import check_database_connection
from core.logging import configure_logging
from core.security import (
    CSRF_COOKIE_NAME,
    csrf_cookie_settings,
    generate_csrf_token,
    resolve_safe_redirect_path,
)
from core.startup import validate_runtime_config


########################################
############### SETUP ##################
########################################

@asynccontextmanager
async def _app_lifespan(_app: FastAPI):
    validate_runtime_config()
    yield


_docs_url = None if is_production() else "/docs"
app = FastAPI(
    title=f"{get_product_name()} API",
    docs_url=_docs_url,
    redoc_url=_docs_url,
    openapi_url=None if is_production() else "/openapi.json",
    lifespan=_app_lifespan,
)
configure_logging()
app.add_middleware(CsrfMiddleware)
app.add_middleware(SecurityHeadersMiddleware)
frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
app.mount("/static", StaticFiles(directory=str(frontend_dir / "static")), name="static")


def _set_session_cookie(response: Response, session_id: str) -> None:
    response.set_cookie(
        key="session_id",
        value=session_id,
        httponly=True,
        samesite="lax",
        secure=is_app_https(),
        max_age=60 * 60 * 24 * 30,
        path="/",
    )


def _set_csrf_cookie(response: Response, *, token: str | None = None) -> None:
    response.set_cookie(value=token or generate_csrf_token(), **csrf_cookie_settings())


def _ensure_authenticated_csrf(response: Response, request: Request, authenticated: bool) -> None:
    if authenticated:
        _set_csrf_cookie(response, token=request.cookies.get("csrf_token"))


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(
        key="session_id",
        httponly=True,
        samesite="lax",
        secure=is_app_https(),
        path="/",
    )
    csrf_settings = csrf_cookie_settings()
    response.delete_cookie(
        key=CSRF_COOKIE_NAME,
        httponly=csrf_settings["httponly"],
        samesite=csrf_settings["samesite"],
        secure=csrf_settings["secure"],
        path="/",
    )


########################################
################# UI ###################
########################################

@app.get("/", response_class=FileResponse)
def landing_page() -> FileResponse:
    return FileResponse(frontend_dir / "index.html")


@app.get("/profiles", response_class=FileResponse)
def profiles_page() -> FileResponse:
    return FileResponse(frontend_dir / "preferences.html")


@app.get("/preferences")
def preferences_page_redirect() -> RedirectResponse:
    return RedirectResponse("/profiles", status_code=307)


@app.get("/digest", response_class=FileResponse)
def digest_page() -> FileResponse:
    if not is_debug_features_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(frontend_dir / "digest.html")


@app.get("/papers", response_class=FileResponse)
def papers_page() -> FileResponse:
    return FileResponse(frontend_dir / "feedback.html")


@app.get("/about", response_class=FileResponse)
def about_page() -> FileResponse:
    return FileResponse(frontend_dir / "about.html")


@app.get("/validate", response_class=FileResponse)
def validate(request: Request) -> FileResponse:
    require_debug_admin(request)
    return FileResponse(frontend_dir / "validate.html")


@app.get("/email/preferences", response_class=FileResponse)
def email_preferences_page() -> FileResponse:
    return FileResponse(frontend_dir / "email-preferences.html")


@app.get("/email/unsubscribe")
def email_unsubscribe(token: str) -> RedirectResponse:
    payload = unsubscribe_by_token_payload(token=token)
    if payload["user_id"] is None:
        response = RedirectResponse(
            url="/email/preferences?status=invalid",
            status_code=302,
        )
    else:
        response = RedirectResponse(
            url="/email/preferences?status=unsubscribed",
            status_code=302,
        )
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return response


@app.get("/site-config")
def site_config() -> dict:
    return {"product_name": get_product_name()}


@app.get("/categories")
def categories() -> dict:
    return {"categories": get_arxiv_category_options()}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    try:
        check_database_connection()
    except Exception as error:
        raise HTTPException(
            status_code=503,
            detail="database unavailable",
        ) from error
    return {"status": "ready"}


########################################
################# AUTH #################
########################################

@app.post("/auth/magic-link/request", response_model=RequestMagicLinkResponse)
def auth_request_magic_link(body: RequestMagicLinkRequest, request: Request) -> dict:
    return request_magic_link_payload(body, client_ip=_client_ip(request))


@app.get("/auth/magic-link/verify")
def auth_verify_magic_link(
    token: str,
    request: Request,
    next: str = "/profiles",
) -> RedirectResponse:
    payload = verify_magic_link_payload(token=token, client_ip=_client_ip(request))
    redirect_target = resolve_safe_redirect_path(next, email=payload["email"])
    response = RedirectResponse(url=redirect_target, status_code=302)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    _set_session_cookie(response, payload["session_id"])
    _set_csrf_cookie(response, token=generate_csrf_token())
    return response


@app.post("/auth/logout")
def auth_logout(request: Request, response: Response) -> dict:
    payload = logout_payload(request.cookies.get("session_id"))
    _clear_auth_cookies(response)
    return payload


@app.get("/auth/session", response_model=AuthSessionResponse)
def auth_session(request: Request, response: Response) -> dict:
    payload = get_auth_session_payload(request.cookies.get("session_id"))
    _ensure_authenticated_csrf(response, request, payload["authenticated"])
    return payload


########################################
########## TEST GENERATION #############
########################################

@app.get("/test-generation", response_model=TestGenerationResponse)
def test_generation(
    request: Request,
    profile_id: str | None = None,
) -> dict:
    require_debug_admin(request)
    user_id = require_authenticated_user_id(request)
    return get_test_generation_payload(
        user_id=user_id,
        profile_id=profile_id,
    )


@app.get("/test-generation/debug", response_model=TestGenerationDebugResponse)
def test_generation_debug(
    request: Request,
    profile_id: str,
) -> dict:
    require_debug_admin(request)
    user_id = require_authenticated_user_id(request)
    return get_test_generation_debug_payload(
        user_id=user_id,
        profile_id=profile_id,
    )


@app.get(
    "/test-generation/progress",
    response_model=TestGenerationProgressResponse,
)
def test_generation_progress(request: Request) -> dict:
    require_debug_admin(request)
    user_id = require_authenticated_user_id(request)
    return get_test_generation_progress_payload(user_id)


@app.post("/test-generation/run", response_model=TestGenerationRunResponse)
def test_generation_run(
    body: TestGenerationRequest,
    request: Request,
) -> dict:
    admin_email = require_debug_admin(request)
    user_id = require_authenticated_user_id(request)
    return run_test_generation_payload(
        body,
        user_id=user_id,
        admin_email=admin_email,
    )


########################################
############### FEEDBACK ###############
########################################

@app.get("/api/papers/hub", response_model=FeedbackHubResponse)
def papers_hub(
    request: Request,
    profile_id: str | None = None,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return get_feedback_hub_payload(
        user_id=user_id,
        profile_id=profile_id,
    )


@app.post("/api/feedback", response_model=FeedbackResponse)
def feedback_create(body: FeedbackRequest, request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return save_feedback_payload(body, user_id=user_id)


@app.delete("/api/feedback", response_model=RemoveFeedbackResponse)
def feedback_delete(body: RemoveFeedbackRequest, request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return remove_feedback_payload(body, user_id=user_id)


@app.delete("/api/papers", response_model=DeletePaperResponse)
def papers_delete(body: DeletePaperRequest, request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return delete_paper_payload(body, user_id=user_id)


########################################
############### PROFILES ###############
########################################

@app.post("/api/profiles", response_model=CreateProfileResponse)
def profiles_create(body: CreateProfileRequest, request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return create_profile_payload(body, user_id=user_id)


@app.get("/api/profiles", response_model=ListProfilesResponse)
def profiles_list(request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return list_profiles_payload(user_id=user_id)




@app.put("/api/profiles/digest-selection", response_model=UpdateDigestSelectionResponse)
def profiles_digest_selection_update(
    body: UpdateDigestSelectionRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return update_digest_selection_payload(body, user_id=user_id)


@app.put("/api/profiles/order", response_model=ReorderProfilesResponse)
def profiles_order_update(
    body: ReorderProfilesRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return reorder_profiles_payload(body, user_id=user_id)


@app.put("/api/profiles/{profile_id}", response_model=UpdateProfileResponse)
def profiles_update(
    profile_id: str,
    body: UpdateProfileRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return update_profile_payload(profile_id=profile_id, request=body, user_id=user_id)


@app.delete("/api/profiles/{profile_id}", response_model=DeleteProfileResponse)
def profiles_delete(profile_id: str, request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return delete_profile_payload(profile_id=profile_id, user_id=user_id)


########################################
########### EMAIL SETTINGS #############
########################################

@app.get("/api/email-settings", response_model=EmailSettingsResponse)
def email_settings_get(request: Request) -> dict:
    user_id = require_authenticated_user_id(request)
    return get_email_settings_payload(user_id=user_id)


@app.patch("/api/email-settings", response_model=EmailSettingsResponse)
def email_settings_update(
    body: UpdateEmailSettingsRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return update_email_settings_payload(body, user_id=user_id)

########################################
############### KEYWORDS ###############
########################################

@app.get(
    "/api/profiles/{profile_id}/keywords", response_model=ManageProfileKeywordResponse
)
def profiles_keywords_list(
    request: Request,
    profile_id: str,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return list_profile_keywords_payload(
        profile_id=profile_id,
        user_id=user_id,
    )


@app.post(
    "/api/profiles/{profile_id}/keywords",
    response_model=ManageProfileKeywordResponse,
)
def profiles_keywords_add(
    profile_id: str,
    body: ManageProfileKeywordRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return add_profile_keyword_payload(
        profile_id=profile_id,
        request=body,
        user_id=user_id,
    )


@app.delete(
    "/api/profiles/{profile_id}/keywords",
    response_model=ManageProfileKeywordResponse,
)
def profiles_keywords_remove(
    profile_id: str,
    body: ManageProfileKeywordRequest,
    request: Request,
) -> dict:
    user_id = require_authenticated_user_id(request)
    return remove_profile_keyword_payload(
        profile_id=profile_id,
        request=body,
        user_id=user_id,
    )


########################################
################ DEBUG #################
########################################

@app.post("/debug/digest-data/reset", response_model=DebugDigestDataResetResponse)
def debug_reset_digest_data(request: Request) -> dict:
    return debug_reset_digest_data_payload(request.cookies.get("session_id"))

@app.post("/debug/profile-data/reset", response_model=DebugProfileDataResetResponse)
def debug_reset_profile_data(request: Request) -> dict:
    return debug_reset_profile_data_payload(request.cookies.get("session_id"))

########################################
############### METRICS ################
########################################

@app.get("/metrics")
def metrics(request: Request, latest_runs_limit: int = 10) -> dict:
    require_debug_admin(request)
    if latest_runs_limit < 1:
        raise HTTPException(status_code=400, detail="latest_runs_limit must be >= 1")

    return get_metrics_payload(latest_runs_limit=latest_runs_limit)


