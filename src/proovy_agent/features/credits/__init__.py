"""Unified credit ledger domain."""

from proovy_agent.features.credits.exceptions import (
    CreditAccountNotFoundError,
    CreditHoldAmountExceededError,
    CreditHoldExpiredError,
    CreditHoldNotFoundError,
    CreditHoldNotPendingError,
    CreditLedgerError,
    InsufficientCreditsError,
    InvalidCreditAmountError,
)
from proovy_agent.features.credits.ledger import CreditLedger
from proovy_agent.features.credits.models import (
    CreditBalance,
    CreditHold,
    CreditHoldStatus,
    CreditRefundResult,
    normalize_credit_amount,
)
from proovy_agent.features.credits.schema import setup_credit_ledger
from proovy_agent.features.credits.service import (
    CreditLedgerClient,
    PostgresCreditLedgerClient,
    create_credit_ledger_client,
    open_credit_ledger_client,
)

__all__ = [
    "CreditAccountNotFoundError",
    "CreditBalance",
    "CreditHold",
    "CreditHoldAmountExceededError",
    "CreditHoldExpiredError",
    "CreditHoldNotFoundError",
    "CreditHoldNotPendingError",
    "CreditHoldStatus",
    "CreditLedger",
    "CreditLedgerClient",
    "CreditLedgerError",
    "CreditRefundResult",
    "InsufficientCreditsError",
    "InvalidCreditAmountError",
    "PostgresCreditLedgerClient",
    "create_credit_ledger_client",
    "normalize_credit_amount",
    "open_credit_ledger_client",
    "setup_credit_ledger",
]
