"""Create test users and data needed for the Phase 3 end-to-end test run."""

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.career_intel.models import SalarySubmission

User = get_user_model()

PASSWORD = "Test123!@#"

# Flags that may need to be forced on so the test accounts can log in
VERIFICATION_FLAGS = ["is_email_verified", "email_verified", "is_verified"]


def force_verified(user):
    """Mark the account as verified, whichever flag this project uses."""
    updated = []
    for flag in VERIFICATION_FLAGS:
        if hasattr(user, flag) and not getattr(user, flag):
            setattr(user, flag, True)
            updated.append(flag)
    if updated:
        user.save(update_fields=updated)
    return updated


def make_user(email, role):
    user, created = User.objects.get_or_create(
        email=email,
        defaults={"role": role, "is_active": True},
    )
    if created:
        user.set_password(PASSWORD)
        user.is_active = True
        user.save()
    flags = force_verified(user)
    status = "created" if created else "already existed"
    print(f"{role:<10} {email:<28} ({status}) verified_flags={flags or 'none needed'}")
    return user


# --- Test accounts -------------------------------------------------------

pro_user = make_user("pro.tester@test.com", "seeker")
recruiter_user = make_user("biz.recruiter@test.com", "recruiter")

# --- Salary submissions to satisfy the K-anonymity threshold -------------

SALARY_VALUES = [1_800_000, 2_100_000, 2_400_000, 2_600_000, 3_000_000, 3_400_000]

created_count = 0
for index, amount in enumerate(SALARY_VALUES):
    filler = make_user(f"salary.filler{index}@test.com", "seeker")

    _, submission_created = SalarySubmission.objects.get_or_create(
        user=filler,
        role_title="Senior Backend Developer",
        location_city="Bangalore",
        experience_years_bucket="5-10",
        defaults={
            "company_size_bucket": "medium",
            "employment_type": "full_time",
            "work_arrangement": "hybrid",
            "salary_inr": amount,
            "effective_year": timezone.now().year,
        },
    )
    created_count += int(submission_created)

total = SalarySubmission.objects.filter(
    role_title="Senior Backend Developer",
    location_city="Bangalore",
    experience_years_bucket="5-10",
    is_flagged=False,
).count()

print("\n" + "-" * 60)
print(f"Salary submissions added this run: {created_count}")
print(f"Total matching submissions: {total} (need 5+ for K-anonymity)")
