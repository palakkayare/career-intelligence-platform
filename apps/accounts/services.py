"""
Business logic for OTP operations.
Keeps views clean, makes testing easy.
"""

import base64
import secrets as py_secrets
from datetime import timedelta
from io import BytesIO

import pyotp
import qrcode
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.mail import send_mail
from django.core.signing import BadSignature, SignatureExpired, TimestampSigner
from django.template.loader import render_to_string
from django.utils import timezone
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token
from rest_framework.exceptions import AuthenticationFailed, ValidationError

from .models import BackupCode, OTPCode, TwoFactorAuth

User = get_user_model()


User = get_user_model()


class OTPService:
    """Service for generating, sending, and verifying OTP codes."""

    OTP_VALIDITY_MINUTES = 10
    RESEND_COOLDOWN_SECONDS = 60  # Spam prevention

    @classmethod
    def create_and_send(cls, user, purpose=OTPCode.Purpose.EMAIL_VERIFICATION):
        """
        Generate a new OTP and email it to the user.
        Invalidates any previous unused OTPs for the same purpose.
        """
        # Cooldown check — when was the last OTP sent?
        recent = OTPCode.objects.filter(
            user=user,
            purpose=purpose,
        ).first()

        if recent and not recent.is_used:
            seconds_since = (timezone.now() - recent.created_at).total_seconds()
            if seconds_since < cls.RESEND_COOLDOWN_SECONDS:
                wait = int(cls.RESEND_COOLDOWN_SECONDS - seconds_since)
                raise ValidationError(f"Please wait {wait} seconds before requesting another code.")

        # Invalidate previous OTPs (clean slate)
        OTPCode.objects.filter(
            user=user,
            purpose=purpose,
            is_used=False,
        ).update(is_used=True, used_at=timezone.now())

        # Generate new OTP
        otp = OTPCode.objects.create(
            user=user,
            code=OTPCode.generate_code(),
            purpose=purpose,
            expires_at=timezone.now() + timedelta(minutes=cls.OTP_VALIDITY_MINUTES),
        )

        # Send email
        cls._send_email(user, otp)

        return otp

    @classmethod
    def verify(cls, user, code, purpose=OTPCode.Purpose.EMAIL_VERIFICATION):
        """
        Verify OTP. Raises ValidationError on failure.
        Returns the OTP instance on success.
        """
        otp = (
            OTPCode.objects.filter(
                user=user,
                purpose=purpose,
                is_used=False,
            )
            .order_by("-created_at")
            .first()
        )

        if not otp:
            raise ValidationError("No valid OTP found. Please request a new one.")

        # Increment attempts FIRST (counts even if wrong)
        otp.attempts += 1
        otp.save(update_fields=["attempts"])

        # Validity checks
        if otp.is_expired:
            raise ValidationError("OTP expired. Please request a new one.")

        if otp.attempts > otp.max_attempts:
            otp.mark_used()  # Block this OTP
            raise ValidationError("Too many attempts. Request a new OTP.")

        # Constant-time comparison (prevents timing attacks)
        if not cls._constant_time_compare(otp.code, code):
            raise ValidationError(f"Invalid OTP. {otp.max_attempts - otp.attempts} attempts left.")

        # Success
        otp.mark_used()
        return otp

    @staticmethod
    def _constant_time_compare(a, b):
        """
        Compare two strings in constant time.
        Prevents timing attacks where an attacker measures comparison time
        to figure out a partial OTP match.
        """
        from hmac import compare_digest

        return compare_digest(str(a), str(b))

    @staticmethod
    def _send_email(user, otp):
        """Send OTP email — for now just plain text via the console backend."""
        subject_map = {
            OTPCode.Purpose.EMAIL_VERIFICATION: "Verify your email",
            OTPCode.Purpose.TWO_FA: "Your 2FA code",
            OTPCode.Purpose.SENSITIVE_ACTION: "Confirm your action",
        }

        context = {
            "user": user,
            "code": otp.code,
            "validity_minutes": OTPService.OTP_VALIDITY_MINUTES,
        }

        body = render_to_string("accounts/email_otp.txt", context)

        send_mail(
            subject=subject_map.get(otp.purpose, "Your OTP"),
            message=body,
            from_email=None,  # Uses DEFAULT_FROM_EMAIL
            recipient_list=[user.email],
            fail_silently=False,
        )


