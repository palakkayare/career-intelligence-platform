# Project Status

**Career Intelligence Platform - backend.** As of 12 Sep 2026.

Replaces `PHASE3_TECH_DEBT.md`. Items carried over keep their original
numbers so older notes still line up.

---

## 1. Where things stand

The backend is built, tested and deployed, and the code work that was
blocking launch is done. What remains needs a lawyer, a GSTIN, a domain or
the frontend - decisions rather than commits.

| Area | State |
|---|---|
| Backend features (Phases 1-3) | Done |
| Docker, CI, Sentry, security hardening (Phase 4) | Done |
| Production deploy on Railway + Neon | Done, smoke-tested, rollback practised |
| API documentation | `/api/docs/` (Swagger UI), generated from the code |
| Frontend | **Not started** |
| Custom domain, Cloudflare | **Not done** - needs a code change for client IPs (DEPLOY.md, 6) |
| Razorpay live mode | **Not done** - waits on legal review and GSTIN |
| Privacy policy, terms, refund policy | **Not written** - for the lawyer |
| Uptime monitoring | **Not set up** - deliberately, see DEPLOY.md, 9 |

Nothing on the "before launch" list is waiting on code.

---

## 2. Corrections to the Phase 4 wrap-up document

The Step 34 document described a plan more than the result. Where they differ:

| The document says | What was actually built |
|---|---|
| Upstash Redis | Railway Redis in the same project. Celery polls the broker constantly, which per-request pricing punishes. |
| Cloudflare DNS + SSL, custom domain | Not done. Railway domain with Railway TLS. |
| Razorpay live keys deployed | Test mode, deliberately, until launch. |
| Privacy policy and ToS pages | Not in the repository. |
| Data export async via S3 + email, with a cleanup schedule | Export is a direct JSON download. No copy is stored, so nothing needs cleaning up. |
| `docker-compose.prod.yml` | Does not exist. One compose file runs production settings. |
| 16 apps, 53+ models, 130+ endpoints | 18 apps, 67 models, 175 API routes. |
| 11 Celery tasks, 5 schedules | 12 tasks, 7 schedules. |
| 100+ skills, 30+ industries, 4 plans, 30 edges | 55 skills, 21 industries, 5 plans, 28 edges. |
| Neon 7-day point-in-time recovery | Depends on the Neon plan; check the restore window in the Neon console. |
| SendGrid free tier, 100 emails/day | Check the current plan in SendGrid; limits change. |

---

## 3. Found and fixed in production (Step 33)

None of these showed up in 955 passing tests. All were found by deploying and
exercising the real system, and each now has a guard.

| # | Bug | Guard |
|---|---|---|
| P1 | Railway's healthcheck host was not allowed - every deploy would roll back | `healthcheck.railway.app` in production hosts |
| P2 | Admin and API static files 404 - no nginx in front on Railway | WhiteNoise |
| P3 | Email went to SMTP on localhost:25 - no email could be sent | SendGrid backend in production |
| P4 | Test Razorpay keys crashed production with no way to run pre-launch | `RAZORPAY_ALLOW_TEST_KEYS` |
| P5 | Three instant emails had no templates (one set sat in an unextracted zip) | Test renders every instant email |
| P6 | Eight skills used by other seeds were never seeded | Seed consistency test |
| P7 | `TRUSTED_PROXY_COUNT` defaulted to 1; Railway sends 2 - every user shared one IP for lockout and rate limits | Required setting; `check_deploy.py` measures it |

Also from the deploy: a rollback restores that deploy's variables, so a later
setting silently reverts. `DEPLOY.md` section 7 records the procedure.

---

## 3a. Found and fixed after the first deploy

Six more, found while writing the documentation and the API schema. Schema
generation walks every view and serializer, which is why it found a crash no
test had reached.

| # | Bug | Guard |
|---|---|---|
| P8 | `GET /seekers/me/` and the public profile returned **500 for every seeker**: a serializer field was declared but left out of `Meta.fields`. Neither endpoint had a test. | Both endpoints covered; a test builds the fields of every serializer in the project |
| P9 | The admin activity chart dropped today's data between midnight and 05:30 IST - IST day buckets compared against the UTC date | `timezone.localdate()`; test pinned to 00:30 IST |
| P10 | Weekly goals: the same UTC-versus-IST mistake put a user in last week every Monday until 05:30, so progress appeared to reset | As above |
| P11 | The expiry warning picked its target day the same way. Correct at its 09:30 schedule, wrong for any earlier run | As above |
| P12 | Salary queries below the K threshold returned the **exact number of matching submissions** - the most identifying fact about a group too small to publish | Every suppressed reply is identical and carries no count |
| P13 | `from-current/` matched a title by first word and took whichever row came back first: "Backend Engineer" resolved to *Junior* Backend Developer, and the person was shown a more junior career path | Scored matcher; no confident answer without a distinctive word in common |

Also corrected: the salary submission reply claimed "Your data stays
anonymous", which the deduplication link makes untrue (gap 4), and the
advanced ATS endpoint reported "still running" for analyses that had failed,
had never been queued, or never would be.

---

## 4. Resolved since the Phase 3 register

