import uuid
from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.models import TimestampedModel


class Plan(TimestampedModel):
    """
    Available subscription plans.
    Seeded via management command.
    """

    class Tier(models.TextChoices):
        FREE = "free", "Free"
        PRO = "pro", "Pro (Seeker)"
        BUSINESS = "business", "Business (Recruiter)"

    class BillingPeriod(models.TextChoices):
        MONTHLY = "monthly", "Monthly"
        YEARLY = "yearly", "Yearly"

    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    tier = models.CharField(max_length=20, choices=Tier.choices)
    billing_period = models.CharField(
        max_length=20,
        choices=BillingPeriod.choices,
        null=True,
        blank=True,
    )
    price_inr = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("0"))

    # Display features (for plan listing UI)
    features = models.JSONField(default=list, blank=True)

    # Razorpay-side reference (set after first plan creation in Razorpay dashboard)
    razorpay_plan_id = models.CharField(max_length=100, blank=True)

    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveSmallIntegerField(default=100)

    # ─── Quotas (null = unlimited) ───
    max_applications_per_month = models.IntegerField(
        null=True,
        blank=True,
        help_text="Null means unlimited",
    )
    max_active_jobs = models.IntegerField(
        null=True,
        blank=True,
        help_text="Max jobs a recruiter can have open at once. Null means unlimited",
    )
    max_applicants_view_per_job = models.IntegerField(
        null=True,
        blank=True,
        help_text="How many applicants a recruiter can see per job. Null means unlimited",
    )
    max_resumes = models.IntegerField(null=True, blank=True)
    max_team_members = models.IntegerField(null=True, blank=True)
    max_saved_searches = models.IntegerField(null=True, blank=True)

    # ─── Feature flags ───
    has_match_score = models.BooleanField(default=False)
    has_skill_gap = models.BooleanField(default=False)
    has_career_path = models.BooleanField(default=False)
    has_candidate_search = models.BooleanField(default=False)
    has_priority_search_visibility = models.BooleanField(default=False)
    has_advanced_filters = models.BooleanField(default=False)
    has_company_branding = models.BooleanField(default=False)
    has_analytics_dashboard = models.BooleanField(default=False)
    has_resume_ai_analysis = models.BooleanField(default=False)
    has_salary_insights = models.BooleanField(default=False)

    class Meta:
        db_table = "plans"
        ordering = ["sort_order", "price_inr"]

    def __str__(self):
        period = f" ({self.billing_period})" if self.billing_period else ""
        return f"{self.name}{period} - ₹{self.price_inr}"

    @property
    def period_days(self):
        """How many days this plan grants."""
        if self.billing_period == self.BillingPeriod.MONTHLY:
            return 30
        if self.billing_period == self.BillingPeriod.YEARLY:
            return 365
        return 0  # Free tier

    @property
    def is_paid(self):
        return self.tier != self.Tier.FREE


class Subscription(TimestampedModel):
    """
    A user's subscription. Lifecycle: TRIALING → ACTIVE → CANCELLED/EXPIRED
    """

    class Status(models.TextChoices):
        TRIALING = "trialing", "Trialing"  # Free trial in progress
        ACTIVE = "active", "Active"  # Paid + within period
        CANCELLED = "cancelled", "Cancelled"  # User cancelled, may still have access
        EXPIRED = "expired", "Expired"  # Period ended, no renewal
        PAYMENT_FAILED = "payment_failed", "Payment Failed"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="subscriptions",
    )
    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.TRIALING,
        db_index=True,
    )

    # Time windows
    trial_starts_at = models.DateTimeField(null=True, blank=True)
    trial_ends_at = models.DateTimeField(null=True, blank=True)
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True, db_index=True)

    # Cancellation
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.TextField(blank=True)

    # Will be used in Step 14 for recurring
    auto_renew = models.BooleanField(default=False)
    razorpay_subscription_id = models.CharField(max_length=100, blank=True)

    class Meta:
        db_table = "subscriptions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "status"]),
            models.Index(fields=["status", "current_period_end"]),
        ]

    def __str__(self):
        return f"{self.user.email} - {self.plan.name} [{self.status}]"

    def is_currently_active(self):
        """Check if user has active access RIGHT NOW."""
        now = timezone.now()
        if self.status == self.Status.TRIALING:
            return self.trial_ends_at and now < self.trial_ends_at
        if self.status in (self.Status.ACTIVE, self.Status.CANCELLED):
            # Even cancelled gives access until period end
            return self.current_period_end and now < self.current_period_end
        return False

    def days_remaining(self):
        """How many days of access left."""
        end = self.trial_ends_at if self.status == self.Status.TRIALING else self.current_period_end
        if not end:
            return 0
        delta = end - timezone.now()
        return max(0, delta.days)


