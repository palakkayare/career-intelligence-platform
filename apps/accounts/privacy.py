"""
Data portability and account closure.

Two rights that belong together: a person should be able to take their data
with them before they close the account, so the export runs independently of
deactivation and can be requested at any time.
"""
import logging

from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

logger = logging.getLogger(__name__)


def _values(queryset, *fields):
    return list(queryset.values(*fields))


class DataExportService:
    """
    Assemble everything the platform holds about one user.

    Two things are deliberately left out. Security material - password hash,
    TOTP secret, OTP and backup-code hashes - because handing it back in a
    downloadable file creates risk without giving the user anything they can
    use. And other people's private assessments, notably a recruiter's notes
    on an application, which belong to the recruiter's own record.
    """

    @classmethod
    def build(cls, user):
        data = {
            'export_metadata': {
                'generated_at': timezone.now().isoformat(),
                'user_id': str(user.public_id),
                'format_version': '1.0',
                'excluded': [
                    'authentication secrets (password, 2FA, OTP, backup codes)',
                    'private recruiter notes on applications',
                ],
            },
            'account': cls._account(user),
            'security_activity': cls._security(user),
            'notifications': cls._notifications(user),
            'referrals': cls._referrals(user),
        }

        if user.is_seeker:
            data['seeker'] = cls._seeker(user)
        if user.is_recruiter:
            data['recruiter'] = cls._recruiter(user)
        if user.subscriptions.exists() or user.payment_transactions.exists():
            data['billing'] = cls._billing(user)

        return data

    # -- sections ---------------------------------------------------------

    @staticmethod
    def _account(user):
        return {
            'email': user.email,
            'full_name': user.full_name,
            'role': user.role,
            'auth_provider': user.auth_provider,
            'is_email_verified': user.is_email_verified,
            'date_joined': user.date_joined.isoformat() if user.date_joined else None,
            'last_login': user.last_login.isoformat() if user.last_login else None,
        }

    @staticmethod
    def _security(user):
        from .models import LoginHistory

        return {
            'two_factor_enabled': hasattr(user, 'two_factor') and user.two_factor.is_enabled,
            'login_history': _values(
                LoginHistory.objects.filter(user=user).order_by('-created_at')[:200],
                'created_at', 'status', 'ip_address', 'user_agent',
            ),
        }

    @staticmethod
    def _notifications(user):
        from apps.notifications.models import Notification, NotificationPreferences

        prefs = NotificationPreferences.objects.filter(user=user).first()
        return {
            'preferences': (
                {f.name: getattr(prefs, f.name)
                 for f in prefs._meta.fields if f.name not in ('id', 'user')}
                if prefs else None
            ),
            'history': _values(
                Notification.objects.filter(user=user).order_by('-created_at')[:500],
                'created_at', 'kind', 'title', 'message', 'is_read',
            ),
        }

    @staticmethod
    def _referrals(user):
        from apps.referrals.models import Referral, ReferralCode, ReferralReward

        code = ReferralCode.objects.filter(user=user).first()
        return {
            'my_code': code.code if code else None,
            'referrals_made': Referral.objects.filter(referrer=user).count(),
            'rewards': _values(
                ReferralReward.objects.filter(user=user),
                'kind', 'value', 'status', 'granted_at',
                'used_at', 'expires_at',
            ),
        }

    @classmethod
    def _seeker(cls, user):
        from apps.applications.models import Application
        from apps.career_intel.models import SalarySubmission, UserLearning
        from apps.jobs.models import SavedSearch, SearchHistory
        from apps.resumes.models import Resume

        profile = getattr(user, 'seeker_profile', None)
        if profile is None:
            return None

        return {
            'profile': {
                f.name: str(getattr(profile, f.name))
                for f in profile._meta.fields
                if f.name not in ('id', 'user', 'public_id')
            },
            'skills': [
                {'skill': s.skill.name, 'proficiency': s.proficiency,
                 'years_of_experience': s.years_of_experience}
                for s in profile.seeker_skills.select_related('skill')
            ],
            'work_experience': _values(
                profile.experiences.all(),
                'company_name', 'job_title', 'employment_type', 'location',
                'start_date', 'end_date', 'is_current', 'description',
            ),
            'education': _values(
                profile.educations.all(),
                'institution_name', 'degree', 'field_of_study',
                'start_year', 'end_year', 'grade', 'description',
            ),
            'resumes': _values(
                Resume.all_objects.filter(user=user),
                'name', 'original_filename', 'created_at',
                'is_primary', 'status', 'ats_score',
            ),
            # all_objects: withdrawn applications are part of the person's
            # own history and belong in their export.
            'applications': [
                {
                    'job_title': a.job.title,
                    'company': a.job.company.name,
                    'status': a.status,
                    'submitted_at': a.submitted_at.isoformat(),
                    'cover_letter': a.cover_letter,
                    'withdrawn': a.is_deleted,
                }
                for a in Application.all_objects.filter(seeker=profile)
                .select_related('job', 'job__company')
            ],
            'saved_searches': _values(
                SavedSearch.objects.filter(user=user),
                'name', 'query_text', 'filters', 'created_at',
                'notify_new_matches',
            ),
            'search_history': _values(
                SearchHistory.objects.filter(user=user).order_by('-created_at')[:100],
                'query_text', 'filters', 'result_count', 'created_at',
            ),
            'learning': _values(
                UserLearning.objects.filter(user=user),
                'status', 'progress_pct', 'started_at', 'completed_at',
                'user_rating', 'notes',
            ),
            'salary_submissions': _values(
                SalarySubmission.objects.filter(user=user),
                'submitted_at', 'role_title', 'location_city',
                'experience_years_bucket', 'salary_inr', 'bonus_inr',
            ),
        }

    @staticmethod
    def _recruiter(user):
        from apps.jobs.models import Job

        profile = getattr(user, 'recruiter_profile', None)
        if profile is None:
            return None

        return {
            'profile': {
                'full_name': profile.full_name,
                'position': profile.position,
                'bio': profile.bio,
                'phone': profile.phone,
                'linkedin_url': profile.linkedin_url,
                'contact_visibility': profile.contact_visibility,
                'company': profile.company.name if profile.company_id else None,
                'is_company_admin': profile.is_company_admin,
            },
            'jobs_posted': _values(
                Job.all_objects.filter(posted_by=profile),
                'title', 'status', 'created_at', 'application_count',
            ),
        }

    @staticmethod
    def _billing(user):
        from apps.payments.models import PaymentTransaction, Subscription

        return {
            'subscriptions': _values(
                Subscription.objects.filter(user=user),
                'created_at', 'status', 'current_period_start',
                'current_period_end', 'cancelled_at',
            ),
            'transactions': _values(
                PaymentTransaction.objects.filter(user=user),
                'created_at', 'amount_inr', 'status', 'razorpay_order_id',
            ),
        }