class GoogleOAuthService:
    """Handles Google OAuth ID token verification and user provisioning."""

    @classmethod
    def verify_id_token(cls, token):
        """
        Verify Google ID token and return user info.
        Raises AuthenticationFailed on invalid token.
        """
        try:
            idinfo = id_token.verify_oauth2_token(
                token,
                google_requests.Request(),
                settings.GOOGLE_OAUTH_CLIENT_ID,
            )
        except ValueError as e:
            raise AuthenticationFailed(f"Invalid Google token: {str(e)}")

        # Verify issuer (extra safety, library does this too)
        if idinfo["iss"] not in ("accounts.google.com", "https://accounts.google.com"):
            raise AuthenticationFailed("Wrong token issuer.")

        # Email must be verified by Google
        if not idinfo.get("email_verified", False):
            raise AuthenticationFailed("Google email not verified.")

        return {
            "sub": idinfo["sub"],
            "email": idinfo["email"].lower(),
            "name": idinfo.get("name", ""),
            "picture": idinfo.get("picture", ""),
        }

    @classmethod
    def get_or_create_user(cls, google_info, role="seeker"):
        """
        Find existing user by google_sub or email, or create new.
        Returns (user, created) tuple.
        """
        # 1. Try to find by google_sub (most reliable)
        try:
            user = User.objects.get(google_sub=google_info["sub"])
            return user, False
        except User.DoesNotExist:
            pass

        # 2. Try to find by email (account linking)
        try:
            user = User.objects.get(email=google_info["email"])
            # Existing email/password user — link Google account
            # (Safe because Google has verified the email)
            user.google_sub = google_info["sub"]
            if not user.full_name:
                user.full_name = google_info["name"]
            if not user.profile_picture_url:
                user.profile_picture_url = google_info["picture"]
            if not user.is_email_verified:
                user.is_email_verified = True  # Verified by Google
            user.save(
                update_fields=[
                    "google_sub",
                    "full_name",
                    "profile_picture_url",
                    "is_email_verified",
                ]
            )
            return user, False
        except User.DoesNotExist:
            pass

        # 3. Create new user
        user = User.objects.create_oauth_user(
            email=google_info["email"],
            google_sub=google_info["sub"],
            full_name=google_info["name"],
            picture=google_info["picture"],
            role=role,
        )
        return user, True

    @classmethod
    def authenticate(cls, token, role="seeker"):
        """
        Full flow: verify token → get/create user → return user.
        """
        google_info = cls.verify_id_token(token)
        user, created = cls.get_or_create_user(google_info, role=role)
        return user, created


