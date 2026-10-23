# Cooperative Management SaaS Platform

Multi-tenant backend for cooperative societies that run on **salary source deduction**.
Contributions and loan repayments are deducted at the institution's payroll (bursary)
office, not collected through the app. The platform's job is to keep the records,
generate the deduction schedules, and enforce the rules.

ACADA Cooperative Society is tenant #1, not a special case — every society is a tenant.

**Stack:** Django 5.1 · Django REST Framework · PostgreSQL 16 · Redis · Celery

---

## 📖 User manual

The end-user manual lives with the frontend, in
[`../ACADA-Frontend/docs/user-manual/`](../ACADA-Frontend/docs/user-manual/README.md).
It documents every role's portal screen by screen — what each role may and may
not do, with user stories and worked examples:

| Chapter | Role |
| --- | --- |
| [00 — System overview](../ACADA-Frontend/docs/user-manual/00-system-overview.md) | Everybody |
| [01 — Member](../ACADA-Frontend/docs/user-manual/01-member.md) | `MEMBER` |
| [02 — Committee member](../ACADA-Frontend/docs/user-manual/02-committee-member.md) | `COMMITTEE_MEMBER` |
| [03 — Executive](../ACADA-Frontend/docs/user-manual/03-executive.md) | `EXECUTIVE` |
| [04 — Society admin](../ACADA-Frontend/docs/user-manual/04-society-admin.md) | `SOCIETY_ADMIN` |
| [05 — Platform admin](../ACADA-Frontend/docs/user-manual/05-super-admin.md) | `SUPER_ADMIN` |
| [06 — Permissions reference](../ACADA-Frontend/docs/user-manual/06-permissions-reference.md) | Everybody |

---

## Quick start

You need Docker Desktop running.

```bash
git clone https://github.com/Abdulmateenmuthoir/COOPERATIVE.git
cd COOPERATIVE

cp .env.example .env          # required — compose will not start without it
docker compose up --build -d
docker compose exec web python manage.py migrate
docker compose exec web python manage.py seed_demo
```

That's it. The API is on <http://localhost:8000>.

| What | Where |
|---|---|
| Swagger UI | <http://localhost:8000/api/docs/> |
| ReDoc | <http://localhost:8000/api/redoc/> |
| OpenAPI schema (JSON) | <http://localhost:8000/api/schema/> |
| Django admin | <http://localhost:8000/admin/> |

Generate a typed client straight from the schema rather than hand-writing calls:

```bash
curl http://localhost:8000/api/schema/ -o openapi.json
```

### `seed_demo`

A fresh database has no roles, no tenant and no members. Because `Membership` requires a
`Role` and the tenant middleware requires an active `Membership`, **every tenant-scoped
endpoint returns 403 until those rows exist** — and there is no way to create them through
the API. `seed_demo` bootstraps it:

```bash
docker compose exec web python manage.py seed_demo           # idempotent, tops up
docker compose exec web python manage.py seed_demo --reset   # rebuild from scratch
```

It creates the ACADA tenant, the five roles, a platform admin, a president, a treasurer,
a read-only committee member, six members, six closed contribution cycles (one with a
missed payment and a penalty), a loan product, and one active loan with a repayment
schedule.

**Demo accounts** — password `Passw0rd!23`, tenant code `acada`:

| Email | Role | Sees |
|---|---|---|
| `platform@acada.demo` | SUPER_ADMIN | Django admin (as a superuser) and `/api/v1/platform/` |
| `president@acada.demo` | SOCIETY_ADMIN | everything in the society |
| `treasurer@acada.demo` | EXECUTIVE | financials, schedules, loan approvals |
| `committee@acada.demo` | COMMITTEE_MEMBER | read-only cycles, reports, loans and roster |
| `adebayo@acada.demo` | MEMBER | own contributions + the active loan |
| `chinelo@acada.demo` … `hauwa@acada.demo` | MEMBER | own records only |

`seed_demo` is idempotent and tops up: it re-applies role flags to accounts that
already exist, so changing a flag and re-running is enough to upgrade the demo
accounts.

---

## Authentication

JWT (`Bearer`). Access tokens last 30 minutes; refresh tokens 7 days and rotate on use.

**`tenant_code` binds the token to a society** — a user can belong to several, so the
society is named at login. It is optional when the user belongs to exactly one active
society: the backend then resolves it from their membership. Supplying a code that
does not match a society the user belongs to is an error, and a user with no
membership — or with several and no code to disambiguate — is refused with a message
saying so.

