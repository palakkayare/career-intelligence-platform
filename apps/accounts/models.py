"""
Custom User model with role-based access.
"""

import hashlib
import secrets
import uuid

from django.conf import settings
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone

from apps.accounts.fields import EncryptedTextField
from apps.core.models import SoftDeleteModel


class UserManager(BaseUserManager):
    """Custom manager since we use email instead of username for login.

    Also enforces soft delete. User overrides `objects` with this manager,
    which would otherwise shadow SoftDeleteModel's SoftDeleteManager and
    leave soft-deleted users fully usable — able to log in, appear in
    search, and authenticate. Use `User.all_objects` to reach deleted rows."""

    def get_queryset(self):
        return super().get_queryset().filter(is_deleted=False)

    def _create_user(self, email, password, **extra_fields):
        """Internal helper - actual user creation logic."""
        if not email:
            raise ValueError("Email is required")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)  # Django's secure password hashing (PBKDF2)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, role="seeker", **extra_fields):
        """Regular user creation - default role is seeker."""
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, role=role, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        """Admin user creation - used by `python manage.py createsuperuser`."""
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", "admin")
        extra_fields.setdefault("is_email_verified", True)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)

    def create_oauth_user(self, email, google_sub, full_name="", picture="", role="seeker"):
        """
        Create user via OAuth (no password — provider handles auth).
        """
        if not email:
            raise ValueError("Email is required")

        email = self.normalize_email(email)
        user = self.model(
            email=email,
            role=role,
            auth_provider=self.model.AuthProvider.GOOGLE,
            google_sub=google_sub,
            full_name=full_name,
            profile_picture_url=picture,
            is_email_verified=True,  # Already verified by Google
        )
        user.set_unusable_password()  # Critical — no password set
        user.save(using=self._db)
        return user


class User(AbstractBaseUser, PermissionsMixin, SoftDeleteModel):
    """
    Custom User model.
    - Login with email (not username)
    - Three roles: seeker, recruiter, admin
    - Soft delete supported
    - Future-ready for FCM mobile push
    """

    class Role(models.TextChoices):
        SEEKER = "seeker", "Job Seeker"
        RECRUITER = "recruiter", "Recruiter"
        ADMIN = "admin", "Admin"

    class AuthProvider(models.TextChoices):
        EMAIL = "email", "Email/Password"
        GOOGLE = "google", "Google OAuth"

    # Public-facing UUID (use in URLs instead of the internal integer id)
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    # Core fields
    email = models.EmailField(unique=True, db_index=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.SEEKER)
    auth_provider = models.CharField(
        max_length=20,
        choices=AuthProvider.choices,
        default=AuthProvider.EMAIL,
    )
    google_sub = models.CharField(
        max_length=100,
        unique=True,
        null=True,
        blank=True,
        db_index=True,
        help_text="Google's unique user ID (sub claim from ID token)",
    )
    full_name = models.CharField(max_length=255, blank=True)
    profile_picture_url = models.URLField(blank=True)
    # Verification flags
    is_email_verified = models.BooleanField(default=False)
    is_2fa_enabled = models.BooleanField(default=False)  # used in Phase 2
    # Mobile-ready (populated in Phase 2)
    deactivation_reason = models.TextField(
        blank=True,
        max_length=500,
        help_text="Why the user closed their account. Optional, self-reported.",
    )
    # Mobile-ready (populated in Phase 2)
    fcm_token = models.CharField(max_length=255, null=True, blank=True)

    # Django admin requirements
    is_staff = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    # Timestamps
    date_joined = models.DateTimeField(default=timezone.now)
    last_login = models.DateTimeField(null=True, blank=True)

    objects = UserManager()

    USERNAME_FIELD = "email"  # Login field
    REQUIRED_FIELDS = []  # Other fields required when running createsuperuser

    class Meta:
        db_table = "users"
        ordering = ["-date_joined"]
        indexes = [
            models.Index(fields=["email", "is_deleted"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        return f"{self.email} ({self.role})"

    @property
    def is_seeker(self):
        return self.role == self.Role.SEEKER

    @property
    def is_recruiter(self):
        return self.role == self.Role.RECRUITER

    @property
    def is_admin_user(self):  # `is_admin` is reserved-ish in Django, so we avoid it
        return self.role == self.Role.ADMIN


class OTPCode(models.Model):
    """
    Stores OTP codes for email verification, password reset, etc.
    """

    class Purpose(models.TextChoices):
        EMAIL_VERIFICATION = "email_verify", "Email Verification"
        TWO_FA = "two_fa", "2FA Login"
        SENSITIVE_ACTION = "sensitive", "Sensitive Action"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="otp_codes",
    )
    code = models.CharField(max_length=6, db_index=True)
    purpose = models.CharField(max_length=20, choices=Purpose.choices)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "otp_codes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "purpose", "is_used"]),
        ]

    def __str__(self):
        return f"OTP for {self.user.email} ({self.purpose})"

    @classmethod
    def generate_code(cls):
        """Generate a 6-digit cryptographically secure random code."""
        # secrets module — not predictable, unlike the `random` module
        return "".join([str(secrets.randbelow(10)) for _ in range(6)])

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    @property
    def is_valid(self):
        """Check if this OTP can still be used."""
        return not self.is_used and not self.is_expired and self.attempts < self.max_attempts

    def mark_used(self):
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=["is_used", "used_at"])


class LoginHistory(models.Model):
    """
    Tracks login events for security monitoring.
    Users can see "active sessions" derived from this.
    """

    class Status(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="login_history",
        null=True,  # Failed logins may not have a matching user
        blank=True,
    )
    email_attempted = models.EmailField()  # Even failed logins capture this
    status = models.CharField(max_length=20, choices=Status.choices)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "login_history"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            # Lockout looks up recent attempts by address.
            models.Index(fields=["ip_address", "-created_at"], name="login_hist_ip_created_idx"),
        ]

    def __str__(self):
        return f"{self.email_attempted} - {self.status} - {self.created_at}"


class TwoFactorAuth(models.Model):
    """
    Stores 2FA configuration per user.
    One-to-one with User (each user has 0 or 1 2FA setup).
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="two_factor",
    )
    # Base32-encoded TOTP secret. Encrypted in the database (see fields.py);
    # plain text in Python, so the 2FA code paths are unchanged.
    secret = EncryptedTextField()
    is_enabled = models.BooleanField(default=False)

    # Tracking
    enabled_at = models.DateTimeField(null=True, blank=True)
    last_used_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "two_factor_auth"

    def __str__(self):
        return f"2FA for {self.user.email} ({'enabled' if self.is_enabled else 'pending'})"


class BackupCode(models.Model):
    """
    Single-use backup codes for 2FA recovery.
    Stored as SHA-256 hash, never plain text.
    """

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="backup_codes",
    )
    code_hash = models.CharField(max_length=64, db_index=True)
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "backup_codes"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_used"]),
        ]

    @staticmethod
    def hash_code(code):
        """SHA-256 hash for storage."""
        return hashlib.sha256(code.encode()).hexdigest()

    def mark_used(self):
        from django.utils import timezone

        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=["is_used", "used_at"])
