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
| Login history: IP, user agent | Security, account review | `accounts.LoginHistory` |
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

**Per-user deduplication.** One submission per role per year.

### The honest caveat

`SalarySubmission` stores a foreign key to `User`.

It is needed for deduplication, and it is never exposed through any aggregation
endpoint. But it exists. Under DPDP this makes the data **pseudonymous, not
anonymous**, and any user-facing copy calling it "anonymous" overstates what
the system does.

Two options for review:

1. Keep the FK and describe the collection accurately as pseudonymous.
2. Replace it with a keyed hash of the user id — deduplication still works, the
   link no longer does.

This is a product and legal decision, not a technical blocker.

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
Any user-facing copy calling them anonymous overstates what the system does.

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

Sentry receives stack traces and error messages. It does not receive user
identities.

**Other third parties:** AWS S3 (resume files, region configurable), SendGrid
or AWS SES (transactional email), Razorpay (payments, India). Each needs
listing in the privacy notice with its region.

---

## 5. Security measures

| Measure | Implementation |
|---|---|
| Password hashing | Django PBKDF2 |
| Two-factor auth | TOTP (`pyotp`), backup codes stored as SHA-256 hashes |
| Session revocation | JWT blacklist; access 15 min, refresh 7 days, rotated on use |
| OTP brute force | 3 attempts, then the code is burned; 10-minute expiry |
| Rate limiting | Login 5/min, OTP 3/hr, password reset 3/hr, search 60/min, apply 20/hr, payments 10/hr |
| Transport | HSTS with preload, SSL redirect, secure cookies (`settings/production.py`) |
| Payment integrity | Razorpay signature verification on the raw body; amount cross-checked before activation |
| Audit trail | `audit.AuditLog` — actor, action, before/after values, IP, timestamp |

The audit log excludes sensitive fields by name (`audit/signals.py`:
passwords, tokens, secrets, salary figures) so the trail itself does not become
a second copy of the data it is meant to protect.

---

## 6. Retention

| Data | Retained | Note |
|---|---|---|
| Account | Until deactivated, then soft deleted | Row kept; see §2 |
| Applications | Indefinitely, soft deleted on withdrawal | Recruiter's hiring record |
| Payments and invoices | Indefinitely | Financial and tax records |
| Audit log | Indefinitely | Append-only by design |
| Login history | Indefinitely | Export caps at the most recent 200 |
| Resume files | Until the user deletes them | S3 |
| OTP codes | 10 minutes | Then expired and unusable |
| Refresh tokens | 7 days | Blacklisted on logout or closure |
| Salary submissions | Aggregates use a 2-year window | Older rows excluded from published figures |

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

### 4. The "anonymous" claim on salary submissions and reviews

Covered in §3 and §3a. Both store an author link; both are pseudonymous.

One decision covers both: either describe them accurately, or replace the
foreign key with a keyed hash of the user id - deduplication and abuse
handling still work, the link does not.

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

Run `pytest -m regression` to exercise the behaviours these measures depend on.

---

*Prepared 09 September 2026, revised 10 September | Backend at 882 tests*
*Requires legal review before launch.*
