# Data Protection Record

**Career Intelligence Platform — backend**
Prepared for review under India's Digital Personal Data Protection Act, 2023.

---

## What this document is, and is not

This is an **engineering record**: what personal data the platform holds, what
protects it, and where in the code each measure lives. Every claim below points
at a file, and most are covered by a test.

It is **not** a legal opinion and it is **not** a privacy policy. A lawyer
needs to review it and write those. This document exists so that review starts
from facts rather than from reading the codebase.

The gaps at the end are as much a part of it as the measures.

---

## 1. Personal data collected

### Job seekers

| Data | Why | Where |
|---|---|---|
| Email, password hash, name | Account identity | `accounts.User` |
| Profile: bio, location, photo, titles | Shown to recruiters | `seekers.SeekerProfile` |
| Skills, work history, education | Job matching | `seekers.SeekerSkill`, `WorkExperience`, `Education` |
| Resume files (PDF/DOC) | Applications, parsing | `resumes.Resume`, stored on S3 |
| Parsed resume content | Skill extraction, ATS scoring | `resumes.ResumeSkill` |
| Applications and cover letters | The core product | `applications.Application` |
| Search history, saved searches | Convenience features | `jobs.SearchHistory`, `SavedSearch` |
| Salary submissions | Aggregate insights | `career_intel.SalarySubmission` |
| Login history: IP, user agent | Security, account review, login lockout | `accounts.LoginHistory` |
| Two-factor secret, backup codes | Two-factor login | `accounts.TwoFactorAuth` (encrypted), `BackupCode` (hashed) |
| FCM device token | Mobile push, when the app ships | `accounts.User.fcm_token` |
| Company reviews | Employer transparency | `reviews.CompanyReview` |
| Interview experiences | Helping the next candidate | `reviews.InterviewExperience` |
| Badges, points, streaks | Retention | `gamification.*` |
| Interview checklist progress | Preparation tracking | `interview_prep.ChecklistProgress` |

### Recruiters

Company details, designation, contact information, and a record of which
candidate profiles they viewed (`recruiters.CandidateView`).

### Both

Payment records (`payments.PaymentTransaction`, `Subscription`) and an audit
trail of changes to critical models (`audit.AuditLog`).

---

## 2. What the person can do with their data

### Access and portability

`GET /api/v1/auth/me/export/` returns everything held about the requesting
user as JSON. `?download=true` serves it as a file.

Implementation: `accounts/privacy.py::DataExportService`.

Two categories are deliberately excluded, and the export says so in its own
metadata:

- **Authentication secrets** — password hash, TOTP secret, OTP and backup-code
  hashes. Returning these creates risk and gives the person nothing they can
  use.
- **A recruiter's private notes on an application.** These are the recruiter's
  own assessment. This is a judgement call and worth a second opinion: an
  argument exists that notes *about* a person are that person's data.

### Erasure and account closure

`POST /api/v1/auth/me/deactivate/` closes the account. Implementation:
`accounts/privacy.py::AccountDeactivationService`.

It withdraws live applications, stops billing, revokes every session by
blacklisting outstanding refresh tokens, sets the profile to private, and soft
deletes the user.

**Soft delete, not erasure — and the reason matters.** Payment records,
applications and audit entries are referenced by other parties: a recruiter's
hiring record, a GST invoice, a financial audit trail. Removing the row would
damage records that are not solely the departing user's.

What stops is the person's presence: they cannot log in, cannot be found in
search, are not billed, and do not receive email.

**This needs legal review.** DPDP grants a right to erasure. Whether soft
deletion satisfies it, and what a full purge would have to preserve, is a legal
question this document cannot answer.

### Correction

Profile, skills, experience and education are all editable through the API.
Parsed resume data has a manual correction interface
(`resumes/views.py`: add, remove and confirm extracted skills) because
automated extraction gets things wrong.

### Consent and preferences

- Profile visibility: `public`, `recruiters_only`, `private`
  (`SeekerProfile.visibility`)
