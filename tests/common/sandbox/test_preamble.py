"""Sandbox preamble tests."""

import pytest

from proovy_agent.common.sandbox.preamble import get_whitelisted_preamble


def test_get_whitelisted_preamble_returns_math_v1() -> None:
    """Known preamble names return whitelisted code."""
    preamble = get_whitelisted_preamble("math_v1")

    assert preamble == "import sympy\nimport numpy as np\nimport scipy\n"


def test_get_whitelisted_preamble_rejects_unknown_name() -> None:
    """Unknown preamble names are rejected."""
    with pytest.raises(ValueError, match=r"Unknown preamble.*math_v1"):
        get_whitelisted_preamble("not_allowed")
