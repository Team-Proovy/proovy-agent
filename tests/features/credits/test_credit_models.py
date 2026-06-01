"""Credit ledger contract model tests."""

from decimal import Decimal

import pytest

from proovy_agent.features.credits import CreditBalance, InvalidCreditAmountError
from proovy_agent.features.credits.models import normalize_credit_amount


def test_credit_balance_available_subtracts_active_holds() -> None:
    balance = CreditBalance(
        user_id="user-1",
        balance=Decimal("25"),
        active_hold_amount=Decimal("7.5"),
    )

    assert balance.available == Decimal("17.5")


@pytest.mark.parametrize("value", ["0", "-1", "NaN", "Infinity"])
def test_normalize_credit_amount_rejects_invalid_positive_amounts(value: str) -> None:
    with pytest.raises(InvalidCreditAmountError):
        normalize_credit_amount(value)


def test_normalize_credit_amount_allows_zero_when_requested() -> None:
    assert normalize_credit_amount("0", allow_zero=True) == Decimal("0")
