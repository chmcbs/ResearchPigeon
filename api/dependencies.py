"""
Helpers to wire dependencies into services
"""

from dataclasses import asdict

import psycopg
from fastapi import HTTPException, Request

from api.queries.daily_picks import fetch_latest_picks, fetch_profile_by_id
from api.queries.feedback_hub import fetch_user_paper_history
from api.queries.metrics import fetch_metrics_rows
from api.queries.profiles import fetch_profiles_for_user
from api.schemas import (
    CreateProfileRequest,
    FeedbackRequest,
    RemoveFeedbackRequest,
    DeletePaperRequest,
    GenerateDailyPicksRequest,
    ManageProfileKeywordRequest,
    RequestMagicLinkRequest,
    UpdateProfileRequest,
    UpdateDigestSelectionRequest,
    ReorderProfilesRequest,
    UpdateEmailSettingsRequest,
)
from api.services.auth import (
    request_magic_link_payload as request_magic_link_payload_service,
    verify_magic_link_payload as verify_magic_link_payload_service,
)
from api.services.common import resolve_profile
from api.services.daily_picks import (
    generate_daily_picks_payload as generate_daily_picks_payload_service,
    get_daily_picks_payload as get_daily_picks_payload_service,
    get_debug_daily_picks_payload as get_debug_daily_picks_payload_service,
)
from api.services.feedback import (
    remove_feedback_payload as remove_feedback_payload_service,
    save_feedback_payload as save_feedback_payload_service,
)
from api.services.paper_delete import (
    delete_paper_payload as delete_paper_payload_service,
)
from api.services.errors import InternalServerError, NotFoundError
from api.services.feedback_hub import get_feedback_hub_payload as get_feedback_hub_payload_service
from api.services.metrics import get_metrics_payload as get_metrics_payload_service
from api.services.profiles import (
    add_profile_keyword_payload as add_profile_keyword_payload_service,
    create_profile_payload as create_profile_payload_service,
    delete_profile_payload as delete_profile_payload_service,
    list_profile_keywords_payload as list_profile_keywords_payload_service,
    list_profiles_payload as list_profiles_payload_service,
    remove_profile_keyword_payload as remove_profile_keyword_payload_service,
    update_profile_payload as update_profile_payload_service,
    update_digest_selection_payload as update_digest_selection_payload_service,
    reorder_profiles_payload as reorder_profiles_payload_service,
)
from api.services.debug_digest_reset import reset_papers_and_runs, reset_user_profiles
from api.services.email_settings import (
    get_email_settings_payload as get_email_settings_payload_service,
    update_email_settings_payload as update_email_settings_payload_service,
)
from api.unit_of_work import ApiUnitOfWork, open_api_unit_of_work
from core.auth import (
    create_magic_link,
    get_session_user,
    revoke_session,
    verify_magic_link,
)
from core.config import (
    get_app_base_url,
    get_daily_picks_generate_limit_per_user,
    get_magic_link_request_limit_per_email,
    get_magic_link_request_limit_per_ip,
    get_magic_link_verify_limit_per_ip,
    get_rate_limit_window_seconds,
    is_debug_features_enabled,
    is_dev_magic_link_response_enabled,
    is_trust_proxy_headers_enabled,
)
from core.cron import run_daily_digest_for_all_users
from core.pipeline_progress import get_progress, set_step, track_pipeline
from core.db import get_database_url
from core.email import EmailDeliveryError, send_magic_link_email
from core.email_settings import (
    ensure_email_settings,
    get_digest_subscribed,
    get_email_settings,
    resubscribe_by_token,
    set_digest_subscribed,
    unsubscribe_by_token,
)
from core.rate_limit import RateLimitExceeded, check_rate_limit
from core.security import can_use_debug_features, verify_internal_cron_token
from core.paper_history import dismiss_paper
from core.preferences import (
    initialize_preference_embedding,
    remove_feedback,
    save_feedback,
    update_preference_embedding,
)
from core.profiles import (
    add_profile_keyword,
    create_profile,
    delete_profile,
    list_digest_selected_profile_ids,
    list_profile_keywords,
    remove_profile_keyword,
    set_digest_profile_selection,
    reorder_profiles,
    update_profile,
)


