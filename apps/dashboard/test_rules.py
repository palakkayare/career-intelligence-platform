"""Pure rule tests - no database."""

from datetime import datetime, timedelta, timezone

from apps.dashboard import rules

NOW = datetime(2026, 9, 16, 10, 0, tzinfo=timezone.utc)
DAY = timedelta(days=1)


def app(id_, status, **extra):
    row = {
        "id": id_,
        "status": status,
        "company_name": f"Co {id_}",
        "job_title": f"Job {id_}",
        "job_public_id": f"j{id_}",
        "last_status_change_at": NOW - 10 * DAY,
        "submitted_at": NOW - 10 * DAY,
    }
    row.update(extra)
    return row


def attention(**kw):
    base = {
        "applications": [],
        "saved_jobs": [],
        "new_view_companies": [],
        "last_seen": None,
        "now": NOW,
    }
    base.update(kw)
    return rules.build_attention(**base)


def next_action(**kw):
    base = {
        "applications": [],
        "has_profile": True,
        "resume_count": 1,
        "strength": {"score": 80, "next_step": "Add your education details."},
        "matches": [],
        "learning_skill": None,
    }
    base.update(kw)
    return rules.build_next_action(**base)


# ── match_reasons ─────────────────────────────────────────────────────


def test_match_reasons_is_case_insensitive_and_keeps_job_order():
    out = rules.match_reasons(["Python", "Docker", "SQL"], ["sql", "python"])
    assert out == {"matched_skills": ["Python", "SQL"], "missing_skills": ["Docker"]}


# ── attention ─────────────────────────────────────────────────────────


def test_attention_is_empty_when_nothing_needs_the_seeker():
    assert attention(applications=[app(1, "submitted")]) == []


def test_offer_comes_before_interview():
    items = attention(applications=[app(1, "interview"), app(2, "offered")])
    assert [i["id"] for i in items] == ["offer-2", "interview-1"]


def test_status_changes_only_after_last_seen():
    items = attention(
        applications=[
            app(1, "shortlisted", last_status_change_at=NOW - DAY),
            app(2, "reviewing", last_status_change_at=NOW - 10 * DAY),
        ],
        last_seen=NOW - 3 * DAY,
    )
    assert [i["id"] for i in items] == ["status-1"]


def test_first_visit_reports_no_changes_or_views():
    items = attention(
        applications=[app(1, "shortlisted", last_status_change_at=NOW - DAY)],
        new_view_companies=["Cloudify"],
        last_seen=None,
    )
    assert items == []


def test_views_are_one_aggregated_item():
    one = attention(new_view_companies=["Cloudify"], last_seen=NOW - DAY)
    many = attention(new_view_companies=["A", "B", "C"], last_seen=NOW - DAY)
    assert one[0]["text"] == "A recruiter from Cloudify viewed your profile"
    assert many[0]["text"] == "3 recruiter views on your profile"


def test_deadline_warning_rounds_up_and_skips_applied_jobs():
    saved = [
        {"job_public_id": "s1", "title": "Soon", "application_deadline": NOW + timedelta(hours=30)},
        {"job_public_id": "s2", "title": "Later", "application_deadline": NOW + 5 * DAY},
        {"job_public_id": "j1", "title": "Applied", "application_deadline": NOW + DAY},
        {"job_public_id": "s3", "title": "Past", "application_deadline": NOW - DAY},
    ]
    items = attention(applications=[app(1, "submitted")], saved_jobs=saved)
    assert [i["id"] for i in items] == ["deadline-s1"]
    assert items[0]["text"] == "Soon closes in 2 days"


def test_withdrawn_application_does_not_hide_a_deadline():
    saved = [{"job_public_id": "j1", "title": "Again", "application_deadline": NOW + DAY}]
    items = attention(applications=[app(1, "withdrawn")], saved_jobs=saved)
    assert [i["kind"] for i in items] == ["deadline"]


def test_attention_is_capped():
    items = attention(applications=[app(i, "interview") for i in range(1, 10)])
    assert len(items) == rules.ATTENTION_LIMIT


# ── next action ───────────────────────────────────────────────────────


def test_offer_beats_everything():
    a = next_action(applications=[app(1, "offered")], resume_count=0, strength={"score": 10})
    assert a["id"] == "offer"
    assert a["link"] == "/me/applications/1"


def test_resume_comes_first_when_missing():
    assert next_action(resume_count=0)["id"] == "resume"


def test_thin_profile_uses_the_backend_next_step():
    a = next_action(strength={"score": 40, "next_step": "Add more skills."})
    assert (a["id"], a["title"], a["progress"]) == ("profile", "Add more skills.", 40)


def test_best_unapplied_strong_match_is_offered_as_apply():
    a = next_action(
        applications=[app(1, "submitted")],
        matches=[
            {"job_public_id": "j1", "title": "Taken", "company_name": "X", "score": 95},
            {"job_public_id": "j9", "title": "Open", "company_name": "Y", "score": 88},
        ],
    )
    assert (a["id"], a["action"], a["job_id"], a["job_title"]) == ("apply", "apply", "j9", "Open")


def test_weak_or_unscored_matches_are_not_pushed():
    a = next_action(
        matches=[
            {"job_public_id": "j9", "title": "Weak", "company_name": "Y", "score": 55},
            {"job_public_id": "j8", "title": "Free tier", "company_name": "Z", "score": None},
        ]
    )
    assert a["id"] == "first_application"


def test_withdrawn_only_still_counts_as_no_applications():
    assert next_action(applications=[app(1, "withdrawn")])["id"] == "first_application"


def test_complete_profile_skips_polish_and_falls_to_learning_then_browse():
    done = {"score": 100, "next_step": "Profile complete! 🎉"}
    applied = [app(1, "submitted")]
    assert (
        next_action(applications=applied, strength=done, learning_skill="Docker")["id"] == "learn"
    )
    assert next_action(applications=applied, strength=done)["id"] == "browse"


def test_every_action_has_the_same_shape():
    keys = {"id", "title", "detail", "cta", "link", "action", "job_id", "job_title", "progress"}
    assert set(next_action().keys()) == keys


# ── small helpers ─────────────────────────────────────────────────────


def test_quota_is_none_for_unlimited_plans():
    assert rules.quota_from(None, 7) is None
    assert rules.quota_from(5, 7) == {"used": 7, "limit": 5, "remaining": 0, "window_days": 30}


def test_new_user_definition():
    assert rules.is_new_user(total_applications=0, strength_score=30)
    assert not rules.is_new_user(total_applications=1, strength_score=30)
    assert not rules.is_new_user(total_applications=0, strength_score=60)


def test_an_offer_asks_to_be_answered():
    """
    Regression: the copy predated the accept/decline flow and told people the
    employer would contact them. It is their move now, and the dashboard is
    where they find that out.
    """
    result = next_action(applications=[app(7, "offered", company_name="Nimbus Systems")])

    assert "Nimbus Systems" in result["title"]
    assert result["cta"] == "Answer offer"
    assert "contact you" not in result["detail"].lower()
    assert result["link"] == "/me/applications/7"


def test_the_attention_list_offers_the_same_move():
    items = attention(applications=[app(7, "offered")])

    offers = [i for i in items if i["kind"] == "offer"]
    assert offers and offers[0]["cta"] == "Answer offer"
