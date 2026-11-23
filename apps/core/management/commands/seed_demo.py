"""
Seed a working demo tenant so the API can actually be used.

A fresh database has no roles, no tenant and no members. Because Membership
requires a Role and TenantMiddleware requires an active Membership, every
tenant-scoped endpoint returns 400/403 until those rows exist — there is no
way to bootstrap through the API itself.

    python manage.py seed_demo

The command is idempotent: re-running it tops up anything missing rather than
duplicating. Use --reset to delete the demo tenant and rebuild from scratch.
"""
from datetime import date
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

DEFAULT_PASSWORD = "Passw0rd!23"

# The canonical permission catalog from the PRD (section 7.4). The officer-read
# endpoints and loan decisions are gated on these codes; the rest of the API
# still gates on role codes, so the `manage_*` entries are documentation for
# now. See the "Known gaps" section of the README.
PERMISSIONS = [
    ("view_financials", "contributions", "View financial summaries and balances"),
    ("record_contributions", "contributions", "Record and confirm contributions"),
    ("manage_contribution_plans", "contributions", "Create and edit contribution plans"),
    ("apply_penalties", "contributions", "Apply or waive contribution penalties"),
    ("view_loans", "loans", "View loan applications and contracts"),
    ("approve_loans", "loans", "Approve or reject loan applications"),
    ("manage_loan_products", "loans", "Configure loan rule packages"),
    ("prepare_deductions", "schedules", "Generate and export bursary deduction schedules"),
    ("view_reports", "reports", "View and export financial reports"),
    ("manage_members", "users", "Add, approve and suspend members"),
    ("manage_roles", "users", "Assign roles and permission overrides"),
    ("manage_tenant_settings", "core", "Edit society branding, settings and rules"),
]

ROLES = {
    "SUPER_ADMIN": ("Platform Administrator", "platform", [p[0] for p in PERMISSIONS]),
    "SOCIETY_ADMIN": ("President", "tenant", [p[0] for p in PERMISSIONS]),
    "EXECUTIVE": ("Treasurer / Executive", "tenant", [
        "view_financials", "record_contributions", "apply_penalties",
        "view_loans", "approve_loans", "prepare_deductions", "view_reports",
    ]),
    "COMMITTEE_MEMBER": ("Committee Member", "tenant", ["view_financials", "view_loans", "view_reports"]),
    "MEMBER": ("Member", "tenant", []),
}

# (tag, first, last, department, designation)
DEMO_MEMBERS = [
    ("adebayo", "Adebayo", "Ogunlesi", "Physics", "Senior Lecturer"),
    ("chinelo", "Chinelo", "Okafor", "Microbiology", "Reader"),
    ("yusuf", "Yusuf", "Danladi", "Mathematics", "Professor"),
    ("folake", "Folake", "Adeyemi", "Economics", "Lecturer I"),
    ("emeka", "Emeka", "Nwosu", "Computer Science", "Lecturer II"),
    ("hauwa", "Hauwa", "Ibrahim", "Law", "Senior Lecturer"),
]

# A read-only officer. Without an account here the COMMITTEE_MEMBER role
# cannot be tried at all — the role exists, but nothing is ever assigned it.
# (tag, first, last, department, designation)
DEMO_COMMITTEE = [
    ("committee", "Chioma", "Eze", "Accounting", "Lecturer I"),
]