```http
POST /api/v1/auth/login/
Content-Type: application/json

{ "email": "treasurer@acada.demo", "password": "Passw0rd!23", "tenant_code": "acada" }
```

```jsonc
{
  "access":  "eyJhbGciOi...",
  "refresh": "eyJhbGciOi...",
  "tenant":  { "id": "...", "code": "acada", "name": "ACADA Cooperative Society" },
  "role":    "EXECUTIVE",
  "user":    { "id": "...", "email": "treasurer@acada.demo", "full_name": "Segun Balogun" }
}
```

Send the access token on every request. **Nothing else is needed** — the tenant is carried
as a signed claim inside the token:

```http
Authorization: Bearer <access>
```

> An `X-Tenant-ID` header is still honoured as a fallback for manual testing, but don't
> build against it. It's client-supplied where the JWT claim is signed. To switch
> societies, log in again with a different `tenant_code`.

Refresh with `POST /api/v1/auth/refresh/` `{"refresh": "..."}`.

### What the error codes mean

| Code | Meaning |
|---|---|
| 401 | Missing, expired or invalid token |
| 400 `Tenant context required` | Token has no tenant claim and no `X-Tenant-ID` was sent |
| 400 `Validation failed` | Login problem — the `errors` map says which field and why (bad society code, no membership, several memberships) |
| 403 `Access denied` | Valid token, but no active membership in that society |
| 403 `Tenant inactive` | The society is suspended or deactivated |

---

## API surface

All routes are under `/api/v1/`. Lists are paginated (`?page=`, `?page_size=`).

**Auth** — `login/` · `refresh/` · `logout/` · `register/` · `me/` · `password/change/`

**Members** — `members/` · `members/{id}/` · `members/{id}/profile/` · `members/{id}/role/` ·
`members/{id}/status/` · `members/pending/` · `members/guarantor-candidates/`

`members/guarantor-candidates/` returns the active members who can be named as a
guarantor — a name, an email and a profile id, and nothing else. The loan
application form uses it, so a member never has to be handed the whole roster,
with everybody's employee and payroll numbers, in order to pick one guarantor.

**Contributions** — `contributions/plans/` · `contributions/cycles/` ·
`cycles/{id}/entries/` · `cycles/{id}/confirm/` · `cycles/{id}/penalties/` ·
`contributions/entries/` · `entries/{id}/confirm/` · `contributions/ledger/` ·
`contributions/my/` · `contributions/my/balance/`

**Loans** — `loans/products/` · `loans/applications/` · `applications/{id}/approve/` ·
`applications/{id}/confirm-guarantor/` · `applications/guarantor-requests/` ·
`applications/{id}/guarantee-request/` · `loans/eligibility/` · `loans/quote/` ·
`loans/active/`

**Schedules** — `schedules/` · `schedules/generate/` · `schedules/{id}/export/csv/` ·
`schedules/{id}/export/excel/`

**Reports** — `reports/dashboard/summary/` · `reports/dashboard/contributions_chart/`

**Notifications** — `notifications/` · `notifications/{id}/read/` · `notifications/read-all/`

**Platform (SUPER_ADMIN)** — `platform/tenants/` · `platform/stats/` and per-tenant
`branding/` · `settings/` · `rules/` · `activate/` · `suspend/` · `deactivate/`

The per-tenant `branding/`, `settings/` and `rules/` routes are also readable and
writable by the society's own `SOCIETY_ADMIN` — never by another society's admin.
The platform-only lifecycle actions (`activate/`, `suspend/`, `deactivate/`) stay
`SUPER_ADMIN`.

### Searching

List endpoints for members, tenants, contribution plans, loan products and loan
applications accept `?search=`. Member search covers name, email, employee number
and payroll number; the identifiers are matched against the *current tenant's*
member profile only, so a number issued by another society can never match.

### Who can see what

Role gates are enforced server-side; build the UI to match or you'll render dead buttons.

| Role | Access |
|---|---|
| `MEMBER` | Own contributions, own notifications, and loan applications they submitted **or** guarantee. List endpoints self-filter. No society-wide financials, no loan decisions, and no member records beyond the directory. |
| `COMMITTEE_MEMBER` | Read-only financials and loans: the ledger, cycles and their entries, dashboard reports, loan applications and the member directory. No writes, no loan decisions, and no deduction schedules. |
| `EXECUTIVE` | Financials, contribution confirmation, schedules, loan approvals. |
| `SOCIETY_ADMIN` | Everything above, plus members, roles and society settings — including contribution plans and loan products, which are society configuration. |
| `SUPER_ADMIN` | Cross-tenant platform endpoints. |