class TwoFactorAuthService:
    """Service for 2FA setup, verification, and management."""

    BACKUP_CODE_COUNT = 10
    BACKUP_CODE_LENGTH = 8  # 8 hex characters
    TOTP_VALID_WINDOW = 1  # ±30 seconds tolerance for clock drift

    @classmethod
    def initiate_setup(cls, user):
        """
        Generate TOTP secret + QR code for user.
        Does NOT enable 2FA yet — user must verify first.
        """
        # Generate cryptographically secure secret
        secret = pyotp.random_base32()

        # Save (or update) TwoFactorAuth record (not enabled yet)
        twofa, _ = TwoFactorAuth.objects.update_or_create(
            user=user,
            defaults={
                "secret": secret,
                "is_enabled": False,
                "enabled_at": None,
            },
        )

        # Generate provisioning URI
        totp = pyotp.TOTP(secret)
        uri = totp.provisioning_uri(
            name=user.email,
            issuer_name=getattr(settings, "TOTP_ISSUER_NAME", "Career Intelligence"),
        )

        # Generate QR code as base64 image
        qr_base64 = cls._generate_qr_base64(uri)

        return {
            "qr_code": f"data:image/png;base64,{qr_base64}",
            "secret_text": secret,  # For manual entry option
            "provisioning_uri": uri,
        }

    @classmethod
    def verify_and_enable(cls, user, code):
        """
        User entered first TOTP code → verify it → enable 2FA → generate backup codes.
        """
        try:
            twofa = user.two_factor
        except TwoFactorAuth.DoesNotExist:
            raise ValidationError("2FA setup not initiated. Call /2fa/setup/ first.")

        if twofa.is_enabled:
            raise ValidationError("2FA is already enabled.")

        # Verify TOTP code
        if not cls._verify_totp(twofa.secret, code):
            raise ValidationError("Invalid code. Please try again.")

        # Enable
        twofa.is_enabled = True
        twofa.enabled_at = timezone.now()
        twofa.save(update_fields=["is_enabled", "enabled_at"])

        # Update User flag
        user.is_2fa_enabled = True
        user.save(update_fields=["is_2fa_enabled"])

        # Generate fresh backup codes
        backup_codes = cls._generate_backup_codes(user)

        return backup_codes  # Plain text — show ONCE

    @classmethod
    def verify_login_code(cls, user, code):
        """
        Verify TOTP code OR backup code during login.
        Returns True/False.
        """
        try:
            twofa = user.two_factor
        except TwoFactorAuth.DoesNotExist:
            return False

        if not twofa.is_enabled:
            return False

        # 1. Try TOTP first (most common)
        if cls._verify_totp(twofa.secret, code):
            twofa.last_used_at = timezone.now()
            twofa.save(update_fields=["last_used_at"])
            return True

        # 2. Try backup code
        return cls._verify_backup_code(user, code)

    @classmethod
    def disable(cls, user, password):
        """
        Disable 2FA — requires re-entering password for safety.
        """
        if not user.check_password(password):
            raise ValidationError("Incorrect password.")

        try:
            twofa = user.two_factor
        except TwoFactorAuth.DoesNotExist:
            raise ValidationError("2FA is not enabled.")

        twofa.delete()

        # Invalidate all backup codes
        BackupCode.objects.filter(user=user).delete()

        user.is_2fa_enabled = False
        user.save(update_fields=["is_2fa_enabled"])

    @classmethod
    def regenerate_backup_codes(cls, user):
        """Throw away old backup codes, generate new set."""
        if not user.is_2fa_enabled:
            raise ValidationError("2FA is not enabled.")
        return cls._generate_backup_codes(user)

    # ─── Private helpers ─────────────────────────────────

    @staticmethod
    def _generate_qr_base64(uri):
        """Generate QR code PNG and return as base64 string."""
        qr = qrcode.QRCode(
            version=1,
            error_correction=qrcode.constants.ERROR_CORRECT_M,
            box_size=10,
            border=4,
        )
        qr.add_data(uri)
        qr.make(fit=True)

        img = qr.make_image(fill_color="black", back_color="white")
        buffer = BytesIO()
        img.save(buffer, format="PNG")
        return base64.b64encode(buffer.getvalue()).decode("ascii")

    @staticmethod
    def _verify_totp(secret, code):
        """Verify TOTP code with time drift tolerance."""
        if not code or not code.isdigit() or len(code) != 6:
            return False
        totp = pyotp.TOTP(secret)
        return totp.verify(
            code,
            valid_window=TwoFactorAuthService.TOTP_VALID_WINDOW,
        )

    @classmethod
    def _generate_backup_codes(cls, user):
        """Generate 10 new backup codes. Invalidates old ones."""
        # Delete existing
        BackupCode.objects.filter(user=user).delete()

        # Generate new
        plain_codes = []
        bulk_records = []
        for _ in range(cls.BACKUP_CODE_COUNT):
            code = py_secrets.token_hex(cls.BACKUP_CODE_LENGTH // 2)
            plain_codes.append(code)
            bulk_records.append(
                BackupCode(
                    user=user,
                    code_hash=BackupCode.hash_code(code),
                )
            )

        BackupCode.objects.bulk_create(bulk_records)
        return plain_codes

    @staticmethod
    def _verify_backup_code(user, code):
        """Verify and consume a backup code (single-use)."""
        if not code:
            return False

        code_hash = BackupCode.hash_code(code.lower().strip())
        try:
            backup = BackupCode.objects.get(
                user=user,
                code_hash=code_hash,
                is_used=False,
            )
        except BackupCode.DoesNotExist:
            return False

        backup.mark_used()
        return True


class PendingAuthService:
    """
    Manages short-lived pending tokens for 2FA two-step login.
    Stateless — uses Django's signing module.
    """

    SALT = "pending_2fa_login"
    MAX_AGE_SECONDS = 300  # 5 minutes

    @classmethod
    def create_token(cls, user):
        """Generate a signed token containing user_id."""
        signer = TimestampSigner(salt=cls.SALT)
        return signer.sign(str(user.id))

    @classmethod
    def verify_token(cls, token):
        """Verify and return user. Raises on invalid/expired."""
        signer = TimestampSigner(salt=cls.SALT)
        try:
            user_id = signer.unsign(token, max_age=cls.MAX_AGE_SECONDS)
        except SignatureExpired:
            raise AuthenticationFailed("Login session expired. Please login again.")
        except BadSignature:
            raise AuthenticationFailed("Invalid login session.")

        try:
            return User.objects.get(id=user_id, is_active=True)
        except User.DoesNotExist:
            raise AuthenticationFailed("User not found.")
