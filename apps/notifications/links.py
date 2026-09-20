"""
In-app paths the backend hands to people: notification deep links, and the
same links inside emails (prefixed with FRONTEND_URL).

Every path here must be a route the React app actually renders. When a
frontend route changes, change it here - one place - and the test in
test_links.py pins the full list so a drift shows up in review.

Paths are written without a trailing slash, as the frontend declares them.
"""


def seeker_application(application_id):
    return f"/me/applications/{application_id}"


def seeker_applications():
    return "/me/applications"


def recruiter_job_applications(job_public_id):
    return f"/recruiter/jobs/{job_public_id}/applications"


def recruiter_application(application_id):
    """The employer's view of one application."""
    return f"/recruiter/applications/{application_id}"


def recruiter_team():
    """Where join requests are decided."""
    return "/recruiter/team"


def recruiter_companies():
    """The list a recruiter without a company browses."""
    return "/recruiter/companies"


def recruiter_job_edit(job_public_id):
    return f"/recruiter/jobs/{job_public_id}/edit"


def job(job_public_id):
    return f"/jobs/{job_public_id}"


def invoice(transaction_id):
    return f"/billing/invoices/{transaction_id}"


def subscription():
    return "/subscription"


def pricing():
    return "/pricing"


def resume_analysis(resume_public_id):
    return f"/account/resumes/{resume_public_id}/parsed"


def job_matches():
    return "/recommendations"


def referrals():
    return "/referrals"


def who_viewed_me():
    return "/me/who-viewed"


def candidate_search():
    # There is no talent-pool screen in the web app yet; search is where a
    # recruiter finds the new members.
    return "/candidates"