class Command(BaseCommand):
    help = "Seed a demo cooperative society with roles, members, contributions and a loan."

    def add_arguments(self, parser):
        parser.add_argument("--tenant-code", default="acada", help="Tenant slug (default: acada)")
        parser.add_argument("--password", default=DEFAULT_PASSWORD, help="Password for all demo accounts")
        parser.add_argument("--reset", action="store_true", help="Delete the demo tenant first, then rebuild")

    @transaction.atomic
    def handle(self, *args, **options):
        from apps.core.models import Tenant, TenantBranding, TenantRuleSet, TenantSettings
        from apps.users.models import Permission, Role, UserAccount

        code = options["tenant_code"]
        password = options["password"]

        if options["reset"]:
            self._reset(code)

        # ── Permissions ──────────────────────────────────────────────
        perms = {}
        for perm_code, module, description in PERMISSIONS:
            perms[perm_code], _ = Permission.objects.get_or_create(
                code=perm_code, defaults={"module": module, "description": description}
            )
        self.stdout.write(f"Permissions: {len(perms)}")

        # ── Tenant ───────────────────────────────────────────────────
        tenant, created = Tenant.objects.get_or_create(
            code=code,
            defaults={
                "name": "ACADA Cooperative Society",
                "description": "Academic staff cooperative — first tenant on the platform.",
                "status": Tenant.Status.ACTIVE,
                "onboarding_state": Tenant.OnboardingState.ACTIVE,
                "primary_contact_email": f"admin@{code}.demo",
                "institution_name": "University of Ibadan",
                "address": "Staff Secretariat, University of Ibadan, Oyo State",
            },
        )
        TenantBranding.objects.get_or_create(
            tenant=tenant, defaults={"primary_color": "#1a56db", "secondary_color": "#7e3af2"}
        )
        TenantSettings.objects.get_or_create(
            tenant=tenant,
            defaults={"currency": "NGN", "timezone": "Africa/Lagos", "locale": "en-NG"},
        )
        rule_set, _ = TenantRuleSet.objects.get_or_create(
            tenant=tenant,
            version=1,
            defaults={
                "active_from": date(2026, 1, 1),
                "rules": {
                    "penalty": {"missed_payment_flat": "500.00", "missed_payment_rate": "0.00"},
                    "loan": {
                        "escalation_threshold": "100000.00",
                        "default_interest_rate": "5.00",
                        "default_interest_method": "flat",
                        "max_term_months": 36,
                    },
                },
                "notes": "Seeded demo rules.",
            },
        )

        # Idempotent upgrade — an existing rule set keeps whatever the
        # society has configured, but gains the keys the platform now reads.
        rules = dict(rule_set.rules or {})
        loan_rules = dict(rules.get("loan") or {})
        for key, default in (
            ("escalation_threshold", "100000.00"),
            ("default_interest_rate", "5.00"),
            ("default_interest_method", "flat"),
            ("max_term_months", 36),
        ):
            loan_rules.setdefault(key, default)
        if loan_rules != (rules.get("loan") or {}):
            rules["loan"] = loan_rules
            rule_set.rules = rules
            rule_set.save(update_fields=["rules", "updated_at"])
        self.stdout.write(f"Tenant: {tenant.name} ({'created' if created else 'existing'})")

        # ── Roles ────────────────────────────────────────────────────
        roles = {}
        for role_code, (name, scope, perm_codes) in ROLES.items():
            role, _ = Role.objects.get_or_create(
                code=role_code,
                tenant=None if scope == "platform" else tenant,
                defaults={"name": name, "scope": scope},
            )
            role.permissions.set([perms[p] for p in perm_codes])
            roles[role_code] = role
        self.stdout.write(f"Roles: {', '.join(roles)}")

        # ── Accounts ─────────────────────────────────────────────────
        platform_admin = self._make_user(
            f"platform@{code}.demo", "Platform", "Admin", password,
            superuser=True, is_platform_user=True, is_staff=True,
        )
        president = self._make_member(tenant, roles["SOCIETY_ADMIN"], code, password,
                                      "president", "Bolanle", "Ajayi", "Registry", "President")
        treasurer = self._make_member(tenant, roles["EXECUTIVE"], code, password,
                                      "treasurer", "Segun", "Balogun", "Bursary", "Treasurer")
        committee = [
            self._make_member(tenant, roles["COMMITTEE_MEMBER"], code, password,
                              tag, first, last, dept, title)
            for tag, first, last, dept, title in DEMO_COMMITTEE
        ]

        members = [
            self._make_member(tenant, roles["MEMBER"], code, password, tag, first, last, dept, title)
            for tag, first, last, dept, title in DEMO_MEMBERS
        ]
        self.stdout.write(f"Accounts: 1 platform admin, 1 president, 1 treasurer, {len(committee)} committee, {len(members)} members")

        # ── Contribution plan + six months of history ────────────────
        self._seed_contributions(tenant, treasurer.user, members)

        # ── Loan product + one live loan ─────────────────────────────
        self._seed_loan(tenant, members)

        self._report(tenant, code, password, platform_admin, president, treasurer, committee, members)

    # ── helpers ──────────────────────────────────────────────────────

    def _reset(self, code):
        """
        Tear down the demo tenant.

        Membership.role and LoanApplication.loan_product are PROTECT, so the
        tenant cascade cannot reach Role/LoanProduct while those rows exist.
        Clear the protecting rows first, then let the cascade do the rest.
        """
        from apps.core.models import Tenant
        from apps.loans.models import LoanApplication
        from apps.users.models import Membership, UserAccount

        tenant = Tenant.objects.filter(code=code).first()
        if not tenant:
            self.stdout.write(self.style.WARNING(f"No existing tenant '{code}' to reset."))
            return

        LoanApplication.objects.filter(tenant=tenant).delete()
        Membership.objects.filter(tenant=tenant).delete()
        tenant.delete()
        UserAccount.objects.filter(email__endswith=f"@{code}.demo").delete()
        self.stdout.write(self.style.WARNING(f"Deleted existing tenant '{code}' and its demo users."))

    def _make_user(self, email, first, last, password, *, superuser=False, **flags):
        """
        Create (or fetch) a demo account.

        `superuser=True` is used for the platform administrator. Django's
        admin site only shows models a user has permission on, and a plain
        staff account with no model permissions lands on the "You don't have
        permission to view or edit anything" page. The platform operator is
        meant to be able to administer the whole platform, so that account is
        a Django superuser.

        The API is unaffected — its permissions come from the custom
        permission classes, not from Django's `has_perm`.
        """
        from apps.users.models import UserAccount

        if superuser:
            # Fold these into `flags` so they are also re-applied to an
            # account that already exists.
            flags.setdefault("is_superuser", True)
            flags.setdefault("is_staff", True)

        user = UserAccount.objects.filter(email=email).first()
        if user:
            # Re-apply the flags so an account seeded before they were
            # introduced is brought up to date.
            changed = [f for f, v in flags.items() if getattr(user, f) != v]
            for field in changed:
                setattr(user, field, flags[field])
            if changed:
                user.save(update_fields=changed)
            return user

        create = (
            UserAccount.objects.create_superuser
            if superuser
            else UserAccount.objects.create_user
        )
        return create(
            email=email, password=password, first_name=first, last_name=last, **flags
        )

    def _make_member(self, tenant, role, code, password, tag, first, last, department, designation):
        """Create the user, their tenant membership, and their member profile."""
        from apps.users.models import MemberProfile, Membership

        user = self._make_user(f"{tag}@{code}.demo", first, last, password)

        membership, _ = Membership.objects.get_or_create(
            tenant=tenant, user=user,
            defaults={
                "role": role,
                "status": Membership.Status.ACTIVE,
                "approved_at": timezone.now(),
            },
        )
        # Re-apply the role and status, so re-seeding a database that was
        # seeded before a role change actually moves the account.
        if membership.role_id != role.id or membership.status != Membership.Status.ACTIVE:
            membership.role = role
            membership.status = Membership.Status.ACTIVE
            membership.approved_at = membership.approved_at or timezone.now()
            membership.save(update_fields=["role", "status", "approved_at", "updated_at"])
        profile, _ = MemberProfile.objects.get_or_create(
            tenant=tenant, user=user,
            defaults={
                "employee_no": f"EMP{abs(hash(tag)) % 90000 + 10000}",
                "payroll_no": f"PR{abs(hash(tag)) % 90000 + 10000}",
                "department": department,
                "designation": designation,
                "employment_status": MemberProfile.EmploymentStatus.ACTIVE,
                "joined_at": date(2024, 1, 15),
            },
        )
        return profile

    def _seed_contributions(self, tenant, confirmed_by, members):
        from apps.contributions.models import (
            ContributionCycle, ContributionEntry, ContributionPlan, PenaltyEntry,
        )
        from apps.contributions.services import (
            apply_penalty, confirm_contribution, generate_cycle_entries,
        )

        ContributionPlan.objects.get_or_create(
            tenant=tenant, plan_name="Standard Monthly",
            defaults={
                "amount_fixed": Decimal("25000.00"),
                "allows_extra": True,
                "is_default": True,
                "effective_from": date(2024, 1, 1),
                "description": "Fixed monthly salary deduction.",
            },
        )

        # Six closed months of history, plus the current month left open.
        for month in range(1, 7):
            cycle, created = ContributionCycle.objects.get_or_create(
                tenant=tenant, cycle_month=month, cycle_year=2026,
                defaults={"status": ContributionCycle.Status.CLOSED, "generated_at": timezone.now()},
            )
            if not created:
                continue

            generate_cycle_entries(cycle)

            for entry in ContributionEntry.objects.filter(tenant=tenant, cycle=cycle):
                # One member misses June so there is a penalty to look at.
                if month == 6 and entry.member_profile_id == members[-1].id:
                    confirm_contribution(entry, Decimal("0.00"), confirmed_by, f"BURSARY-2026-{month:02d}")
                    apply_penalty(
                        member_profile=entry.member_profile, cycle=cycle,
                        penalty_type=PenaltyEntry.PenaltyType.MISSED_PAYMENT,
                        amount=Decimal("500.00"),
                        reason=f"Missed deduction for {cycle.period_display}",
                    )
                else:
                    confirm_contribution(
                        entry, entry.amount_due, confirmed_by, f"BURSARY-2026-{month:02d}"
                    )

        ContributionCycle.objects.get_or_create(
            tenant=tenant, cycle_month=7, cycle_year=2026,
            defaults={"status": ContributionCycle.Status.OPEN},
        )
        self.stdout.write("Contributions: 6 closed cycles + 1 open, 1 missed payment with penalty")

    def _seed_loan(self, tenant, members):
        from apps.loans.engine import LoanApprovalEngine, LoanEligibilityEngine
        from apps.loans.models import InterestMethod, LoanApplication, LoanGuarantor, LoanProduct

        product, _ = LoanProduct.objects.get_or_create(
            tenant=tenant, name="Standard Loan",
            defaults={
                "description": "General purpose loan for members in good standing.",
                "min_membership_months": 6,
                "min_contribution_months": 6,
                "guarantor_required_count": 2,
                "max_amount": Decimal("500000.00"),
                "max_multiplier": Decimal("2.00"),
                "interest_rate": Decimal("5.00"),
                "rate_period": "annual",
                "interest_method": InterestMethod.FLAT,
                "max_term_months": 24,
                "auto_approval_threshold": Decimal("100000.00"),
            },
        )

        # A second product on the other interest basis, so a society can see
        # both calculations side by side.
        LoanProduct.objects.get_or_create(
            tenant=tenant, name="Salary Advance",
            defaults={
                "description": "Short-term advance on the next salary, repaid on a reducing balance.",
                "min_membership_months": 6,
                "min_contribution_months": 3,
                "guarantor_required_count": 1,
                "max_amount": Decimal("300000.00"),
                "max_multiplier": Decimal("1.50"),
                "interest_rate": Decimal("4.00"),
                "rate_period": "annual",
                "interest_method": InterestMethod.REDUCING,
                "max_term_months": 12,
                "auto_approval_threshold": Decimal("50000.00"),
            },
        )

        applicant, g1, g2 = members[0], members[1], members[2]
        if LoanApplication.objects.filter(tenant=tenant, member_profile=applicant).exists():
            self.stdout.write("Loans: existing application found, skipped")
            return

        application = LoanApplication.objects.create(
            tenant=tenant, member_profile=applicant, loan_product=product,
            amount_requested=Decimal("80000.00"),
            purpose="School fees for the 2026 session",
            term_months=12,
            status=LoanApplication.Status.SUBMITTED,
            submitted_at=timezone.now(),
        )
        for guarantor in (g1, g2):
            LoanGuarantor.objects.create(
                tenant=tenant, application=application, guarantor_member=guarantor,
                status=LoanGuarantor.Status.CONFIRMED, confirmed_at=timezone.now(),
            )

        engine = LoanEligibilityEngine(applicant, product, application=application)
        result = engine.evaluate(application.amount_requested)
        application.rule_evaluation = result.to_dict()
        application.evaluated_at = timezone.now()
        application.save()

        if result.eligible and result.approval_mode == "auto":
            loan = LoanApprovalEngine.auto_approve(application)
            self.stdout.write(
                f"Loans: 1 active loan ₦{loan.approved_amount:,.2f} over {loan.term_months} months"
            )
        else:
            self.stdout.write(self.style.WARNING(f"Loans: application not auto-approved — {result.message}"))

    def _report(self, tenant, code, password, platform_admin, president, treasurer, committee, members):
        line = "─" * 62
        self.stdout.write("\n" + line)
        self.stdout.write(self.style.SUCCESS("  Demo data ready"))
        self.stdout.write(line)
        self.stdout.write(f"  Tenant code (send as tenant_code on login):  {code}")
        self.stdout.write(f"  Password for every account below:            {password}\n")
        self.stdout.write(f"  Platform admin  {platform_admin.email}   (Django admin, /api/v1/platform/)")
        self.stdout.write(f"  President       {president.user.email}   (SOCIETY_ADMIN)")
        self.stdout.write(f"  Treasurer       {treasurer.user.email}   (EXECUTIVE)")
        for profile in committee:
            self.stdout.write(f"  Committee       {profile.user.email}   (COMMITTEE_MEMBER, read-only)")
        for profile in members:
            self.stdout.write(f"  Member          {profile.user.email}")
        self.stdout.write("\n  Log in with:")
        self.stdout.write("    POST /api/v1/auth/login/")
        self.stdout.write(
            '    {"email": "%s", "password": "%s", "tenant_code": "%s"}'
            % (treasurer.user.email, password, code)
        )
        self.stdout.write(line + "\n")
