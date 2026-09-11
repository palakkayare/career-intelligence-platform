# Deployment Runbook

**Career Intelligence Platform - backend**

How production is laid out, how to change it safely, and how to check that a
change did what it was meant to. Written after the first deploy (Step 33),
including what the rollback practice showed that the tutorial did not.

---

## 1. What runs where

| Piece | Where | Notes |
|---|---|---|
| `web` | Railway, Singapore | Gunicorn. Public domain. Healthcheck `/api/v1/health/ready/`. Only service that migrates. |
| `worker` | Railway, Singapore | Celery worker: resume parsing, emails, match scores. No domain, no healthcheck. |
| `beat` | Railway, Singapore | Celery beat. **Exactly one replica, always** - two send every scheduled email twice. |
| `Redis` | Railway, same project | Queue and cache, over the private network. Has a volume. |
| Postgres | Neon, AWS Singapore | Direct (non-pooled) connection string. |
| Files | AWS S3, `ap-south-1` | Resumes. Private bucket, presigned download links. |
| Email | SendGrid | Via django-anymail. |
| Errors | Sentry | Environment `production`, release = git commit. |

All three Railway services build from the same repo and the same Dockerfile.
`SERVICE_ROLE` (`web` / `worker` / `beat`) decides what a container runs - see
`docker/entrypoint.sh`. **Custom Start Command stays empty** on every service.

Every service has **Wait for CI** on, so a push to `main` deploys only after
tests pass.

---

## 2. Variables

The template with every variable and how to generate each secret is
`deploy/railway-variables.example`. Secrets live in Railway and in the
password manager - never in the repo, never in chat.

Production **refuses to start** when something required is missing or points
at `localhost`, and lists every problem at once in the deploy logs
(`apps/core/deploy_checks.py`). If a deploy crashes on start, read those
lines first.

Two values need care:

- **`FIELD_ENCRYPTION_KEY`** encrypts 2FA secrets. Losing or changing it locks
  every 2FA user out. It is backed up outside Railway. To rotate, put the new
  key first and keep the old one after a comma.
- **`TRUSTED_PROXY_COUNT`** must match the real proxy setup - see section 6.

`web` also has `PORT=8000`. `worker` and `beat` do not need it.

---

## 3. Deploying

A normal deploy is a push to `main`:

1. `black --check . && isort --check-only . && flake8 . && pytest`
2. Commit and push.
3. CI runs; when it is green Railway builds and deploys all three services.
4. Run the deploy check (section 5).

To redeploy the latest code without a code change (for example after a
rollback, or to pick up changed variables on every service):

```bash
git commit --allow-empty -m "Redeploy"
git push
```

Changing a variable in Railway creates a new deploy of **that service only**,
with the same code.

---

## 4. Migrations

`web` runs `migrate` on start (`RUN_MIGRATIONS`, default on for the web role).
`worker` and `beat` never migrate. Keep `web` at one replica while this is so;
several replicas starting together would race on the same migration.

A migration and the code that uses it deploy together, so for a moment old
code can meet the new schema. Safe and unsafe changes:

| Change | How |
|---|---|
| Add a nullable column, or one with a default | One deploy. |
| Add a table | One deploy. |
| Add an index on a large table | `AddIndexConcurrently` (needs `atomic = False` on the migration). |
| Remove a column | **Two deploys.** First: code stops using it. After a day with no errors: the migration that drops it. |
| Rename a column or table | **Three deploys.** Add the new one and write to both; move reads; drop the old one. |
| Make a column non-null | Backfill first in its own deploy, then add the constraint. |

Before a risky migration, take a Neon snapshot: Neon console -> Branches ->
create a branch from `production`. Restoring means pointing `DATABASE_URL` at
that branch.

**A rollback does not undo a migration.** Migrations only move forward. If a
deploy with a migration has to be rolled back, the old code must still work
with the new schema - which the table above is there to guarantee.

---

## 5. Checking a deploy

Run this after **every** deploy and **every** rollback:

```bash
python scripts/check_deploy.py
```

It reads `ADMIN_EMAIL` / `ADMIN_PASSWORD` from
`~/.career-intel/career-intel-keys.txt` (override with `CAREER_INTEL_KEYS`) and
checks, against the running app rather than the dashboard:

1. **Ready** - database and cache reachable.
2. **Release** - the commit actually running, and whether it is your local `HEAD`.
3. **Settings in force** - environment, `TRUSTED_PROXY_COUNT`, Razorpay mode,
   S3, Sentry.
4. **Client IP** - which forwarded address the app uses, and that a fake
   `X-Forwarded-For` from the client does not change it.

It prints no secrets and no IP addresses, and exits non-zero if a check fails.

Then watch Sentry for new issues for 30 minutes.

After a deploy that touches a feature, test that feature the way a user
would. The Step 33 smoke tests (signup with email code, resume upload with
parsing and S3, Razorpay test order) are the model for this.

---

## 6. Client IP and proxies