- A separate discovery opt-out (`is_open_to_opportunities`)
- Per-category email preferences (`notifications.NotificationPreferences`)
- Unsubscribe links carry a token and need no login
- Mobile push is **off by default**. Registering a device does not enable it —
  a device token is not consent.

---

## 3. Salary submissions

The most sensitive collection on the platform, and the one where the promise
made to the user is strongest.

### The promise, stated precisely

Aggregate salary figures are published. No aggregate should be traceable to an
individual submission.

### How it is kept

**K-anonymity.** No aggregate is returned below `SALARY_K_ANONYMITY`
submissions (default 5). Four submissions and a median is enough for someone
who knows three of the four to derive the fourth.

**Individual figures are not published.** `min` and `max` were removed: each
is one person's exact salary, and two queries differing by a single filter
recovered it directly.

**Published percentiles sit between submissions.** Rank interpolation returns
a member whenever the index is whole - at five submissions that was p25, the
median and p75 all at once. `publication_percentile` blends with a neighbour
instead, so no published figure is anybody's salary.

**Figures are banded**, proportionally to the median. A separate defence from
the one above: it stops a published number being an exact figure that can be
matched against outside knowledge.

The reasoning behind all three, including two proposed fixes that failed
testing, is in `REIDENTIFICATION_ASSESSMENT.md`.

The check runs **again after outlier trimming**. Five submissions where two are
junk leaves three real ones; checking only before trimming would make the
guarantee skin deep. (`salary_services.py`, tested.)

**Outlier removal.** IQR-based and absolute-bound trimming, so one typo cannot
move a published median.

**IP hashing.** The submitting address is stored as an HMAC-SHA256 keyed with a
dedicated pepper (`SALARY_IP_PEPPER`), never in the clear.

The keying is the point, not a detail. There are roughly four billion IPv4
addresses — a plain `sha256(ip)` is reversible with a lookup table anyone can
build in an afternoon. Hashing without a secret would not be anonymising.

The pepper is deliberately **not** `SECRET_KEY`: rotating one should not
invalidate the other, and a leaked `SECRET_KEY` should not also de-anonymise
salary data.

If the pepper is unset, the hash is empty rather than weak. A misconfigured
deployment loses rate limiting; it does not gain a reversible record of every
submitter's address.

**Per-device rate limiting.** Three submissions per IP per 24 hours by default.
One person with several accounts still has one machine.

The address is the one delivered by the platform's own proxies
(`core/client_ip.py`, see §5). Until 11 September it was the first
`X-Forwarded-For` entry, which the client types: a different made-up address
on each request walked straight past this limit, and with it the protection
of the aggregates. Fixed before any production deployment.

**Per-user deduplication.** One submission per role per year.

### The honest caveat

`SalarySubmission` stores a foreign key to `User`.

It is needed for deduplication, and it is never exposed through any aggregation
endpoint. But it exists. Under DPDP this makes the data **pseudonymous, not
anonymous**, and any user-facing copy calling it "anonymous" overstates what
the system does.

**Decided: the link stays and the wording changes.** The keyed-hash
alternative does not survive the requirement to deduplicate - see gap 4.

---

## 3a. Company reviews

The same tension as salary submissions, and the same resolution.

**The promise:** a review is published without the author's name attached.

**How it is kept:** `CompanyReview.author` is a foreign key to the reviewer.
It appears in no serializer, no field list, no ordering and no filter. The API
exposes an `is_mine` boolean so the frontend can show edit controls, which
reveals nothing about anyone else's review.

The link is stored because the alternative is worse: with no author on file,
one person can post fifty reviews of a company that rejected them and nobody
can tell.

**Same caveat as salary.** This makes reviews **pseudonymous, not anonymous**.
Any user-facing copy calling them anonymous overstates what the system does -
see gap 4 for the wording that is accurate.

**Verification:** `is_verified_employee` is set when the author has an
application to that company on file. It proves interest, not employment, and
is labelled as what it is - claiming stronger verification than the platform
has would be worse than claiming none. It is computed server-side and cannot
be set by the submitter.