class PaymentTransaction(TimestampedModel):
    """Audit log of all payment attempts."""

    class Status(models.TextChoices):
        CREATED = "created", "Order Created"
        SUCCESS = "success", "Payment Successful"
        FAILED = "failed", "Payment Failed"
        REFUNDED = "refunded", "Refunded"

    subscription = models.ForeignKey(
        Subscription,
        on_delete=models.PROTECT,
        related_name="transactions",
        null=True,
        blank=True,  # Failed orders may not have sub
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="payment_transactions",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
        related_name="+",  # Don't need reverse
    )
    amount_inr = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.CREATED)

    # Razorpay references
    razorpay_order_id = models.CharField(max_length=100, db_index=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    razorpay_signature = models.CharField(max_length=512, blank=True)

    # Diagnostics
    failure_reason = models.TextField(blank=True)

    class Meta:
        db_table = "payment_transactions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "-created_at"]),
            models.Index(fields=["razorpay_payment_id"]),
        ]

    def __str__(self):
        return f"₹{self.amount_inr} [{self.status}] - {self.razorpay_order_id}"


class Refund(TimestampedModel):
    """
    An admin-issued refund against a successful payment.

    Kept as its own model rather than a few columns on PaymentTransaction so
    that partial and repeated refunds are both possible, and so the record of
    who authorised each one, and why, survives independently.
    """

    class Status(models.TextChoices):
        PENDING = "pending", "Pending at gateway"
        PROCESSED = "processed", "Processed"
        FAILED = "failed", "Failed"

    transaction = models.ForeignKey(
        PaymentTransaction,
        on_delete=models.PROTECT,
        related_name="refunds",
    )
    amount_inr = models.DecimalField(max_digits=10, decimal_places=2)
    reason = models.TextField(
        max_length=500,
        help_text="Why this refund was issued. Required for accountability.",
    )
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="refunds_issued",
        help_text="Admin who authorised the refund. Null for system refunds.",
    )
    access_revoked = models.BooleanField(
        default=False,
        help_text="Whether the paid subscription was ended alongside this refund.",
    )

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    razorpay_refund_id = models.CharField(max_length=100, blank=True, db_index=True)
    failure_reason = models.TextField(blank=True)

    class Meta:
        db_table = "refunds"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["transaction", "-created_at"]),
            models.Index(fields=["status", "-created_at"]),
        ]

    def __str__(self):
        return (
            f"Refund Rs.{self.amount_inr} [{self.status}] - {self.razorpay_refund_id or 'pending'}"
        )


class WebhookEvent(TimestampedModel):
    """
    Records every Razorpay webhook for idempotency and audit.
    """

    class ProcessingStatus(models.TextChoices):
        RECEIVED = "received", "Received"
        PROCESSED = "processed", "Processed Successfully"
        FAILED = "failed", "Processing Failed"
        SKIPPED = "skipped", "Skipped (Duplicate)"

    # Razorpay's unique event ID — used for idempotency
    razorpay_event_id = models.CharField(
        max_length=100,
        unique=True,
        db_index=True,
    )
    event_type = models.CharField(max_length=100, db_index=True)

    # Full raw event payload
    payload = models.JSONField()
    signature = models.CharField(max_length=512)

    # Processing
    processing_status = models.CharField(
        max_length=20,
        choices=ProcessingStatus.choices,
        default=ProcessingStatus.RECEIVED,
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    retry_count = models.PositiveSmallIntegerField(default=0)

    received_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        db_table = "webhook_events"
        ordering = ["-received_at"]
        indexes = [
            models.Index(fields=["event_type", "processing_status"]),
            models.Index(fields=["-received_at"]),
        ]

    def __str__(self):
        return f"{self.event_type} [{self.processing_status}] - {self.razorpay_event_id}"
