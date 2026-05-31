"""Pydantic contracts for the unified credit ledger."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator

from proovy_agent.features.credits.exceptions import InvalidCreditAmountError

CreditAmount = Decimal | int | str
RefundSkipReason = Literal["already_refunded", "succeeded", "missing_target"]


def normalize_credit_amount(value: CreditAmount, *, allow_zero: bool = False) -> Decimal:
    """Normalize external credit values into finite non-negative Decimal values."""
    amount = value if isinstance(value, Decimal) else Decimal(str(value))
    if not amount.is_finite():
        raise InvalidCreditAmountError("credit amount must be finite")
    if amount < 0 or (amount == 0 and not allow_zero):
        operator = "non-negative" if allow_zero else "positive"
        raise InvalidCreditAmountError(f"credit amount must be {operator}: {amount}")
    return amount


class _CreditBaseModel(BaseModel):
    """Base config shared by credit domain models."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class CreditHoldStatus(StrEnum):
    """Persisted status values for a plan-level credit hold."""

    PENDING = "pending"
    CAPTURED = "captured"
    RELEASED = "released"


class CreditBalance(_CreditBaseModel):
    """Current balance and active hold summary for one user."""

    user_id: str
    balance: Decimal
    active_hold_amount: Decimal = Decimal("0")

    @field_validator("balance", "active_hold_amount")
    @classmethod
    def amounts_must_be_finite(cls, value: Decimal) -> Decimal:
        if not value.is_finite():
            raise ValueError("credit amount must be finite")
        return value

    @computed_field
    @property
    def available(self) -> Decimal:
        """Balance available after pending, unexpired holds are subtracted."""
        return self.balance - self.active_hold_amount


class CreditHold(_CreditBaseModel):
    """A single plan-level hold row."""

    id: UUID
    user_id: str
    amount: Decimal = Field(ge=0)
    status: CreditHoldStatus
    created_at: datetime
    expires_at: datetime
    plan_id: str | None = None


class CreditRefundResult(_CreditBaseModel):
    """Result of an idempotent refund attempt."""

    applied: bool
    user_id: str | None = None
    amount: Decimal = Decimal("0")
    skipped_reason: RefundSkipReason | None = None