**Moderation:** reviews publish immediately and are hidden once three people
report them. Pre-moderation was considered and rejected - review sections that
queue for admin approval sit empty, because nobody writes into a void for a
week.

The threshold is three rather than one so a company cannot bury a fair review
with a handful of coordinated reports. The response to a report does not say
whether the review was hidden; telling a reporter how close they are to the
threshold is an invitation to organise the rest.

---

## 3b. Gamification data

Points, badges and streaks are behavioural records: they show when someone was
job hunting and how actively.

`PointsLedger` is append-only and every entry is retained, because a balance
that cannot be explained is worse than no balance. `ApplicationStreak` records
which weeks a person applied in.

Both are included in the data export and go with the account on closure.

Worth flagging for the retention schedule: this is the one category where the
data has no use at all once the person stops job hunting.

---

## 4. Cross-border transfer

**Sentry (error tracking) is hosted in the United States.** Error events leave
India. DPDP permits transfer except to restricted countries, but the transfer
is real and belongs in the privacy notice.

What is deliberately kept out of those events
(`core/observability.py::before_send`, tested):

- `send_default_pii=False` — Sentry's default of attaching a username and IP to
  every event is off
- Passwords, tokens, signatures, API keys, FCM tokens → `[Filtered]`
- **Salary figures** → `[Filtered]`, because they are collected on a promise
- Cookies dropped entirely — there is no safe version of a session cookie
- Scrubbing recurses through nested dictionaries and lists
- The same scrubbing covers performance transactions
  (`before_send_transaction`), not only error events. Before 10 September
  it covered errors alone.

Sentry receives stack traces, error messages, and timing data for a sample of
requests. It also receives, deliberately:

- **The internal user id and role** of the person whose request failed
  (`core/authentication.py`, `core/observability.py::tag_user`, tested). No
  email, no name. This is pseudonymous personal data leaving India and the
  privacy notice should say so. It lets someone with admin access match a
  reported error to an account, without a third party holding who that
  account belongs to.
- **A request id**, which is also returned to the client as `X-Request-ID`,
  so a user reporting a problem can quote it.

Tracing is sampled by path: health checks never, payment, subscription and
webhook requests always, everything else at `SENTRY_TRACES_SAMPLE_RATE`.

**Other third parties:** AWS S3 (resume files, region configurable), SendGrid
or AWS SES (transactional email), Razorpay (payments, India). Each needs
listing in the privacy notice with its region.

**Have I Been Pwned** (breached-password check, production only). When a
password is set, the first five characters of its SHA-1 hash are sent and the
match is made locally against the list that comes back, with padding requested
so the response size gives nothing away. The password, its full hash and any
account identifier never leave the server (`accounts/validators.py`, tested).
Whether this is a transfer of personal data at all is doubtful, but it is a
third-party call made during signup, and a notice that lists it costs nothing.

---

## 5. Security measures

| Measure | Implementation |
|---|---|
| Password hashing | Django PBKDF2 |
| Breached passwords | Rejected in production by a k-anonymous Have I Been Pwned lookup; fails open if the service is unreachable |
| Two-factor auth | TOTP (`pyotp`); secret encrypted at rest with Fernet (`accounts/fields.py`); backup codes stored as SHA-256 hashes |
| Session revocation | JWT blacklist; access 15 min, refresh 7 days, rotated on use |
| OTP brute force | 3 attempts, then the code is burned; 10-minute expiry |
| Login lockout | 5 failures for one email from one address in 15 minutes locks that pair until the oldest ages out; same response whether or not the account exists (`accounts/lockout.py`) |
| Rate limiting | Login 5/min, OTP 3/hr, password reset 3/hr, search 60/min, apply 20/hr, payments 10/hr |
| Transport | HSTS with preload, SSL redirect, secure cookies (`settings/production.py`) |
| Payment integrity | Razorpay signature verification on the raw body; amount cross-checked before activation |
| Audit trail | `audit.AuditLog` — actor, action, before/after values, IP, timestamp |
| Client address | Only `X-Forwarded-For` entries appended by the platform's own proxies are trusted (`TRUSTED_PROXY_COUNT`). One definition used by rate limits, lockout, login history, the audit trail and salary limits (`core/client_ip.py`) |
| Logging | JSON lines with a request id on each; secrets passed as structured fields are scrubbed; requests logged by URL pattern, never raw path (`core/log_format.py`, `core/middleware.py`) |