########################################
############### ERRORS #################
########################################

def _to_http_exception(error: Exception) -> HTTPException:
    if isinstance(error, InternalServerError):
        return HTTPException(status_code=500, detail=str(error))
    if isinstance(error, NotFoundError):
        return HTTPException(status_code=404, detail=str(error))
    if isinstance(error, RateLimitExceeded):
        return HTTPException(status_code=429, detail=str(error))
    if isinstance(error, psycopg.Error):
        return HTTPException(status_code=500, detail="Database error")
    return HTTPException(status_code=400, detail=str(error))


def require_internal_cron_token(request: Request) -> None:
    auth_header = request.headers.get("Authorization", "")
    token = (
        auth_header.removeprefix("Bearer ").strip()
        if auth_header.startswith("Bearer ")
        else None
    )
    if not verify_internal_cron_token(token):
        raise HTTPException(status_code=401, detail="Invalid internal cron token")


def _require_debug_admin_session(session: dict) -> None:
    if not is_debug_features_enabled():
        raise HTTPException(status_code=404, detail="Not found")
    if not session["authenticated"]:
        raise HTTPException(status_code=401, detail="Sign in required")
    if not can_use_debug_features(session.get("email")):
        raise HTTPException(
            status_code=403,
            detail="Debug access is restricted to configured admin emails",
        )


def require_debug_admin(request: Request) -> str:
    session = get_auth_session_payload(request.cookies.get("session_id"))
    _require_debug_admin_session(session)
    return str(session["email"])


def _client_ip(request: Request) -> str:
    if is_trust_proxy_headers_enabled():
        forwarded_for = request.headers.get("X-Forwarded-For", "").strip()
        if forwarded_for:
            return forwarded_for.split(",", 1)[0].strip()
        real_ip = request.headers.get("X-Real-IP", "").strip()
        if real_ip:
            return real_ip
    if request.client is None:
        return "unknown"
    return request.client.host


def _enforce_magic_link_request_limits(email: str, client_ip: str) -> None:
    window = get_rate_limit_window_seconds()
    normalized_email = email.strip().lower()
    check_rate_limit(
        f"magic-link:email:{normalized_email}",
        max_attempts=get_magic_link_request_limit_per_email(),
        window_seconds=window,
    )
    check_rate_limit(
        f"magic-link:ip:{client_ip}",
        max_attempts=get_magic_link_request_limit_per_ip(),
        window_seconds=window,
    )


def _enforce_magic_link_verify_limit(client_ip: str) -> None:
    check_rate_limit(
        f"magic-link-verify:ip:{client_ip}",
        max_attempts=get_magic_link_verify_limit_per_ip(),
        window_seconds=get_rate_limit_window_seconds(),
    )


def _enforce_daily_picks_generate_limit(user_id: str) -> None:
    check_rate_limit(
        f"daily-picks-generate:user:{user_id.strip().lower()}",
        max_attempts=get_daily_picks_generate_limit_per_user(),
        window_seconds=get_rate_limit_window_seconds(),
    )


def require_authenticated_user_id(request: Request) -> str:
    session = get_auth_session_payload(request.cookies.get("session_id"))
    if not session["authenticated"] or not session["user_id"]:
        raise HTTPException(status_code=401, detail="Sign in required")
    return str(session["user_id"])


########################################
############## PIPELINE ################
########################################

def _run_pipeline(**kwargs):
    from core.pipeline import run_pipeline

    return run_pipeline(**kwargs)


########################################
########### SHARED ADAPTERS ############
########################################

