"""Credit ledger domain exceptions."""

from decimal import Decimal
from uuid import UUID


class CreditLedgerError(Exception):
    """Base class for credit ledger failures."""


class InvalidCreditAmountError(ValueError):
    """Raised when a credit amount is negative, zero where disallowed, or non-finite."""


class CreditAccountNotFoundError(CreditLedgerError):
    """Raised when a credit account row does not exist."""

    def __init__(self, user_id: str) -> None:
        super().__init__(f"credit account not found: {user_id}")
        self.user_id = user_id


class InsufficientCreditsError(CreditLedgerError):
    """Raised when an all-or-nothing hold cannot be reserved."""

    def __init__(self, *, user_id: str, required: Decimal, available: Decimal) -> None:
        super().__init__(
            f"insufficient credits for {user_id}: required={required}, available={available}"
        )
        self.user_id = user_id
        self.required = required
        self.available = available


class CreditHoldNotFoundError(CreditLedgerError):
    """Raised when a hold row cannot be found for the requested user."""

    def __init__(self, hold_id: UUID, user_id: str) -> None:
        super().__init__(f"credit hold not found: hold_id={hold_id}, user_id={user_id}")
        self.hold_id = hold_id
        self.user_id = user_id


class CreditHoldNotPendingError(CreditLedgerError):
    """Raised when a capture/release targets a hold that is no longer pending."""

    def __init__(self, hold_id: UUID, status: str) -> None:
        super().__init__(f"credit hold is not pending: hold_id={hold_id}, status={status}")
        self.hold_id = hold_id
        self.status = status


class CreditHoldExpiredError(CreditLedgerError):
    """Raised when code attempts to capture a hold after its TTL has elapsed."""

    def __init__(self, hold_id: UUID) -> None:
        super().__init__(f"credit hold has expired: hold_id={hold_id}")
        self.hold_id = hold_id


class CreditHoldAmountExceededError(CreditLedgerError):
    """Raised when a partial capture exceeds the remaining held amount."""

    def __init__(self, *, hold_id: UUID, requested: Decimal, remaining: Decimal) -> None:
        super().__init__(
            f"credit hold amount exceeded: hold_id={hold_id}, "
            f"requested={requested}, remaining={remaining}"
        )
        self.hold_id = hold_id
        self.requested = requested
        self.remaining = remaining