class AccountDeactivationService:
    """
    Close an account.

    Soft delete, not a row deletion. Payment and application records are
    referenced by other parties and legally have to survive; what stops is the
    person's presence on the platform - they cannot log in, cannot be found,
    and stop being billed.
    """

    @classmethod
    @transaction.atomic
    def deactivate(cls, user, password=None, reason=''):
        if user.is_deleted:
            raise ValidationError({'detail': 'This account is already closed.'})

        cls._verify_identity(user, password)

        summary = {
            'applications_withdrawn': cls._withdraw_applications(user),
            'subscription_cancelled': cls._stop_billing(user),
            'sessions_revoked': cls._revoke_sessions(user),
        }

        cls._hide_profile(user)

        user.deactivation_reason = (reason or '')[:500]
        user.save(update_fields=['deactivation_reason'])
        user.soft_delete()

        logger.info('Account %s deactivated. %s', user.public_id, summary)
        return summary

    # -- steps ------------------------------------------------------------

    @staticmethod
    def _verify_identity(user, password):
        """
        Password confirmation, because closing an account is destructive and a
        hijacked session should not be able to do it. OAuth users have no
        usable password, so there is nothing to check.
        """
        if not user.has_usable_password():
            return
        if not password:
            raise ValidationError(
                {'password': 'Confirm your password to close the account.'}
            )
        if not user.check_password(password):
            raise ValidationError({'password': 'Incorrect password.'})

    @staticmethod
    def _withdraw_applications(user):
        """
        Pull back anything still in flight, so recruiters are not left
        reviewing candidates who have gone.
        """
        if not user.is_seeker:
            return 0

        from apps.applications.models import Application
        from apps.applications.services import ApplicationStatusService

        profile = getattr(user, 'seeker_profile', None)
        if profile is None:
            return 0

        live = Application.objects.filter(seeker=profile).exclude(
            status__in=[
                Application.Status.REJECTED,
                Application.Status.OFFERED,
                Application.Status.WITHDRAWN,
            ]
        )
        count = 0
        for application in live:
            try:
                ApplicationStatusService.update_status(
                    application, Application.Status.WITHDRAWN, actor=user,
                    notes='Account closed by user',
                )
                count += 1
            except Exception:
                logger.exception(
                    'Could not withdraw application %s during deactivation',
                    application.id,
                )
        return count

    @staticmethod
    def _stop_billing(user):
        """Turn off auto-renew. No refund - that is a separate admin decision."""
        from apps.payments.models import Subscription

        subscription = Subscription.objects.filter(
            user=user,
            status__in=[Subscription.Status.ACTIVE, Subscription.Status.TRIALING],
        ).first()
        if subscription is None:
            return False

        subscription.auto_renew = False
        subscription.cancelled_at = timezone.now()
        subscription.cancellation_reason = 'Account closed by user'
        subscription.save(update_fields=[
            'auto_renew', 'cancelled_at', 'cancellation_reason',
        ])
        return True

    @staticmethod
    def _revoke_sessions(user):
        """Blacklist outstanding refresh tokens so every device is logged out."""
        try:
            from rest_framework_simplejwt.token_blacklist.models import (
                BlacklistedToken, OutstandingToken,
            )
        except ImportError:
            return 0

        count = 0
        for token in OutstandingToken.objects.filter(user=user):
            _, created = BlacklistedToken.objects.get_or_create(token=token)
            if created:
                count += 1
        return count

    @staticmethod
    def _hide_profile(user):
        """
        Belt and braces. The soft delete alone hides the account, but leaving
        the discovery flags on would expose the profile again the moment
        anyone restores it.
        """
        from apps.seekers.models import SeekerProfile

        profile = getattr(user, 'seeker_profile', None)
        if profile is None:
            return

        profile.is_open_to_opportunities = False
        profile.visibility = SeekerProfile.Visibility.PRIVATE
        profile.save(update_fields=['is_open_to_opportunities', 'visibility'])