def _fetch_profile_by_id(profile_id: str, user_id: str, conn=None):
    return fetch_profile_by_id(
        profile_id=profile_id,
        user_id=user_id,
        connect=psycopg.connect,
        database_url=get_database_url(),
        conn=conn,
    )


def _resolve_profile(user_id: str, profile_id: str | None, conn=None) -> dict:
    profile = resolve_profile(
        user_id=user_id,
        profile_id=profile_id,
        fetch_profile_by_id=lambda profile_id, user_id: _fetch_profile_by_id(
            profile_id=profile_id,
            user_id=user_id,
            conn=conn,
        ),
    )
    return profile if isinstance(profile, dict) else asdict(profile)


########################################
############ DAILY PICKS ###############
########################################

def _fetch_latest_picks(profile_id: str, run_ids: list[str] | None = None, conn=None):
    return fetch_latest_picks(
        profile_id=profile_id,
        connect=psycopg.connect,
        database_url=get_database_url(),
        run_ids=run_ids,
        conn=conn,
    )


def get_daily_picks_payload(
    user_id: str,
    profile_id: str | None = None,
    run_ids: list[str] | None = None,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return get_daily_picks_payload_service(
                user_id=user_id,
                profile_id=profile_id,
                anchored_run_ids=run_ids,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                list_digest_selected_profile_ids=lambda user_id: list_digest_selected_profile_ids(
                    user_id=user_id,
                    conn=active_uow.conn,
                ),
                fetch_latest_picks=lambda profile_id: _fetch_latest_picks(
                    profile_id=profile_id,
                    run_ids=run_ids,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def get_debug_daily_picks_payload(
    user_id: str,
    profile_id: str | None = None,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return get_debug_daily_picks_payload_service(
                user_id=user_id,
                profile_id=profile_id,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                fetch_latest_picks=lambda profile_id: _fetch_latest_picks(
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def get_generate_daily_picks_progress_payload(user_id: str) -> dict:
    return get_progress(user_id).as_dict()


def generate_daily_picks_payload(
    request: GenerateDailyPicksRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        _enforce_daily_picks_generate_limit(user_id)
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:

            def run_pipeline_with_uow(**kwargs):
                # End any request-scoped transaction before running pipeline setup.
                # Pipeline opens separate DB connections and may execute DDL that
                # otherwise blocks on locks held by this connection.
                active_uow.conn.commit()
                with track_pipeline(user_id):
                    summary = _run_pipeline(**kwargs)
                    set_step("finishing")
                active_uow.set_generated_run_ids(summary.get("run_ids", []))
                return summary

            return generate_daily_picks_payload_service(
                request=request,
                user_id=user_id,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                run_pipeline=run_pipeline_with_uow,
                get_daily_picks_payload=lambda user_id, profile_id, run_ids=None: get_daily_picks_payload(
                    user_id=user_id,
                    profile_id=profile_id,
                    run_ids=(
                        run_ids if run_ids is not None else active_uow.generated_run_ids
                    ),
                    uow=active_uow,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def debug_reset_digest_data_payload(session_id: str | None) -> dict:
    session = get_auth_session_payload(session_id)
    _require_debug_admin_session(session)
    with open_api_unit_of_work() as uow:
        return reset_papers_and_runs(uow.conn)


########################################
############### FEEDBACK ###############
########################################

def save_feedback_payload(
    request: FeedbackRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return save_feedback_payload_service(
                request=request,
                user_id=user_id,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                save_feedback=lambda **kwargs: save_feedback(
                    conn=active_uow.conn, **kwargs
                ),
                update_preference_embedding=lambda **kwargs: update_preference_embedding(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def remove_feedback_payload(
    request: RemoveFeedbackRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return remove_feedback_payload_service(
                request=request,
                user_id=user_id,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                remove_feedback=lambda **kwargs: remove_feedback(
                    conn=active_uow.conn,
                    **kwargs,
                ),
                update_preference_embedding=lambda **kwargs: update_preference_embedding(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def delete_paper_payload(
    request: DeletePaperRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return delete_paper_payload_service(
                request=request,
                user_id=user_id,
                resolve_profile=lambda user_id, profile_id: _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                ),
                dismiss_paper=lambda **kwargs: dismiss_paper(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def get_feedback_hub_payload(
    user_id: str,
    profile_id: str | None = None,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            if profile_id is not None:
                _resolve_profile(
                    user_id=user_id,
                    profile_id=profile_id,
                    conn=active_uow.conn,
                )
            return get_feedback_hub_payload_service(
                user_id=user_id,
                profile_id=profile_id,
                fetch_user_paper_history=lambda uid, profile_id=None: fetch_user_paper_history(
                    user_id=uid,
                    connect=psycopg.connect,
                    database_url=get_database_url(),
                    conn=active_uow.conn,
                    profile_id=profile_id,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


########################################
############### PROFILES ###############
########################################

def _fetch_profiles_for_user(user_id: str, conn=None):
    return fetch_profiles_for_user(
        user_id=user_id,
        connect=psycopg.connect,
        database_url=get_database_url(),
        conn=conn,
    )


def _require_digest_profile_changes_allowed(user_id: str, conn) -> None:
    if not get_digest_subscribed(user_id, conn=conn):
        raise ValueError("digest emails are turned off")


def create_profile_payload(
    request: CreateProfileRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            ensure_email_settings(user_id, conn=active_uow.conn)
            return create_profile_payload_service(
                request=request,
                user_id=user_id,
                create_profile=lambda **kwargs: create_profile(
                    conn=active_uow.conn, **kwargs
                ),
                initialize_preference_embedding=lambda **kwargs: initialize_preference_embedding(
                    conn=active_uow.conn,
                    **kwargs,
                ),
                list_profiles_payload=lambda user_id: list_profiles_payload(
                    user_id=user_id,
                    uow=active_uow,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def update_profile_payload(
    profile_id: str,
    request: UpdateProfileRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            if request.digest_enabled is not None:
                _require_digest_profile_changes_allowed(
                    user_id,
                    active_uow.conn,
                )
            return update_profile_payload_service(
                profile_id=profile_id,
                request=request,
                user_id=user_id,
                update_profile=lambda **kwargs: update_profile(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def delete_profile_payload(
    profile_id: str,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return delete_profile_payload_service(
                profile_id=profile_id,
                user_id=user_id,
                delete_profile=lambda **kwargs: delete_profile(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def list_profiles_payload(
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return list_profiles_payload_service(
                user_id=user_id,
                fetch_profiles_for_user=lambda user_id: _fetch_profiles_for_user(
                    user_id=user_id,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def update_digest_selection_payload(
    request: UpdateDigestSelectionRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            _require_digest_profile_changes_allowed(user_id, active_uow.conn)
            return update_digest_selection_payload_service(
                request=request,
                user_id=user_id,
                set_digest_profile_selection=lambda **kwargs: set_digest_profile_selection(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


########################################
########### EMAIL SETTINGS #############
########################################

def get_email_settings_payload(
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return get_email_settings_payload_service(
                user_id=user_id,
                get_email_settings=lambda uid: get_email_settings(
                    uid,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def update_email_settings_payload(
    request: UpdateEmailSettingsRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return update_email_settings_payload_service(
                request=request,
                user_id=user_id,
                set_digest_subscribed=lambda uid, digest_subscribed: set_digest_subscribed(
                    uid,
                    digest_subscribed=digest_subscribed,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def unsubscribe_by_token_payload(
    token: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
        user_id = unsubscribe_by_token(token, conn=active_uow.conn)
    return {"user_id": user_id}


def resubscribe_by_token_payload(
    token: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
        user_id = resubscribe_by_token(token, conn=active_uow.conn)
    return {"user_id": user_id}


def reorder_profiles_payload(
    request: ReorderProfilesRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return reorder_profiles_payload_service(
                request=request,
                user_id=user_id,
                reorder_profiles=lambda **kwargs: reorder_profiles(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error
    except psycopg.Error as error:
        raise _to_http_exception(error) from error


def debug_reset_profile_data_payload(session_id: str | None) -> dict:
    session = get_auth_session_payload(session_id)
    _require_debug_admin_session(session)
    with open_api_unit_of_work() as uow:
        return reset_user_profiles(uow.conn)


########################################
############### KEYWORDS ###############
########################################

def add_profile_keyword_payload(
    profile_id: str,
    request: ManageProfileKeywordRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return add_profile_keyword_payload_service(
                profile_id=profile_id,
                request=request,
                user_id=user_id,
                add_profile_keyword=lambda **kwargs: add_profile_keyword(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def remove_profile_keyword_payload(
    profile_id: str,
    request: ManageProfileKeywordRequest,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return remove_profile_keyword_payload_service(
                profile_id=profile_id,
                request=request,
                user_id=user_id,
                remove_profile_keyword=lambda **kwargs: remove_profile_keyword(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def list_profile_keywords_payload(
    profile_id: str,
    user_id: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return list_profile_keywords_payload_service(
                profile_id=profile_id,
                user_id=user_id,
                list_profile_keywords=lambda **kwargs: list_profile_keywords(
                    conn=active_uow.conn,
                    **kwargs,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


########################################
############### METRICS ################
########################################

def _fetch_metrics_rows(latest_runs_limit: int, conn=None):
    return fetch_metrics_rows(
        latest_runs_limit=latest_runs_limit,
        connect=psycopg.connect,
        database_url=get_database_url(),
        conn=conn,
    )


def get_metrics_payload(
    latest_runs_limit: int = 10,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return get_metrics_payload_service(
                latest_runs_limit=latest_runs_limit,
                fetch_metrics_rows=lambda latest_runs_limit: _fetch_metrics_rows(
                    latest_runs_limit=latest_runs_limit,
                    conn=active_uow.conn,
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


########################################
################ AUTH ##################
########################################

def request_magic_link_payload(
    request: RequestMagicLinkRequest,
    client_ip: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        _enforce_magic_link_request_limits(request.email, client_ip)
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return request_magic_link_payload_service(
                request=request,
                create_magic_link=lambda email: create_magic_link(
                    email=email, conn=active_uow.conn
                ),
                send_magic_link_email=send_magic_link_email,
                app_base_url=get_app_base_url(),
                expose_magic_link=is_dev_magic_link_response_enabled(),
            )
    except EmailDeliveryError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    except ValueError as error:
        raise _to_http_exception(error) from error


def verify_magic_link_payload(
    token: str,
    client_ip: str,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    try:
        _enforce_magic_link_verify_limit(client_ip)
        with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
            return verify_magic_link_payload_service(
                token=token,
                verify_magic_link=lambda value: verify_magic_link(
                    token=value, conn=active_uow.conn
                ),
            )
    except ValueError as error:
        raise _to_http_exception(error) from error


def logout_payload(session_id: str | None, conn=None) -> dict:
    if session_id:
        with open_api_unit_of_work(conn=conn) as active_uow:
            revoke_session(session_id=session_id, conn=active_uow.conn)
    return {"logged_out": True}


def get_auth_session_payload(
    session_id: str | None,
    uow: ApiUnitOfWork | None = None,
    conn=None,
) -> dict:
    with open_api_unit_of_work(uow=uow, conn=conn) as active_uow:
        resolved = get_session_user(session_id=session_id or "", conn=active_uow.conn)
    if resolved is None:
        return {
            "authenticated": False,
            "user_id": None,
            "email": None,
            "can_debug_access": False,
        }
    user_id, email = resolved
    return {
        "authenticated": True,
        "user_id": user_id,
        "email": email,
        "can_debug_access": can_use_debug_features(email),
    }


def run_daily_digest_cron_payload() -> dict:
    return run_daily_digest_for_all_users()

