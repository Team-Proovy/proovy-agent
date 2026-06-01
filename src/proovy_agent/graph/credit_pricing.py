"""Credit pricing helpers for graph hold and settlement."""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from collections.abc import Iterable

    from proovy_agent.graph.state import CreditEntry, PlanStep

MODEL_CREDIT_COST: dict[str, Decimal] = {
    "flash": Decimal("1"),
    "sonnet": Decimal("3"),
    "opus": Decimal("8"),
}
GENERAL_CHAT_COST = Decimal("0.5")
CODE_GENERATE_COST = Decimal("1")
CODE_EXECUTE_COST = Decimal("1")
PDF_COST = Decimal("1")
IMAGE_COST = Decimal("2")
VIDEO_FLAT_COST = Decimal("10")


def _as_credit_amount(value: float | int | str | Decimal) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def credit_log_amount(entries: Iterable[CreditEntry]) -> Decimal:
    """Return the decimal sum of credit log costs."""
    return sum((_as_credit_amount(entry.cost) for entry in entries), Decimal("0"))


def estimate_plan_hold_amount(
    plan: Iterable[PlanStep],
    *,
    selected_model: str,
    explanation_mode: Literal["full", "brief"],
    accrued_log: Iterable[CreditEntry] = (),
) -> Decimal:
    """Estimate the plan-level hold amount before execution starts."""
    amount = credit_log_amount(accrued_log)
    for step in plan:
        if step.action == "solve":
            amount += _estimate_solve_cost(selected_model, explanation_mode)
        elif step.action == "pdf":
            amount += PDF_COST
        elif step.action == "video":
            amount += VIDEO_FLAT_COST
    return amount


def synchronous_credit_amount(entries: Iterable[CreditEntry]) -> Decimal:
    """Return costs captured by CreditSettler.

    Video charges are captured in VideoNode in Phase B and intentionally excluded
    from the graph-end synchronous capture path.
    """
    return credit_log_amount(entry for entry in entries if entry.node != "video_node")


def format_credit_amount(amount: Decimal) -> str:
    """Format a Decimal credit value for user-facing short messages."""
    normalized = amount.normalize()
    text = format(normalized, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _estimate_solve_cost(
    selected_model: str,
    explanation_mode: Literal["full", "brief"],
) -> Decimal:
    model_cost = MODEL_CREDIT_COST.get(selected_model, MODEL_CREDIT_COST["flash"])
    llm_call_count = Decimal("1") + (Decimal("1") if explanation_mode == "full" else Decimal("0"))
    return (model_cost * llm_call_count) + CODE_GENERATE_COST + CODE_EXECUTE_COST
