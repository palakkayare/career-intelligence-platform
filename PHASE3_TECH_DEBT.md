# Phase 3 — Tech Debt Register (Frozen)

Frozen after the Phase 3 end-to-end integration test on 27 Aug 2026.
Items 1–25 carry over from the wrap-up document. Items 26–29 were found
during the integration test. Items marked RESOLVED were fixed during the
test run itself.

---

## Production blockers — must be fixed before launch

| # | Item | Severity |
|---|---|---|
| 5 | No automated DB backups | Critical |
| 1 | TOTP secret stored unencrypted (carryover from Phase 1) | High |
| 4 | No GDPR data export | High |

---

## Resolved during the integration test

| # | Item | Fix |
|---|---|---|
| R1 | Skill gap message read "Start with the 0 critical skill(s)" when no critical skills were missing | `_build_message` now derives the headline from the gap score and the advice from the actual missing counts |
| R2 | Candidate name mask fell back to the email handle (`p****`), leaking the first character of contact data | Falls back to `"Candidate"`; `_initials` now upper-cases the initial |

---

## Open items

### High

| # | Item | Phase |
|---|---|---|
| 1 | TOTP secret unencrypted | 4 |
| 4 | No GDPR data export | 4 |
| 5 | No automated DB backups | 4 |

### Medium

| # | Item | Phase |
|---|---|---|
| 3 | View counter writes directly to the DB on every read | 4 |
| 6 | Per-user account lockout missing | 4 |
| 7 | Razorpay Subscriptions API not used | 4 |
| 9 | Resume parsing accuracy 60–70% (spaCy) | 4 — LLM upgrade |
| 14 | Admin cannot impersonate a user | 4 |
| 15 | No webhook delivery retry queue | 4 |
| 17 | TargetRoles are curated, not ML-derived | 4 |
| 20 | Advanced ATS does not run automatically on resumes parsed before Step 26 | 4 |
| 21 | Referral discount codes are manual (no Razorpay coupon API) | 4 |
| 25 | No multi-language support anywhere | 4 |
| **26** | **Salary insights expose raw min/max, which are individual submissions** | **4** |
| **27** | **`current_title` matching against career path nodes is exact-match only** | **4** |
| **28** | **`advanced-ats` reports "analysis is still running" when no task was ever queued** | **4** |

### Low

| # | Item | Phase |
|---|---|---|
| 2 | Search history slow at scale | 4 |
| 8 | TF-IDF on job description not added — JD match uses structured skill tags only | 4 |
| 10 | No A/B testing for match weights | 4 |
| 11 | SendGrid free tier | Migrate to AWS SES |
| 12 | ngrok URL changes | Production: real domain |
| 13 | Email templates inline | 4 if needed |
| 16 | Resume parsing English-only | 4 |
| 18 | Career graph rebuilt per request (not cached) | 4 |
| 19 | Salary outlier trim is simple (no IQR) | 4 |
| 22 | No device fingerprinting for referral abuse | 4 |
| 23 | Learning resource ratings are static (no API scrape) | 4 |
| 24 | Salary insights not cached | 4 |
| **29** | **Career path seed data has no slow-but-easy transitions, so the `easiest` objective never surfaces as a distinct route** | **4** |
| **30** | **Learning recommendations return only one resource per skill** | **4** |
| **31** | **Salary suppression response leaks the exact submission count below K** | **4** |
| **32** | **Salary comparison returns a position label but not the user's percentile** | **4** |

---

## New items — detail

### 26. Salary insights expose individual submissions

`salary_range_inr` includes `min` and `max`. Both are, by definition, one
real person's exact salary. K-anonymity protects the aggregate but not the
endpoints of the range.

Fix: drop `min`/`max` from the response and keep `p10`/`p90` as the
displayed boundaries. Both are already computed.

```python
# p10/p90 are safe boundaries. Raw min/max always correspond to one real
# person's submission, so exposing them defeats the point of K-anonymity.
"salary_range_inr": {
    "p10": percentiles["p10"],
    "p25": percentiles["p25"],
    "median": percentiles["median"],
    "p75": percentiles["p75"],
    "p90": percentiles["p90"],
    "mean": mean_value,
},
```

### 27. Career path current-title matching is exact-match only

`/career-path/from-current/` matched `"Backend Developer"` because it is
character-identical to the node name. Real users will enter "Backend
Engineer", "Sr. Backend Dev", "SDE-2" — all of which will fail and return
"Set your current title in your profile first", which is misleading because
the title *is* set.

Fix options, cheapest first:
1. Add an alias list per `CareerPathNode` and match case-insensitively.
2. Let the seeker pick their node from a dropdown instead of free text.
3. Fuzzy match with a similarity threshold, then confirm with the user.

Also correct the error message so it distinguishes "no title set" from
"title set but not recognised".

### 28. Advanced ATS status message is inaccurate

`GET /resumes/<uuid>/advanced-ats/` returns "Advanced ATS analysis is still
running. Check back in a moment." even when no task was ever queued for
that resume. Resumes parsed before Step 26 have no analysis and never will
until someone calls `re-analyze-ats/`.

The user polls forever with no way of knowing the analysis will never
arrive.

Fix: distinguish the three states — queued and running, never queued, and
failed — and point the user at `re-analyze-ats/` in the second case. A
backfill management command for pre-Step-26 resumes would close this
properly.

### 29. `easiest` career path never surfaces separately

`find_paths` computes fastest, easiest, and most direct, then de-duplicates.
In the current seed data every edge's difficulty rises with its duration, so
the fastest path is always the easiest path, and the `easiest` label is
always de-duplicated away.

This is a data gap, not a code bug. Add a few transitions that are slow but
low-difficulty (long tenure, low skill delta) to exercise the objective.

Related UX nit: when three objectives collapse into one path, the label
still reads "Fastest path". "Fastest, easiest and most direct" tells the
user more.

---

## Documentation corrections

The Phase 3 wrap-up document contains three inaccuracies:

| Claim | Reality |
|---|---|
| Career path graph has 23 nodes + 30 edges | 23 nodes + **28 edges** |
| JD match endpoint is `/resumes/<uuid>/jd-match/` | It is `/applications/<id>/jd-match/` — correctly scoped to an application, since a JD match is a property of a resume *and* a job |
| Admin dashboard snippet uses `{% extends "admin/index.html" %}` in `templates/admin/index.html` | That template extends itself and recurses. Use a differently-named template plus a custom `AdminSite.each_context` |

---

## Verified working — no action needed

These were checked during the integration test and behaved correctly:

- Skill gap weighted scoring, easy-critical-first recommendation ordering
- Gap → learning recommendation flow; completed resources excluded
- Learning progress state machine (`in_progress` → `completed`, auto 100%)
- K-anonymity suppression with data present but below threshold
- Career path multi-objective search and BFS reachability
- Candidate search masking; contact absent until revealed
- Reveal credit decrement, idempotent on repeat reveals
- "Who viewed me" audit trail — one record per candidate, not per call
- Recruiter credit sync derives the limit from the plan tier
- Advanced ATS scoring (action verbs, quantification, passive voice, spelling)
- JD match scoring folded into a 100-point combined score
- Referral conversion is idempotent (`select_for_update` + PENDING filter)
- Referral conversion fires on first payment only, not on signup
- Both-side rewards; anonymized leaderboard