| # | Item | How |
|---|---|---|
| 1 | TOTP secret unencrypted | Fernet field encryption (Step 32) |
| 4 | No GDPR data export | `GET /api/v1/auth/me/export/` |
| 5 | No automated DB backups | Neon managed backups - restore window per plan |
| 6 | No per-user account lockout | Lockout after repeated failures (Step 32) |
| 12 | ngrok URL changes | Production has a fixed domain |
| 13 | Email templates inline | Templates are files; missing ones added (P5) |
| 26 | Salary insights exposed raw min/max | Removed - see REIDENTIFICATION_ASSESSMENT.md |
| 3 | Job view counter wrote to the database on every read | Still open - see below |
| 20 | Advanced ATS never ran on resumes parsed before Step 26 | `queue_missing_advanced_ats` command, and the endpoint now says so |
| 27 | Career path matching on the current title was exact-match only | Scored matcher (P13) |
| 28 | `advanced-ats` said "still running" when nothing was queued | Five distinct states, with `can_retry` |
| 31 | Salary suppression revealed the match count | Removed (P12) |
| L4 | User-facing copy called salary submissions anonymous | Corrected to the wording in gap 4 |
| X1 | No OpenAPI schema or browsable API docs | drf-spectacular; a ratchet test stops undocumented endpoints growing |

---

## 4a. Secret scan of the git history

12 Sep 2026, gitleaks 8.30.1, all 56 commits. **No real secrets found.**

| Finding | Verdict |
|---|---|
| `generic-api-key` in `.github/workflows/ci.yml` | CI-only Fernet key for the test database. Production's key was generated separately. |
| `jwt` in `test_payment.html` | Access token for a test account, local development signing key, expired 18 Aug 2026. Never valid in production. Removed from the file; left in history. |

No `.env` file was ever committed (only `.env.example`). Both findings are in
`.gitleaksignore`; CI now runs the same scan on every push.

---

## 5. Open tech debt

### Before launch

None of these is blocked on code alone.

| # | Item | Waiting on |
|---|---|---|
| L1 | Client IP handling for Cloudflare (`CF-Connecting-IP` from Cloudflare ranges) | Deciding to use Cloudflare |
| L2 | SendGrid domain authentication (SPF, DKIM) | A domain |
| L3 | `DATA_PROTECTION.md` gaps: retention schedule, consent records, breach procedure, DPO decision, key custody procedure, log retention | A lawyer: the retention periods and consent record set the code |
| L5 | Delete or clearly label the smoke-test accounts in production | Launch day |
| L6 | `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` | The frontend |
| L7 | Razorpay live keys, webhook, and one real ₹1 payment; remove `RAZORPAY_ALLOW_TEST_KEYS` | GSTIN and the lawyer |
| L8 | Review copy in the frontend against gap 4 as it is written | The frontend |

### Medium

| # | Item |
|---|---|
| 3 | Job view counter writes to the database on every read |
| 7 | Razorpay Subscriptions API not used - renewal is manual |
| 9 | Resume parsing accuracy 60-70% (spaCy) - LLM upgrade candidate |
| 14 | Admin cannot impersonate a user for support |
| 15 | No retry queue for failed webhook processing |
| 17 | Target roles are curated, not derived from job data |
| 21 | Referral discount codes are manual, not Razorpay coupons |
| 25 | No multi-language support |
| M1 | `web` migrates on start, so it must stay at one replica |
| M2 | No health monitoring for `worker` and `beat` (no HTTP to probe) |
| M3 | 130 of 215 API operations have no documented response body. The ratchet test keeps the number falling; annotate views with `@extend_schema` |
| M4 | The title matcher's synonyms are a hand-written list. It fails safe - no match rather than a wrong one - but new roles need new entries |

### Low

| # | Item |
|---|---|
| 2 | Search history slow at scale |
| 8 | Job-description match uses skill tags only, no TF-IDF |
| 10 | No A/B testing for match weights |
| 11 | SendGrid limits - AWS SES at volume |
| 16 | Resume parsing English-only |
| 18 | Career graph rebuilt per request |
| 19 | Salary outlier trim is simple |
| 22 | No device fingerprinting for referral abuse |
| 23 | Learning resource ratings are static |
| 24 | Salary insights not cached |
| 29 | Seed data never makes the `easiest` career path distinct |
| 30 | One learning resource per skill |
| 32 | Salary comparison gives a position label, not a percentile |

The remaining salary privacy findings are tracked in
REIDENTIFICATION_ASSESSMENT.md.

---

## 6. Numbers

Measured from the code on 12 Sep 2026 (Django app registry, URL resolver,
Celery app, seeded database).

| | |
|---|---|
| Django apps | 18 |
| Models | 67 |
| API routes | 177 |
| Migrations | 47 |
| Management commands | 17 |
| Celery tasks | 12 |
| Celery beat schedules | 7 |
| Automated tests | 1195 |
| Application Python (excluding tests, migrations) | ~30,000 lines |
| Test Python | ~14,000 lines |
| Seeded: skills / industries / categories / plans | 55 / 21 / 36 / 5 |
| Seeded: target roles / learning resources | 7 / 19 |
| Seeded: career path nodes / edges | 23 / 28 |
