"""
Connects notifications to events that happen in other apps.

Each function here is called from the relevant service layer.
Keeping them in one module means business logic never imports
notification internals directly.
"""
from .models import NotificationKind
from .service import NotificationService


def notify_application_status_change(application, old_status, new_status):
    """Called from ApplicationStatusService.update_status()"""
    seeker_user = application.seeker.user

    NotificationService.create(
        user=seeker_user,
        kind=NotificationKind.APPLICATION_STATUS_CHANGE,
        title=f'Application status updated to {new_status}',
        message=(
            f'Your application for "{application.job.title}" at '
            f'{application.job.company.name} is now {new_status}.'
        ),
        link=f'/applications/me/{application.id}',
        context={
            'job_title': application.job.title,
            'company_name': application.job.company.name,
            'old_status': old_status,
            'new_status': new_status,
            'recruiter_notes': application.recruiter_notes,
        },
    )


def notify_application_received(application):
    """Called when a seeker submits a new application — notifies the recruiter."""
    recruiter_user = application.job.posted_by.user
    seeker_name = (
        application.seeker.full_name or application.seeker.user.email
    )

    NotificationService.create(
        user=recruiter_user,
        kind=NotificationKind.APPLICATION_RECEIVED,
        title='New application received',
        message=f'{seeker_name} applied to "{application.job.title}".',
        link=f'/jobs/{application.job.public_id}/applications/',
        context={
            'job_title': application.job.title,
            'seeker_name': seeker_name,
        },
    )


def notify_payment_success(transaction):
    """Called from PaymentService.verify_and_activate()"""
    NotificationService.create(
        user=transaction.user,
        kind=NotificationKind.PAYMENT_SUCCESS,
        title=f'Payment confirmed — {transaction.plan.name}',
        message=(
            f'Your payment of Rs. {transaction.amount_inr} for '
            f'{transaction.plan.name} has been received.'
        ),
        link=f'/payments/me/{transaction.id}/invoice/',
        context={
            'plan_name': transaction.plan.name,
            'amount_inr': str(transaction.amount_inr),
            'invoice_url': f'/payments/me/{transaction.id}/invoice/',
        },
    )


def notify_payment_failed(transaction):
    """Called when a payment attempt fails."""
    NotificationService.create(
        user=transaction.user,
        kind=NotificationKind.PAYMENT_FAILED,
        title='Payment failed',
        message=(
            f'Your payment of Rs. {transaction.amount_inr} for '
            f'{transaction.plan.name} could not be processed. '
            f'Reason: {transaction.failure_reason or "Unknown"}'
        ),
        link='/subscriptions/',
        context={
            'plan_name': transaction.plan.name,
            'amount_inr': str(transaction.amount_inr),
            'failure_reason': transaction.failure_reason,
        },
    )


def notify_subscription_expiring(subscription, days_remaining):
    """Called from the check_expiring_subscriptions Celery task."""
    NotificationService.create(
        user=subscription.user,
        kind=NotificationKind.SUBSCRIPTION_EXPIRING,
        title=f'Your subscription expires in {days_remaining} days',
        message=(
            f'Your {subscription.plan.name} subscription will end on '
            f'{subscription.current_period_end.strftime("%d %b %Y")}.'
        ),
        link='/subscriptions/me/',
        context={
            'plan_name': subscription.plan.name,
            'days_remaining': days_remaining,
            'period_end': str(subscription.current_period_end),
        },
    )


def notify_job_approved(job):
    """Called from JobStatusService.approve()"""
    NotificationService.create(
        user=job.posted_by.user,
        kind=NotificationKind.JOB_APPROVED,
        title='Your job posting is now live',
        message=(
            f'Your posting "{job.title}" has been approved and is now '
            f'visible to job seekers.'
        ),
        link=f'/jobs/{job.public_id}/',
        context={'job_title': job.title},
    )


def notify_job_rejected(job, reason):
    """Called from JobStatusService.reject()"""
    NotificationService.create(
        user=job.posted_by.user,
        kind=NotificationKind.JOB_REJECTED,
        title='Job posting needs revision',
        message=f'Your posting "{job.title}" was not approved. Reason: {reason}',
        link=f'/jobs/{job.public_id}/edit/',
        context={'job_title': job.title, 'rejection_reason': reason},
    )