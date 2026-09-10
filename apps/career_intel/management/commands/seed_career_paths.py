"""
apps/career_intel/management/commands/seed_career_paths.py

Seed the curated career graph: nodes (roles) and edges (transitions).

Run with:
    python manage.py seed_career_paths

The command is idempotent -- it uses update_or_create, so running it twice
refreshes the data instead of duplicating it.
"""

from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.career_intel.models import CareerPathEdge, CareerPathNode, TargetRole
from apps.skills.models import Skill

# ─────────────────────────────────────────────────────────────────────────────
# Nodes
# ─────────────────────────────────────────────────────────────────────────────
# avg_salary_inr values are rough Indian market annual base figures, used only
# for display. Adjust them freely -- nothing in the path-finding depends on them.

NODES = [
    # --- Backend / leadership track ---
    {
        "slug": "junior-backend-dev",
        "name": "Junior Backend Developer",
        "level": 2,
        "category": "engineering",
        "typical_experience_years": 1,
        "avg_salary_inr": Decimal("800000.00"),
    },
    {
        "slug": "backend-dev",
        "name": "Backend Developer",
        "level": 3,
        "category": "engineering",
        "typical_experience_years": 3,
        "avg_salary_inr": Decimal("1500000.00"),
    },
    {
        "slug": "senior-backend-dev",
        "name": "Senior Backend Developer",
        "level": 4,
        "category": "engineering",
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2800000.00"),
    },
    {
        "slug": "tech-lead",
        "name": "Tech Lead",
        "level": 5,
        "category": "engineering",
        "typical_experience_years": 8,
        "avg_salary_inr": Decimal("4000000.00"),
    },
    {
        "slug": "engineering-manager",
        "name": "Engineering Manager",
        "level": 5,
        "category": "engineering",
        "typical_experience_years": 8,
        "avg_salary_inr": Decimal("4500000.00"),
    },
    {
        "slug": "principal-engineer",
        "name": "Principal Engineer",
        "level": 5,
        "category": "engineering",
        "typical_experience_years": 10,
        "avg_salary_inr": Decimal("5500000.00"),
    },
    {
        "slug": "engineering-director",
        "name": "Engineering Director",
        "level": 6,
        "category": "engineering",
        "typical_experience_years": 12,
        "avg_salary_inr": Decimal("7000000.00"),
    },
    {
        "slug": "cto",
        "name": "CTO",
        "level": 6,
        "category": "engineering",
        "typical_experience_years": 15,
        "avg_salary_inr": Decimal("10000000.00"),
    },
    # --- Frontend track ---
    {
        "slug": "junior-frontend-dev",
        "name": "Junior Frontend Developer",
        "level": 2,
        "category": "engineering",
        "typical_experience_years": 1,
        "avg_salary_inr": Decimal("750000.00"),
    },
    {
        "slug": "frontend-dev",
        "name": "Frontend Developer",
        "level": 3,
        "category": "engineering",
        "typical_experience_years": 3,
        "avg_salary_inr": Decimal("1400000.00"),
    },
    {
        "slug": "senior-frontend-dev",
        "name": "Senior Frontend Developer",
        "level": 4,
        "category": "engineering",
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2600000.00"),
    },
    # --- Full stack ---
    {
        "slug": "full-stack-dev",
        "name": "Full Stack Developer",
        "level": 3,
        "category": "engineering",
        "typical_experience_years": 4,
        "avg_salary_inr": Decimal("1800000.00"),
    },
    # --- Data track ---
    {
        "slug": "data-analyst",
        "name": "Data Analyst",
        "level": 2,
        "category": "data",
        "typical_experience_years": 1,
        "avg_salary_inr": Decimal("700000.00"),
    },
    {
        "slug": "data-scientist",
        "name": "Data Scientist",
        "level": 3,
        "category": "data",
        "typical_experience_years": 3,
        "avg_salary_inr": Decimal("1600000.00"),
    },
    {
        "slug": "senior-data-scientist",
        "name": "Senior Data Scientist",
        "level": 4,
        "category": "data",
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2900000.00"),
    },
    # --- DevOps ---
    {
        "slug": "devops-engineer",
        "name": "DevOps Engineer",
        "level": 3,
        "category": "engineering",
        "typical_experience_years": 3,
        "avg_salary_inr": Decimal("1600000.00"),
    },
    {
        "slug": "senior-devops",
        "name": "Senior DevOps Engineer",
        "level": 4,
        "category": "engineering",
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2800000.00"),
    },
    # --- Product ---
    {
        "slug": "associate-pm",
        "name": "Associate Product Manager",
        "level": 2,
        "category": "product",
        "typical_experience_years": 1,
        "avg_salary_inr": Decimal("900000.00"),
    },
    {
        "slug": "product-manager",
        "name": "Product Manager",
        "level": 3,
        "category": "product",
        "typical_experience_years": 4,
        "avg_salary_inr": Decimal("2200000.00"),
    },
    {
        "slug": "senior-pm",
        "name": "Senior Product Manager",
        "level": 4,
        "category": "product",
        "typical_experience_years": 7,
        "avg_salary_inr": Decimal("3500000.00"),
    },
    # --- Design ---
    {
        "slug": "junior-designer",
        "name": "Junior UI/UX Designer",
        "level": 2,
        "category": "design",
        "typical_experience_years": 1,
        "avg_salary_inr": Decimal("600000.00"),
    },
    {
        "slug": "designer",
        "name": "UI/UX Designer",
        "level": 3,
        "category": "design",
        "typical_experience_years": 3,
        "avg_salary_inr": Decimal("1200000.00"),
    },
    {
        "slug": "senior-designer",
        "name": "Senior UI/UX Designer",
        "level": 4,
        "category": "design",
        "typical_experience_years": 6,
        "avg_salary_inr": Decimal("2200000.00"),
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Edges
# ─────────────────────────────────────────────────────────────────────────────
# Format: (from_slug, to_slug, weight, time_months, transition_type, rationale, skills)
#
# Weight heuristics:
#   2-3  promotion within the same track
#   3-4  lateral move
#   5-7  pivot into a different category
#   7-10 skipping levels

EDGES = [
    # --- Backend / leadership track ---
    (
        "junior-backend-dev",
        "backend-dev",
        2,
        18,
        "vertical",
        "Standard one to two year promotion with project ownership.",
        ["Django", "PostgreSQL"],
    ),
    (
        "backend-dev",
        "senior-backend-dev",
        3,
        30,
        "vertical",
        "Requires demonstrated mentorship and system design ability.",
        ["AWS", "Docker", "System Design"],
    ),
    (
        "senior-backend-dev",
        "tech-lead",
        4,
        24,
        "vertical",
        "Adds team leadership and architectural decision making.",
        ["Leadership", "Communication"],
    ),
    (
        "senior-backend-dev",
        "engineering-manager",
        5,
        30,
        "pivot",
        "Pivot into people management; needs deliberate soft skill development.",
        ["Leadership", "Communication"],
    ),
    (
        "senior-backend-dev",
        "principal-engineer",
        6,
        36,
        "vertical",
        "Deep technical specialisation with no people management.",
        ["System Design", "Architecture"],
    ),
    (
        "tech-lead",
        "engineering-manager",
        3,
        18,
        "lateral",
        "Common transition that formalises people leadership.",
        ["Leadership"],
    ),
    (
        "tech-lead",
        "principal-engineer",
        4,
        24,
        "lateral",
        "Move back to the individual contributor track from leadership.",
        ["System Design"],
    ),
    (
        "engineering-manager",
        "engineering-director",
        4,
        36,
        "vertical",
        "Larger org with multiple managers reporting in.",
        ["Leadership", "Strategy"],
    ),
    (
        "principal-engineer",
        "engineering-director",
        5,
        36,
        "pivot",
        "Pivot from deep IC work into broader leadership.",
        ["Leadership"],
    ),
    (
        "engineering-director",
        "cto",
        6,
        48,
        "vertical",
        "Executive role owning company-wide technology strategy.",
        ["Leadership", "Strategy"],
    ),
    # --- Frontend track ---
    (
        "junior-frontend-dev",
        "frontend-dev",
        2,
        18,
        "vertical",
        "Standard one to two year promotion.",
        ["React", "TypeScript"],
    ),
    (
        "frontend-dev",
        "senior-frontend-dev",
        3,
        30,
        "vertical",
        "Senior frontend work with deep UI engineering.",
        ["React", "Next.js"],
    ),
    (
        "frontend-dev",
        "full-stack-dev",
        3,
        12,
        "lateral",
        "Broaden by adding backend skills.",
        ["Python", "Django", "PostgreSQL"],
    ),
    # --- Full stack flexibility ---
    (
        "backend-dev",
        "full-stack-dev",
        3,
        12,
        "lateral",
        "Broaden by adding frontend skills.",
        ["React", "JavaScript"],
    ),
    (
        "full-stack-dev",
        "senior-backend-dev",
        3,
        24,
        "vertical",
        "Specialise into backend depth.",
        ["AWS", "System Design"],
    ),
    (
        "full-stack-dev",
        "senior-frontend-dev",
        3,
        24,
        "vertical",
        "Specialise into frontend depth.",
        ["React", "Next.js"],
    ),
    # --- Data track ---
    (
        "data-analyst",
        "data-scientist",
        4,
        24,
        "vertical",
        "Add machine learning and statistics depth.",
        ["Machine Learning", "Python"],
    ),
    (
        "data-scientist",
        "senior-data-scientist",
        3,
        30,
        "vertical",
        "Senior IC role with research depth.",
        ["Machine Learning", "Statistics"],
    ),
    (
        "backend-dev",
        "data-scientist",
        5,
        24,
        "pivot",
        "Pivot from engineering into data science; significant retraining needed.",
        ["Machine Learning", "Python", "Statistics"],
    ),
    # --- DevOps ---
    (
        "backend-dev",
        "devops-engineer",
        4,
        18,
        "pivot",
        "Pivot from application development to infrastructure.",
        ["Docker", "Kubernetes", "AWS"],
    ),
    (
        "devops-engineer",
        "senior-devops",
        3,
        30,
        "vertical",
        "Senior DevOps with platform-level ownership.",
        ["Kubernetes", "AWS", "Terraform"],
    ),
    # --- Product ---
    (
        "associate-pm",
        "product-manager",
        3,
        24,
        "vertical",
        "Standard promotion with full feature ownership.",
        ["Communication", "Problem Solving"],
    ),
    (
        "product-manager",
        "senior-pm",
        3,
        30,
        "vertical",
        "Senior PM owning an entire product area.",
        ["Leadership", "Strategy"],
    ),
    (
        "senior-backend-dev",
        "product-manager",
        6,
        18,
        "pivot",
        "Engineer to PM pivot; common inside tech companies.",
        ["Communication", "Problem Solving"],
    ),
    (
        "senior-frontend-dev",
        "product-manager",
        6,
        18,
        "pivot",
        "Engineer to PM pivot.",
        ["Communication"],
    ),
    # --- Design ---
    (
        "junior-designer",
        "designer",
        2,
        18,
        "vertical",
        "Standard one to two year promotion.",
        ["Figma"],
    ),
    (
        "designer",
        "senior-designer",
        3,
        30,
        "vertical",
        "Senior designer owning the design system.",
        ["Figma", "UI/UX Design"],
    ),
    (
        "senior-designer",
        "product-manager",
        6,
        24,
        "pivot",
        "Designer to PM; common in product-led companies.",
        ["Communication"],
    ),
]


class Command(BaseCommand):
    help = "Seed the curated career path nodes and edges"

    @transaction.atomic
    def handle(self, *args, **options):
        node_map = {}
        created_nodes = 0

        # ── Nodes ──
        for data in NODES:
            slug = data["slug"]

            # Link to a TargetRole when one with a matching slug exists.
            # TargetRole may not have a slug field in every project, so this
            # is best-effort and never fatal.
            try:
                target_role = TargetRole.objects.filter(slug=slug).first()
            except Exception:
                target_role = None

            node, was_created = CareerPathNode.objects.update_or_create(
                slug=slug,
                defaults={**data, "target_role": target_role, "is_active": True},
            )
            node_map[slug] = node
            if was_created:
                created_nodes += 1

        self.stdout.write(f"Nodes: {len(node_map)} total ({created_nodes} new)")

        # ── Edges ──
        created_edges = 0
        missing_skills = set()

        for from_slug, to_slug, weight, months, ttype, rationale, skill_names in EDGES:
            from_node = node_map.get(from_slug)
            to_node = node_map.get(to_slug)

            if not from_node or not to_node:
                self.stderr.write(f"WARNING: skipping edge, missing node {from_slug} or {to_slug}")
                continue

            edge, was_created = CareerPathEdge.objects.update_or_create(
                from_node=from_node,
                to_node=to_node,
                defaults={
                    "weight": weight,
                    "time_months": months,
                    "transition_type": ttype,
                    "rationale": rationale,
                    "is_active": True,
                },
            )

            # Re-wire the required skills from scratch each run.
            edge.required_skills.clear()
            for skill_name in skill_names:
                skill = Skill.objects.filter(name__iexact=skill_name).first()
                if skill:
                    edge.required_skills.add(skill)
                else:
                    # Not fatal: the edge still works, it just carries no skill
                    # for this name. Collected and reported at the end.
                    missing_skills.add(skill_name)

            if was_created:
                created_edges += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Edges: {created_edges} new (total {CareerPathEdge.objects.count()})"
            )
        )

        if missing_skills:
            self.stdout.write(
                self.style.WARNING(
                    "Skills not found in the Skill table (edges seeded without them): "
                    + ", ".join(sorted(missing_skills))
                )
            )