Endpoint by endpoint, for a society with one tenant:

| Endpoint | MEMBER | COMMITTEE | EXECUTIVE | SOCIETY_ADMIN |
|---|---|---|---|---|
| `contributions/my/`, `my/balance/`, `notifications/` | own | own | own | own |
| `contributions/cycles/` (list) | yes | yes | yes | yes |
| `contributions/cycles/{id}/entries/`, `/penalties/` | 403 | yes | yes | yes |
| `contributions/ledger/` | 403 | yes | yes | yes |
| `contributions/plans/` (list / write) | list / 403 | list / 403 | list / 403 | yes |
| `contributions/entries/` (list / confirm) | 403 | 403 | yes | yes |
| `contributions/cycles/` (create, confirm) | 403 | 403 | yes | yes |
| `reports/dashboard/summary/`, `contributions_chart/` | 403 | yes | yes | yes |
| `loans/applications/` (list) | own + guaranteed | all | all | all |
| `loans/applications/` (create) | yes | yes | yes | yes |
| `loans/applications/{id}/approve/` | 403 | 403 | yes | yes |
| `loans/applications/{id}/confirm-guarantor/` | own guarantee | own guarantee | yes | yes |
| `loans/products/` (list / write) | list / 403 | list / 403 | list / 403 | yes |
| `loans/quote/`, `loans/eligibility/` | own | all | all | all |
| `loans/active/` | own | all | all | all |
| `members/` (list) | directory | directory | directory | full |
| `members/` (create, role, status, profile) | 403 | 403 | 403 | yes |
| `members/guarantor-candidates/` | yes | yes | yes | yes |
| `schedules/` (list, generate, export) | 403 | 403 | yes | yes |
| `platform/tenants/{id}/` branding · settings · rules | 403 | 403 | 403 | own society only |
| `platform/tenants/` list, create, activate, suspend, deactivate | 403 | 403 | 403 | 403 (`SUPER_ADMIN` only) |

Two gates are in play. Most endpoints check a **role code** (`IsTenantMember`,
`IsExecutiveOrAbove`, `IsSocietyAdmin`). The officer-read endpoints and loan decisions
check a **permission code** instead (`HasTenantPermission`), so the `view_financials`,
`view_reports` and `approve_loans` grants in the role table above are what actually
gates them — and a per-user `UserPermissionOverride` can still allow or deny them.

The member directory is deliberately thinner than the roster. A member may see who is
in their society — that is what naming a guarantor needs — but not anybody else's
employee number, payroll number, date of birth, next-of-kin details or bank
coordinates. `GET /members/` therefore returns the full record only to the role that
manages members, and `GET /members/guarantor-candidates/` returns just a name, an
email and a profile id for the loan application form.


---

## Core flows

**Monthly contribution cycle.** Treasurer opens a cycle → generates entries for every
active member → exports the deduction schedule → bursary deducts from salaries →
treasurer confirms what was received → member ledgers update → penalties apply to anything
missed.

**Loan lifecycle.** Member checks eligibility → applies with guarantors → each guarantor
confirms *in the app* (passive consent is never accepted) → the rule engine evaluates →
auto-approved under the society's threshold, or escalated to executives → a repayment
schedule is generated and rides along on the monthly deduction schedule.

An application whose only outstanding item is guarantor confirmation sits in
`guarantor_pending` — it is **not** rejected. Check `rule_evaluation.blocked_on_guarantors`
to tell the two apart in the UI. `rule_evaluation.rules[]` carries a per-rule
pass/fail with a human-readable message, so you can show a member exactly why they don't
qualify rather than a bare "ineligible".

Guarantors are notified in-app the moment they are named, and can list and act on
their guarantee requests through `applications/guarantor-requests/`. The applicant is
notified when a guarantor responds and when the application is approved or rejected.
Every notification carries `context_data = {"kind": ..., "application_id": ...}` so the
client can deep-link into the right screen.

---

## Interest rates and loan pricing

Nothing about interest is hard-coded to one cooperative. There are two layers, and
the society's layer sits on top of the product's.

### The two layers