Login lockout, rate limits and the salary submission limit all key on the
client IP (`apps/core/client_ip.py`). `TRUSTED_PROXY_COUNT` tells the app how
many entries at the right-hand end of `X-Forwarded-For` were added by our own
infrastructure.

**Measured on Railway (Step 33): 2.** `X-Forwarded-For` arrives with two
entries - the client, then Railway's edge - and a client-supplied header is
thrown away and rebuilt by Railway rather than appended to.

| Value | Effect on Railway |
|---|---|
| 1 | Every user resolves to Railway's edge address. One user's failed logins lock **everyone** out; one user's traffic throttles everyone. |
| 2 | Correct. A fake header from the client cannot change the result. |

**Never set this by reasoning - measure it** with `scripts/check_deploy.py`
(or `GET /api/v1/admin/dashboard/client-ip/` as staff) after any change in
front of the app.

**Cloudflare changes this in a way a number cannot fix.** Because Railway
discards the incoming `X-Forwarded-For`, the client address Cloudflare adds
would be thrown away too, and the app would see Cloudflare's address for
everyone. With Cloudflare proxying, the client IP has to come from
`CF-Connecting-IP`, trusted only when the connection comes from Cloudflare's
published address ranges. That is a code change to make, and measure, as part
of adding Cloudflare - not a variable edit.

---

## 7. Rolling back

Railway -> service -> **Deployments** -> an earlier deploy -> **⋮** ->
**Rollback**. The old image starts; nothing is rebuilt.

What the practice rollback showed:

1. **A rollback restores that deploy's variables as well as its code.** A
   setting changed after that deploy silently goes back. Rolling back past the
   `TRUSTED_PROXY_COUNT` fix brought the shared-IP bug back.
2. **The Variables tab does not show what is running.** It shows what the
   next deploy will get. After a rollback it still said 2 while the app ran
   with 1. Only the running app tells the truth - run the deploy check.
3. **To go forward again, do not hunt for the right old deploy.** Push an
   empty commit (section 3). That deploys the latest code with the current
   variables.

Rollback procedure:

1. Roll back the broken service(s). Code-only bugs usually need just `web`;
   a bad task or email change needs `worker` too.
2. Run `python scripts/check_deploy.py`. Check the release **and** the
   settings in force.
3. If a setting came back wrong, fix it in Variables and deploy that service
   again, then check again.
4. Fix the bug on `main`, push, and check once more.

A migration cannot be rolled back this way - see section 4.

---

## 8. One-off commands against production

Seeds and admin changes run from a Mac, pointed at Neon for the length of one
subshell only, with test settings so Redis and email are never touched:

```bash
(
  echo -n "Neon URL: "; read -s DATABASE_URL; echo
  export DATABASE_URL DJANGO_SETTINGS_MODULE=config.settings.test PYTHONWARNINGS=ignore
  python manage.py seed_skills && python manage.py seed_target_roles
)
```

- The URL is typed, not stored in shell history, and disappears when the
  subshell ends - a later `pytest` cannot reach production by accident.
- **Do not create users or passwords this way.** Test settings hash passwords
  with MD5, which production cannot verify. Register through the API, then
  promote the user in a shell (as Step 33 did for the admin account).
- Seeds are safe to re-run; `apps/career_intel/test_seed_consistency.py`
  keeps them in agreement.
- Never run anything in `scripts/dev/` against production - it creates test
  data.

---

## 9. Costs

- **Railway** bills for memory and CPU while services run, whether or not
  anyone uses them. Check Usage weekly; a usage limit is set on the account.
  Before launch, removing the three deployments stops the bill; variables are
  kept and a push brings them back.
- **Neon** free plan has limited compute hours. The database suspends when
  idle; anything polling it every few minutes (an uptime check on
  `/health/ready/`) keeps it awake around the clock. Point uptime monitoring at
  `/api/v1/health/` (no database) until on a paid plan.

---

## 10. Before launch

Not done yet, and each one matters:

- [ ] Frontend deployed; `CORS_ALLOWED_ORIGINS` and `FRONTEND_URL` set.
- [ ] Custom domain; Cloudflare with the client-IP change in section 6, measured.
- [ ] Custom domain added to `DJANGO_ALLOWED_HOSTS` and `CSRF_TRUSTED_ORIGINS`
      (keep the Railway domain until the switch is done).
- [ ] SendGrid domain authentication (SPF/DKIM) so mail stays out of spam.
- [ ] Lawyer review of `DATA_PROTECTION.md`; privacy policy, terms, refund policy published.
- [ ] Real `INVOICE_GSTIN`.
- [ ] Razorpay live keys, webhook at `/api/v1/webhooks/razorpay/` with events
      `payment.captured`, `payment.failed`, `order.paid`, `refund.processed`,
      `subscription.charged`, `subscription.cancelled`; remove
      `RAZORPAY_ALLOW_TEST_KEYS`; one real ₹1 payment end to end.
- [ ] Uptime monitoring (section 9).
- [ ] Delete the smoke-test accounts, or keep them clearly labelled.
