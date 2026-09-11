# Project Status

**Career Intelligence Platform - backend.** As of 11 Sep 2026, end of Phase 4.

Replaces `PHASE3_TECH_DEBT.md`. Items carried over keep their original
numbers so older notes still line up.

---

## 1. Where things stand

The backend is built, tested and deployed. The product is not launched.

| Area | State |
|---|---|
| Backend features (Phases 1-3) | Done |
| Docker, CI, Sentry, security hardening (Phase 4) | Done |
| Production deploy on Railway + Neon | Done, smoke-tested, rollback practised |
| Frontend | **Not started** |
| Custom domain, Cloudflare | **Not done** - needs a code change for client IPs (DEPLOY.md, 6) |
| Razorpay live mode | **Not done** - waits on legal review and GSTIN |
| Privacy policy, terms, refund policy | **Not written** - for the lawyer |
| Uptime monitoring | **Not set up** - deliberately, see DEPLOY.md, 9 |

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
| S1 | Found in Step 34: admin activity charts dropped today's activity between midnight and 05:30 IST (IST day buckets compared with the UTC date). Two tests failed in that window. | `timezone.localdate()`; regression test pinned to 00:30 IST |

---

## 5. Open tech debt

### Before launch

| # | Item |
|---|---|
| L1 | Client IP handling for Cloudflare (`CF-Connecting-IP` from Cloudflare ranges) |
| L2 | SendGrid domain authentication (SPF, DKIM) |
| L3 | `DATA_PROTECTION.md` gaps: retention schedule, consent records, breach procedure, DPO decision, key custody procedure, log retention |
| L4 | User-facing copy must not call salary submissions or reviews "anonymous" (REIDENTIFICATION_ASSESSMENT.md) |
| L5 | Delete or clearly label the smoke-test accounts in production |
| 31 | Salary insights below K say exactly how many submissions matched ("3 found"). Checked 11 Sep 2026: still open. A count of 1 versus 0 tells a caller whether one known person submitted. |

### Medium

| # | Item |
|---|---|
| 3 | Job view counter writes to the database on every read |
| 7 | Razorpay Subscriptions API not used - renewal is manual |
| 9 | Resume parsing accuracy 60-70% (spaCy) - LLM upgrade candidate |
| 14 | Admin cannot impersonate a user for support |
| 15 | No retry queue for failed webhook processing |
| 17 | Target roles are curated, not derived from job data |
| 20 | Advanced ATS never runs on resumes parsed before Step 26 |
| 21 | Referral discount codes are manual, not Razorpay coupons |
| 25 | No multi-language support |
| 27 | Career path matching on current title is exact-match only |
| 28 | `advanced-ats` says "still running" when nothing was ever queued |
| M1 | `web` migrates on start, so it must stay at one replica |
| M2 | No health monitoring for `worker` and `beat` (no HTTP to probe) |

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
| X1 | No OpenAPI schema or browsable API docs |
| X2 | `check_expiring_subscriptions` compares an IST `__date` lookup with a UTC date. Correct at its 09:30 IST schedule; wrong if run before 05:30 IST |

The remaining salary privacy findings are tracked in
REIDENTIFICATION_ASSESSMENT.md.

---

## 6. Numbers

Measured from the code on 11 Sep 2026 (Django app registry, URL resolver,
Celery app, seeded database).

| | |
|---|---|
| Django apps | 18 |
| Models | 67 |
| API routes | 175 |
| Migrations | 46 |
| Management commands | 16 |
| Celery tasks | 12 |
| Celery beat schedules | 7 |
| Automated tests | 1007 |
| Application Python (excluding tests, migrations) | ~29,000 lines |
| Test Python | ~13,000 lines |
| Seeded: skills / industries / categories / plans | 55 / 21 / 36 / 5 |
| Seeded: target roles / learning resources | 7 / 19 |
| Seeded: career path nodes / edges | 23 / 28 |
