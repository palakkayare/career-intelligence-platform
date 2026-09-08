"""Verify that all Phase 3 performance indexes exist in the database."""

from django.db import connection

# (table_name, [required columns in the index definition])
EXPECTED_INDEXES = [
    ("target_role_skills", ["target_role", "importance"]),
    ("skill_gap_snapshots", ["seeker", "target_role", "created_at"]),
    ("learning_resources", ["quality_score", "is_endorsed"]),
    ("resource_skills", ["skill", "resource"]),
    ("user_learnings", ["user", "status"]),
    ("salary_submissions", ["role_title", "location_city", "is_flagged"]),
    ("career_path_edges", ["from_node", "weight"]),
    ("recruiter_credits", ["recruiter"]),
    ("candidate_views", ["recruiter", "created_at"]),
    ("candidate_views", ["seeker", "created_at"]),
    ("referrals", ["referrer", "status"]),
    ("referral_rewards", ["user", "status", "expires_at"]),
]

with connection.cursor() as cursor:
    cursor.execute(
        """
        SELECT tablename, indexname, indexdef
        FROM pg_indexes
        WHERE schemaname = 'public'
        """
    )
    rows = cursor.fetchall()

# Group index definitions by table
by_table = {}
for table, index_name, index_def in rows:
    by_table.setdefault(table, []).append((index_name, index_def.lower()))

missing = []

for table, columns in EXPECTED_INDEXES:
    label = f"{table} ({', '.join(columns)})"
    candidates = by_table.get(table, [])

    if not candidates:
        print(f"  [NO TABLE] {label}")
        missing.append(label)
        continue

    # An index matches if every required column appears in its definition
    match = None
    for index_name, index_def in candidates:
        if all(col.lower() in index_def for col in columns):
            match = index_name
            break

    if match:
        print(f"  [OK      ] {label}  ->  {match}")
    else:
        print(f"  [MISSING ] {label}")
        missing.append(label)

print("\n" + "-" * 60)
print(f"Missing indexes: {len(missing)} of {len(EXPECTED_INDEXES)}")
for label in missing:
    print(f"  - {label}")