"""
User-facing copy for passwordless sign-in flows
"""

INVALID_EMAIL_MESSAGE = "Please enter a valid email address."
EMAIL_TOO_LONG_MESSAGE = "That email address is too long."
MAGIC_LINK_INVALID_MESSAGE = (
    "This sign-in link is invalid or has expired. Request a new one."
)
EMAIL_DELIVERY_UNAVAILABLE_MESSAGE = (
    "Sign-in email is temporarily unavailable. Please try again later."
)
EMAIL_SEND_FAILED_MESSAGE = (
    "We couldn't send the sign-in email. Please try again in a few minutes."
)
AUTH_SERVER_ERROR_MESSAGE = "Something went wrong on our side. Please try again later."
AUTH_GENERIC_ERROR_MESSAGE = "Something went wrong. Please try again later."
RATE_LIMIT_USER_MESSAGE = "Too many sign-in attempts. Please try again later."