The audit log excludes sensitive fields by name (`audit/signals.py`:
passwords, tokens, secrets, salary figures) so the trail itself does not become
a second copy of the data it is meant to protect.

**Login lockout is keyed on email and address together, deliberately.** Keyed
on email alone, anyone could lock an owner out of their own account with five
wrong guesses, repeatably. Failures are counted for any email string, registered
or not, so a lock reveals nothing about whether an account exists. The owner is
not emailed when a lock happens: that would let anyone send them a message every
fifteen minutes.

**Client addresses before 11 September.** Until then, the IP recorded in login
history, the audit trail and salary rate limiting was the first
`X-Forwarded-For` entry, which a client can set to anything. Rate limits could
be bypassed and a malformed value could fail the request. No production
deployment existed at the time, but any data carried over from testing should
not be treated as evidence of where a request came from.

**The encryption key.** `FIELD_ENCRYPTION_KEY` comes from the environment, never
from the database or the repository. Several keys can be listed to rotate: the
first encrypts, all decrypt. A wrong or missing key fails loudly instead of
quietly breaking two-factor checks. Losing every copy of the key makes every
stored secret unrecoverable - see gap 9.

---

## 6. Retention

| Data | Retained | Note |
|---|---|---|
| Account | Until deactivated, then soft deleted | Row kept; see §2 |
| Applications | Indefinitely, soft deleted on withdrawal | Recruiter's hiring record |
| Payments and invoices | Indefinitely | Financial and tax records |
| Audit log | Indefinitely | Append-only by design |
| Login history | Indefinitely | Export caps at the most recent 200. Lockout reads only the last 15 minutes, so a short retention period would not weaken it |
| Resume files | Until the user deletes them | S3 |
| OTP codes | 10 minutes | Then expired and unusable |
| Refresh tokens | 7 days | Blacklisted on logout or closure |
| Salary submissions | Aggregates use a 2-year window | Older rows excluded from published figures |
| Application logs | Not yet decided | Carry internal user ids and request metadata; storage depends on the hosting platform (gap 10) |
| Sentry events | Set by the Sentry plan | Retention is Sentry's, not ours; confirm the plan's period before launch |

**No automated purge exists.** Nothing is deleted on a schedule. A retention
schedule with defined periods per category is one of the gaps below.

---

## 7. Gaps — outstanding before launch

These are known and unresolved. They are listed because a compliance record
that only lists what was done is not a compliance record.

### 1. Re-identification risk assessment — done, one item open

`REIDENTIFICATION_ASSESSMENT.md`. Three defects found and fixed.

What remains open from it: `role_title` and `location_city` are free-text
filters, so a caller can probe arbitrary values. The K threshold applies to
every slice, so nothing comes back below five - but a query returning nothing
discloses that a known individual did not submit. Weak, and still a
disclosure.

K=5 was not derived from this dataset. It should be revisited against the real
distribution of role and city combinations once there are enough submissions
to look at.

### 2. Retention schedule

Every category above says "indefinitely". DPDP expects data to be erased when
the purpose is served. Each category needs a defined period and an automated
purge.

### 3. Erasure versus soft delete

Covered in §2. Needs a legal answer.

### 4. The "anonymous" claim — decided

Both salary submissions and reviews store an author link. Both are
pseudonymous, not anonymous.

**Decision: keep the link, change the wording.**

The alternative this document originally proposed - replacing the foreign key
with a keyed hash of the user id - does not work, and it is worth recording
why rather than leaving it as an open option.

The hash would have to be deterministic, or deduplication breaks: "one
submission per user per role per year" and "one review per person per company"
both need to recognise a returning author. Deterministic means anyone holding
the pepper can recompute it and re-link. Data export needs the same
capability, because a person asking what is held about them has to be answered.