**The loan product** (`LoanProduct`) is the per-product rule package. Every society
has its own catalogue — the rows are tenant-scoped, so one cooperative's rate can
never leak into another's. It carries the rate (`interest_rate`, an annual
percentage), the basis (`interest_method`), the term band, the ceiling, the
guarantor count and the auto-approval threshold.

**The rule set** (`TenantRuleSet.rules["loan"]`) is the society-wide policy. It is
versioned, and where it speaks it wins over the product's own setting. The keys the
platform reads are:

| Key | Effect |
|---|---|
| `escalation_threshold` | Overrides the product's `auto_approval_threshold`. Loans above this are always escalated to the executives for manual approval. |
| `default_interest_rate` | Pre-fills the rate on newly created loan products — the society's house rate, set once. |
| `default_interest_method` | `"flat"` or `"reducing"` — pre-fills the basis on newly created loan products. |
| `max_term_months` | A society-wide ceiling on the repayment term. A product may offer less, never more. |

Every key is optional and every value is validated. A typo in the JSON falls back to
the product's own setting rather than breaking a loan application. The `penalty`
section of the rule set is read the same way (`missed_payment_flat`,
`missed_payment_rate`).

### The two bases

`apps/loans/interest.py` is the single calculator. It is pure arithmetic on
`Decimal` — no database, no tenant — so the quote a member sees and the contract
that gets written can never disagree.

**Flat (simple) interest** — interest is charged on the original principal for the
whole term:

```
total_interest = principal × (rate / 100) × term / 12
total_repayable = principal + total_interest
monthly = total_repayable / term
```

Every instalment is identical: `principal / term` of principal and
`total_interest / term` of interest.

**Reducing balance (amortised)** — interest is charged on what is still owed:

```
r = (rate / 100) / 12
payment = principal × r / (1 − (1 + r)^(−term))
```

Instalments are level in total, but the interest inside each one falls as the
principal is repaid. At a zero rate this degrades to the flat case.

**Rounding.** Amounts are quantised to two decimals and the *final* instalment
absorbs the residue, so the instalments always sum exactly to `total_repayable`, the
interest column to the total interest, and the principal column to the principal.
The basis and the rate are snapshotted onto the `Loan` row at approval, so changing a
product later never rewrites a loan that has already been issued.

### Pricing a loan before applying

`POST /api/v1/loans/quote/` prices a loan:

```json
{ "loan_product_id": "<uuid>", "amount": "500000.00", "term_months": 12 }
```

It answers with the principal, the rate, the basis, the total interest, the total
repayable, the monthly instalment and the full instalment schedule. Any member of
the society may call it — it is a quote, not an application. `POST /loans/eligibility/`
accepts the same `amount` and an optional `term_months` and returns the same quote
alongside the rule evaluation, so a screen can ask for both in one round trip.

### Who can change what

| | Read a rate | Change a rate | Publish a rule-set version |
|---|---|---|---|
| `MEMBER` | yes (as a member of the society) | 403 | 403 |
| `COMMITTEE_MEMBER` | yes | 403 | 403 |
| `EXECUTIVE` | yes | 403 | 403 |
| `SOCIETY_ADMIN` | yes | yes | yes, for their own society only |
| `SUPER_ADMIN` | yes | yes | yes, for any society |

Loan products are society configuration, so writing one is a society-admin act —
the same way contribution plans are. The treasurer can see the rate that applies to
every loan and can decide applications against it, but cannot change it.

---

## Local development without Docker

