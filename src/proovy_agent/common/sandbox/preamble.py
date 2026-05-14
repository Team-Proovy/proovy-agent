"""Whitelisted sandbox preambles."""

_PREAMBLE_REGISTRY: dict[str, str] = {
    "math_v1": "import sympy\nimport numpy as np\nimport scipy\n",
}


def get_whitelisted_preamble(name: str) -> str:
    """Return a whitelisted preamble by name."""
    if name not in _PREAMBLE_REGISTRY:
        raise ValueError(f"Unknown preamble: {name!r}. Available: {list(_PREAMBLE_REGISTRY)}")
    return _PREAMBLE_REGISTRY[name]
