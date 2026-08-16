"""
Custom throttle classes for authentication endpoints.
"""
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle


class LoginThrottle(AnonRateThrottle):
    """5 login attempts per minute per IP."""
    scope = 'login'


class RegisterThrottle(AnonRateThrottle):
    """10 registrations per hour per IP."""
    scope = 'register'


class PasswordResetThrottle(AnonRateThrottle):
    """3 password reset requests per hour per IP."""
    scope = 'password_reset'


class OTPRequestThrottle(AnonRateThrottle):
    """3 OTP requests per hour per IP (in addition to per-user cooldown)."""
    scope = 'otp_request'


class TwoFAThrottle(UserRateThrottle):
    """10 2FA attempts per minute per user (post-auth)."""
    scope = '2fa'