You'll need PostgreSQL and Redis running locally.

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements/dev.txt
cp .env.example .env          # point DATABASE_URL / REDIS_URL at your local services
python manage.py migrate
python manage.py seed_demo
python manage.py runserver
```

Handy commands:

```bash
docker compose logs -f web                    # tail the API
docker compose exec web python manage.py shell
docker compose exec web python manage.py createsuperuser
docker compose down -v                        # reset, including volumes
```

---

## Deploying to Render

The repo is set up for Render's native Python runtime (no Dockerfile needed).

**Service settings**

| Setting | Value |
|---|---|
| Runtime | Python |
| Build command | `pip install -r requirements.txt && python manage.py collectstatic --noinput` |
| Start command | `python manage.py migrate --noinput && gunicorn config.wsgi:application --bind 0.0.0.0:$PORT --workers 3 --timeout 60 --access-logfile - --error-logfile -` |
| Health check path | `/health/` |

`.python-version` pins Python to 3.12. That matters: every pin in
`requirements/base.txt` has a prebuilt manylinux wheel for CPython 3.12, so the
build never needs a C toolchain.

**Environment variables**

| Variable | Required | Notes |
|---|---|---|
| `SECRET_KEY` | yes | No default — the app refuses to start without it. Render can generate one. |
| `DJANGO_ENV` | no | Defaults to `prod` on Render (`RENDER=true`), `dev` everywhere else. |
| `DJANGO_SETTINGS_MODULE` | no | Explicit override; leave unset on Render. |
| `ALLOWED_HOSTS` | no | `*.onrender.com` is added automatically from `RENDER_EXTERNAL_HOSTNAME`; add custom domains here. |
| `CSRF_TRUSTED_ORIGINS` | no | Derived from `ALLOWED_HOSTS`; only needed for extra origins. |
| `CORS_ALLOWED_ORIGINS` | yes | The frontend origin, e.g. `https://acada.vercel.app`. No trailing slash. |
| `DATABASE_URL` | yes | `postgres://…` — Render's *internal* connection string. `sslmode` is honoured if present. |
| `DEBUG` | no | Never set it on Render; the app raises if `DEBUG=True` and `RENDER` is set. |
| `EMAIL_BACKEND` | no | Defaults to the console backend; nothing sends mail yet. |

`config/settings/prod.py` derives `SECURE_PROXY_SSL_HEADER`, HTTPS redirect,
secure cookies, HSTS and `CONN_MAX_AGE` from these. `SECURE_REDIRECT_EXEMPT`
keeps `/health/` reachable over plain HTTP for the platform's health checker.

**Health endpoints**

| Path | Purpose | Touches the database |
|---|---|---|
| `/health/` | liveness — process is up | no |
| `/health/ready/` | readiness — DB reachable (503 when not) | yes |

**What does not survive a restart**

Render's filesystem is ephemeral. `staticfiles/` is regenerated by the build, but
anything written to `media/` (uploaded files) is lost on redeploy. Move media to
S3/Cloudflare R2 before relying on it.

Celery is installed but idle: no `@shared_task` exists yet, so no worker or Redis
instance is required. `django_celery_beat` tables are migrated as part of
`migrate`.

---

## Project layout

```
apps/
  core/           tenants, branding, settings, versioned rule sets
  users/          auth, hybrid RBAC, memberships, member profiles
  contributions/  plans, cycles, entries, penalties, financial ledger
  loans/          products, applications, guarantors, rule engine, repayments
  schedules/      bursary deduction schedule generation + CSV/Excel export
  reports/        dashboard metrics
  notifications/  in-app / email / SMS dispatch records
  auditing/       append-only audit trail
common/           tenant middleware, JWT auth, base models, RBAC permissions
config/           settings (base/dev/prod), URLs, Celery
```

Every tenant-owned model inherits `TenantScopedModel`, which carries a `tenant` FK.
`TenantMiddleware` resolves the tenant before any view runs and
`TenantScopedViewSetMixin` filters querysets to it.

---

## Known gaps

Worth knowing before you build against this.

- **Penalties are re-billed every cycle.** Once `applied`, a penalty stays on every
  subsequent deduction schedule — nothing marks it recovered. Needs a schema decision.
- **A member's balance nets off their loan.** `current_balance` subtracts loan principal
  from savings, so a member who saved ₦150,000 and took an ₦80,000 loan reads ₦70,000.
  Savings and debt should be separate figures. Don't label this "Savings" in the UI yet.
- **Repayment installments aren't tied to a cycle.** The schedule picks the next
  `scheduled` installment by number, ignoring `due_cycle`.
- **The permission layer is only partly wired.** `HasTenantPermission` gates the
  officer-read endpoints (`view_financials`, `view_reports`) and loan decisions
  (`approve_loans`), so per-user `UserPermissionOverride` rows work there. The rest of
  the API still gates on role codes, so the `manage_*` grants are documentation rather
  than enforcement — a SOCIETY_ADMIN-only grant like `manage_roles` is not what stops
  an EXECUTIVE from calling the endpoint.
- **`/api/v1/members/roles/` 404s** — shadowed by the `/members/{pk}/` route. The same
  is true of `/api/v1/members/permissions/`.
- **No test suite yet.**

Phase 1 is backend-only: no bank or payment gateway integration. Money moves through the
bursary. A `BankGateway` abstraction is reserved for Phase 4.