So the hash is pseudonymisation wearing a disguise. Under DPDP it is treated
identically, and it is arguably worse than the foreign key because it looks
anonymous to anyone reading the schema.

**The underlying constraint:** deduplication requires linkability. "One
submission per person" and "truly anonymous" cannot both hold. Deduplication
is not optional here - without it one person can move a published median alone,
or post fifty reviews of a company that rejected them.

**What changes instead** - user-facing copy must not say "anonymous". Accurate
wording:

- *"Your name is never shown."* True.
- *"Only aggregate figures are published."* True, and covered by tests.
- *"We keep a private record of who submitted, to prevent duplicates and
  abuse."* True, and worth saying rather than hiding.

What must not be said: "anonymous", "we do not know who you are", "untraceable".

### 5. Recruiter notes in the export

Covered in §2. Needs a second opinion.

### 6. Consent records

Preferences are stored, but not *when* and *how* consent was given. DPDP
expects a consent record. A `ConsentLog` model would close this.

### 7. Data Protection Officer

DPDP requires a designated contact for significant data fiduciaries. Whether
the platform qualifies depends on scale — worth deciding early.

### 8. Breach notification procedure

DPDP mandates notification to the Data Protection Board and affected users.
Sentry gives detection; the procedure itself does not exist.

### 9. Encryption key custody

The code side is done: two-factor secrets are encrypted, and a missing or wrong
key fails loudly. What does not exist is the procedure around the production
key - where it is stored, who can read it, how it is backed up, and how a
rotation is carried out. Without a backup, losing the key forces every user
with two-factor authentication to enrol again.

Only the two-factor secret is encrypted at field level. Everything else relies
on the database host's encryption at rest, which needs confirming when the
hosting provider is chosen.

### 10. Application log storage and retention

Structured logs carry internal user ids, URL patterns, status codes and
timings. Where they are stored, who can read them and for how long depends on
the hosting platform, and none of that is decided yet. They belong in the
retention schedule (gap 2).

---

## 8. Where to verify each claim

| Claim | File | Tests |
|---|---|---|
| Data export | `accounts/privacy.py` | `accounts/tests.py` |
| Account closure | `accounts/privacy.py` | `accounts/tests.py` |
| Profile visibility | `seekers/models.py::discoverable` | `recruiters/tests.py` |
| K-anonymity | `career_intel/salary_services.py` | `career_intel/test_salary.py` |
| IP hashing | `career_intel/salary_services.py::hash_ip` | `career_intel/test_salary.py` |
| Sentry scrubbing | `core/observability.py` | `core/tests.py` |
| Audit trail | `audit/signals.py` | `audit/tests.py` |
| Auth security | `accounts/services.py` | `accounts/test_services.py` |
| Rate limits | `core/throttles.py`, `settings/base.py` | `core/tests.py` |
| Review anonymity | `reviews/serializers.py` | `reviews/tests.py` |
| Review moderation | `reviews/services.py` | `reviews/tests.py` |
| Published percentiles | `career_intel/salary_algorithm.py` | `career_intel/test_salary.py` |
| 2FA secret encryption | `accounts/fields.py`, migration `0006` | `accounts/test_security_hardening.py` |
| Breached-password check | `accounts/validators.py` | `accounts/test_security_hardening.py` |
| Login lockout | `accounts/lockout.py` | `accounts/test_login_lockout.py` |
| Trusted client address | `core/client_ip.py` | `accounts/test_login_lockout.py`, `core/test_client_ip_everywhere.py` |
| Sentry user context and sampling | `core/authentication.py`, `core/observability.py` | `core/test_request_tracing.py` |
| Log scrubbing, request ids | `core/log_format.py`, `core/middleware.py` | `core/test_request_tracing.py` |

Run `pytest -m regression` to exercise the behaviours these measures depend on.

---

*Prepared 09 September 2026, revised 11 September | Backend at 955 tests*
*Requires legal review before launch.*
