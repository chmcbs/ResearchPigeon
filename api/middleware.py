"""
HTTP middleware for security headers and CSRF enforcement
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from core.config import is_app_https
from core.security import CSRF_HEADER_NAME, validate_csrf_token

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})

CSRF_EXEMPT_PATHS = frozenset(
    {
        "/auth/magic-link/request",
        "/auth/magic-link/verify",
    }
)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "geolocation=(), microphone=(), camera=()",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    ),
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        for header_name, header_value in SECURITY_HEADERS.items():
            if header_name not in response.headers:
                response.headers[header_name] = header_value
        if is_app_https() and "Strict-Transport-Security" not in response.headers:
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        return response


class CsrfMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        if request.method in UNSAFE_METHODS and request.url.path not in CSRF_EXEMPT_PATHS:
            cookie_token = request.cookies.get("csrf_token")
            header_token = request.headers.get(CSRF_HEADER_NAME)
            if not validate_csrf_token(cookie_token, header_token):
                return JSONResponse(
                    status_code=403,
                    content={"detail": "CSRF validation failed"},
                )
        return await call_next(request)
