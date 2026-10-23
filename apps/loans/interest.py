"""
Loan interest calculation.

Two bases are supported, and each cooperative picks one per loan product:

``flat``
    Simple interest charged on the *original* principal for the whole term.
    Every instalment is identical: ``principal / term + interest / term``.

``reducing``
    Interest is charged on the *outstanding* balance, which falls as the
    principal is repaid — the amortising (annuity) basis. Instalments are
    level in total, but the interest inside each one shrinks over time.

Everything in this module is pure arithmetic on ``Decimal`` — no database,
no tenant, no request state. That is deliberate: the very same function
answers the pre-application quote a member sees while filling in the form
and the contract that is written when the loan is approved, so the two can
never disagree.

Rounding: amounts are quantised to two decimal places, and the *final*
instalment absorbs the residue. The instalments therefore always sum exactly
to ``total_repayable`` — no loose kobo left over.
"""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import List

CENT = Decimal("0.01")

FLAT = "flat"
REDUCING = "reducing"
INTEREST_METHODS = (FLAT, REDUCING)

METHOD_LABELS = {
    FLAT: "Flat (simple) interest",
    REDUCING: "Reducing balance (amortised)",
}


class InterestCalculationError(ValueError):
    """Raised when a quote cannot be produced from the given inputs."""


@dataclass(frozen=True)
class Installment:
    """One repayment instalment."""

    installment_no: int
    principal_component: Decimal
    interest_component: Decimal
    amount_due: Decimal


@dataclass(frozen=True)
class RepaymentQuote:
    """The full cost of a loan — what the member will repay."""

    principal: Decimal
    annual_rate: Decimal
    term_months: int
    method: str
    total_interest: Decimal
    total_repayable: Decimal
    monthly_installment: Decimal
    installments: List[Installment]

    @property
    def method_label(self) -> str:
        return METHOD_LABELS.get(self.method, self.method)

    def to_dict(self) -> dict:
        """A JSON-ready representation — all money as strings, never floats."""
        return {
            "principal": f"{self.principal:.2f}",
            "annual_rate": f"{self.annual_rate:.2f}",
            "term_months": self.term_months,
            "interest_method": self.method,
            "interest_method_label": self.method_label,
            "total_interest": f"{self.total_interest:.2f}",
            "total_repayable": f"{self.total_repayable:.2f}",
            "monthly_installment": f"{self.monthly_installment:.2f}",
            "schedule": [
                {
                    "installment_no": i.installment_no,
                    "principal_component": f"{i.principal_component:.2f}",
                    "interest_component": f"{i.interest_component:.2f}",
                    "amount_due": f"{i.amount_due:.2f}",
                }
                for i in self.installments
            ],
        }


def _to_decimal(value) -> Decimal:
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InterestCalculationError(f"'{value}' is not a number.") from exc


def _quantize(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _build_schedule(
    principal: Decimal,
    total_interest: Decimal,
    amount_parts: List[Decimal],
    interest_parts: List[Decimal],
) -> List[Installment]:
    """
    Turn exact components into a two-decimal schedule.

    The instalment *total* is the thing a member pays, so it is rounded
    first; the interest inside it is rounded next; the principal is whatever
    is left. Every instalment except the last is rounded on its own, and the
    last one absorbs whatever residue that left behind — so the instalments
    sum exactly to the total repayable, the interest column sums to the
    total interest, and the principal column sums to the principal.
    """
    term = len(amount_parts)
    total_repayable = principal + total_interest

    amount_rounded: List[Decimal] = []
    interest_rounded: List[Decimal] = []

    for i in range(term - 1):
        amount_rounded.append(_quantize(amount_parts[i]))
        interest_rounded.append(_quantize(interest_parts[i]))

    amount_rounded.append(total_repayable - sum(amount_rounded, Decimal("0")))
    interest_rounded.append(total_interest - sum(interest_rounded, Decimal("0")))

    installments = []
    for i in range(term):
        amount = amount_rounded[i]
        interest = interest_rounded[i]
        installments.append(
            Installment(
                installment_no=i + 1,
                principal_component=amount - interest,
                interest_component=interest,
                amount_due=amount,
            )
        )

    return installments


def _flat_components(
    principal: Decimal, annual_rate: Decimal, term: int
):
    """Simple interest on the original principal, split evenly over the term."""
    rate = annual_rate / Decimal("100")
    total_interest = _quantize(principal * rate * Decimal(term) / Decimal("12"))
    total_repayable = principal + total_interest

    # Every instalment is the same: the loan divided by the term, interest
    # included.
    instalment = total_repayable / Decimal(term)
    amount_parts = [instalment] * term
    interest_parts = [total_interest / Decimal(term)] * term

    return total_interest, total_repayable, _quantize(instalment), amount_parts, interest_parts


def _reducing_components(
    principal: Decimal, annual_rate: Decimal, term: int
):
    """Interest on the falling balance — the level-payment (annuity) basis."""
    monthly_rate = annual_rate / Decimal("100") / Decimal("12")

    if monthly_rate == 0:
        payment = principal / Decimal(term)
    else:
        payment = principal * monthly_rate / (1 - (1 + monthly_rate) ** -term)

    balance = principal
    amount_parts: List[Decimal] = []
    interest_parts: List[Decimal] = []

    for i in range(1, term + 1):
        interest = balance * monthly_rate
        if i == term:
            # The final instalment clears whatever balance is left.
            principal_part = balance
        else:
            principal_part = payment - interest
        amount_parts.append(principal_part + interest)
        interest_parts.append(interest)
        balance -= principal_part

    total_interest = _quantize(sum(interest_parts, Decimal("0")))
    total_repayable = principal + total_interest

    return total_interest, total_repayable, _quantize(payment), amount_parts, interest_parts


def calculate_repayment(
    principal,
    annual_rate,
    term_months,
    method: str = FLAT,
) -> RepaymentQuote:
    """
    Price a loan.

    `principal`   — the amount borrowed.
    `annual_rate` — the annual interest rate as a percentage (5.00 = 5%).
    `term_months` — the repayment term in months.
    `method`      — ``flat`` or ``reducing``.
    """
    principal = _to_decimal(principal)
    annual_rate = _to_decimal(annual_rate)
    term = int(term_months)

    if principal <= 0:
        raise InterestCalculationError("The loan amount must be greater than zero.")
    if term < 1:
        raise InterestCalculationError("The repayment term must be at least one month.")
    if annual_rate < 0:
        raise InterestCalculationError("The interest rate cannot be negative.")
    if method not in INTEREST_METHODS:
        raise InterestCalculationError(
            f"Unknown interest method '{method}'. Use one of: {', '.join(INTEREST_METHODS)}."
        )

    if method == REDUCING:
        total_interest, total_repayable, monthly, p_parts, i_parts = _reducing_components(
            principal, annual_rate, term
        )
    else:
        total_interest, total_repayable, monthly, p_parts, i_parts = _flat_components(
            principal, annual_rate, term
        )

    installments = _build_schedule(principal, total_interest, p_parts, i_parts)

    return RepaymentQuote(
        principal=principal,
        annual_rate=annual_rate,
        term_months=term,
        method=method,
        total_interest=total_interest,
        total_repayable=total_repayable,
        monthly_installment=monthly,
        installments=installments,
    )
