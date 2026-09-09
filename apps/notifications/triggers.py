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
            # Lets the email task attach the invoice PDF
            'transaction_id': transaction.id,
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

def notify_application_withdrawn(application):
    """
    Called from ApplicationStatusService when a seeker withdraws.

    The recruiter may have this candidate in an interview pipeline, so this
    is worth telling them promptly rather than leaving them to notice a
    silent disappearance.
    """
    recruiter_user = application.job.posted_by.user
    seeker_name = (
        application.seeker.full_name or application.seeker.user.email
    )

    NotificationService.create(
        user=recruiter_user,
        kind=NotificationKind.APPLICATION_WITHDRAWN,
        title='An application was withdrawn',
        message=(
            f'{seeker_name} withdrew their application for '
            f'"{application.job.title}".'
        ),
        link=f'/jobs/{application.job.public_id}/applications/',
        context={
            'job_title': application.job.title,
            'seeker_name': seeker_name,
        },
    )


def notify_subscription_expired(subscription):
    """
    Called from SubscriptionService.expire_ended_subscriptions().

    Separate from the expiring-soon reminder: that one is a nudge, this one
    explains why paid features stopped working.
    """
    NotificationService.create(
        user=subscription.user,
        kind=NotificationKind.SUBSCRIPTION_EXPIRED,
        title='Your subscription has expired',
        message=(
            f'Your {subscription.plan.name} subscription has ended. '
            f'Renew to get your Pro features back.'
        ),
        link='/payments/plans/',
        context={
            'plan_name': subscription.plan.name,
            'expired_on': (
                subscription.current_period_end.strftime('%d %b %Y')
                if subscription.current_period_end else ''
            ),
        },
    )


def notify_resume_analysis_complete(resume):
    """
    Called from the resume parsing task once spaCy has finished.

    Parsing is asynchronous and can take a while, so the user has usually
    navigated away by the time it lands.
    """
    NotificationService.create(
        user=resume.user,
        kind=NotificationKind.RESUME_ANALYSIS_COMPLETE,
        title='Your resume analysis is ready',
        message=(
            f'"{resume.name}" has been analysed. '
            f'ATS score: {resume.ats_score}/100.'
        ),
        link=f'/resumes/{resume.public_id}/',
        context={
            'resume_name': resume.name,
            'ats_score': resume.ats_score,
            'skills_found': resume.resume_skills.count(),
        },
    )


def notify_new_matching_jobs(seeker_user, matches):
    """
    Called from the weekly job-alert task.

    One notification for the whole batch, not one per job - a digest is the
    point. Delivery priority for this kind is DIGEST, so the daily email
    task picks it up rather than sending immediately.
    """
    if not matches:
        return None

    top = matches[0]

    return NotificationService.create(
        user=seeker_user,
        kind=NotificationKind.NEW_MATCHING_JOB,
        title=f'{len(matches)} new jobs match your profile',
        message=(
            f'Your best match is "{top["job_title"]}" at '
            f'{top["company_name"]} ({top["score"]}% fit).'
        ),
        link='/jobs/matches/',
        context={
            'match_count': len(matches),
            'matches': matches[:5],
        },
    )