"""Give the Pro test account an active subscription and a starting skill set."""

from datetime import timedelta

from django.contrib.auth import get_user_model
from django.utils import timezone

from apps.payments.models import Plan, Subscription
from apps.skills.models import Skill

User = get_user_model()

user = User.objects.get(email="pro.tester@test.com")
profile = user.seeker_profile

# --- Pick a plan that unlocks the Phase 3 features -----------------------

REQUIRED_FEATURES = {
    "has_skill_gap": True,
    "has_career_path": True,
    "has_salary_insights": True,
    "has_resume_ai_analysis": True,
}

plan = Plan.objects.filter(is_active=True, **REQUIRED_FEATURES).order_by("price_inr").first()

if plan is None:
    print("No plan unlocks all Phase 3 features. Available plans:")
    for candidate in Plan.objects.all():
        flags = {name: getattr(candidate, name) for name in REQUIRED_FEATURES}
        print(f"  {candidate.slug:<20} tier={candidate.tier:<12} {flags}")
    raise SystemExit("Seed the plans first, then re-run this script.")

print(f"Using plan: {plan.slug} (tier={plan.tier}, price={plan.price_inr})")

# --- Create or refresh the subscription ----------------------------------

now = timezone.now()

subscription, created = Subscription.objects.update_or_create(
    user=user,
    defaults={
        "plan": plan,
        "status": "active",
        "current_period_start": now,
        "current_period_end": now + timedelta(days=30),
        "auto_renew": False,
        "cancelled_at": None,
    },
)
print(
    f"Subscription {'created' if created else 'updated'}: "
    f"status={subscription.status}, valid until {subscription.current_period_end:%Y-%m-%d}"
)

# --- Give the seeker a realistic starting skill set ----------------------
# Deliberately partial, so the gap analysis returns something meaningful.

STARTING_SKILLS = ["Python", "Django", "PostgreSQL", "Git", "REST API"]

matched, not_found = [], []
for name in STARTING_SKILLS:
    skill = Skill.objects.filter(name__iexact=name).first()
    if skill:
        profile.skills.add(skill)
        matched.append(skill.name)
    else:
        not_found.append(name)

print(f"\nSkills attached: {matched}")
if not_found:
    print(f"Not found in the Skill table: {not_found}")

print(f"Seeker now has {profile.skills.count()} skill(s)")