# Cooperative Management SaaS Platform

Multi-tenant backend for cooperative societies that run on **salary source deduction**.
Contributions and loan repayments are deducted at the institution's payroll (bursary)
office, not collected through the app. The platform's job is to keep the records,
generate the deduction schedules, and enforce the rules.

ACADA Cooperative Society is tenant #1, not a special case — every society is a tenant.

**Stack:** Django 5.1 · Django REST Framework · PostgreSQL 16 · Redis · Celery

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
six members, six closed contribution cycles (one with a missed payment and a penalty),
a loan product, and one active loan with a repayment schedule.

**Demo accounts** — password `Passw0rd!23`, tenant code `acada`:

| Email | Role | Sees |
|---|---|---|
| `platform@acada.demo` | SUPER_ADMIN | Django admin, `/api/v1/platform/` |
| `president@acada.demo` | SOCIETY_ADMIN | everything in the society |
| `treasurer@acada.demo` | EXECUTIVE | financials, schedules, loan approvals |
| `adebayo@acada.demo` | MEMBER | own contributions + the active loan |
| `chinelo@acada.demo` … `hauwa@acada.demo` | MEMBER | own records only |

---

## Authentication

JWT (`Bearer`). Access tokens last 30 minutes; refresh tokens 7 days and rotate on use.

**`tenant_code` is required at login for non-platform users.** It is what binds the token
to a society — a user can belong to several.

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
| 400 `Tenant context required` | Token has no tenant claim — you logged in without `tenant_code` |
| 403 `Access denied` | Valid token, but no active membership in that society |
| 403 `Tenant inactive` | The society is suspended or deactivated |

---

## API surface

All routes are under `/api/v1/`. Lists are paginated (`?page=`, `?page_size=`).

**Auth** — `login/` · `refresh/` · `logout/` · `register/` · `me/` · `password/change/`

**Members** — `members/` · `members/{id}/` · `members/{id}/profile/` · `members/{id}/role/` ·
`members/{id}/status/` · `members/pending/`

**Contributions** — `contributions/plans/` · `contributions/cycles/` ·
`cycles/{id}/entries/` · `cycles/{id}/confirm/` · `cycles/{id}/penalties/` ·
`contributions/entries/` · `entries/{id}/confirm/` · `contributions/ledger/` ·
`contributions/my/` · `contributions/my/balance/`

**Loans** — `loans/products/` · `loans/applications/` · `applications/{id}/approve/` ·
`applications/{id}/confirm-guarantor/` · `loans/eligibility/` · `loans/active/`

**Schedules** — `schedules/` · `schedules/generate/` · `schedules/{id}/export/csv/` ·
`schedules/{id}/export/excel/`

**Reports** — `reports/dashboard/summary/` · `reports/dashboard/contributions_chart/`

**Notifications** — `notifications/` · `notifications/{id}/read/` · `notifications/read-all/`

**Platform (SUPER_ADMIN)** — `platform/tenants/` · `platform/stats/` and per-tenant
`branding/` · `settings/` · `rules/` · `activate/` · `suspend/` · `deactivate/`

### Who can see what

Role gates are enforced server-side; build the UI to match or you'll render dead buttons.

| Role | Access |
|---|---|
| `MEMBER` | Own contributions, own loans, own notifications. List endpoints self-filter. |
| `COMMITTEE_MEMBER` | Read-only financials and loans |
| `EXECUTIVE` | Financials, contribution confirmation, schedules, loan approvals |
| `SOCIETY_ADMIN` | Everything above, plus members, roles and society settings |
| `SUPER_ADMIN` | Cross-tenant platform endpoints |

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
- **Rounding residue on loans.** Installments are rounded individually, so they don't
  always sum to `total_repayable`. The final installment doesn't absorb the difference.
- **`/api/v1/members/roles/` 404s** — shadowed by the `/members/{pk}/` route.
- **No test suite yet.**

Phase 1 is backend-only: no bank or payment gateway integration. Money moves through the
bursary. A `BankGateway` abstraction is reserved for Phase 4.
