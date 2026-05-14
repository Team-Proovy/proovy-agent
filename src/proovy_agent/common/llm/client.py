"""ChatOpenRouter LLM client singleton."""

from langchain_openrouter import ChatOpenRouter

from proovy_agent.common.config import get_settings

MODEL_MAP: dict[str, str] = {
    "flash": "google/gemini-2.0-flash-001",
    "sonnet": "anthropic/claude-sonnet-4-5",
    "opus": "anthropic/claude-opus-4-5",
}

_cache: dict[str, ChatOpenRouter] = {}


def get_llm(model: str) -> ChatOpenRouter:
    """Return a cached ChatOpenRouter instance for the given model alias."""
    if model not in MODEL_MAP:
        raise ValueError(f"Unknown model alias '{model}'. Choose from: {list(MODEL_MAP)}")

    if model in _cache:
        return _cache[model]

    settings = get_settings()
    if not settings.openrouter_api_key:
        raise ValueError("OPENROUTER_API_KEY is not set")

    _cache[model] = ChatOpenRouter(
        model=MODEL_MAP[model],
        api_key=settings.openrouter_api_key,
    )
    return _cache[model]
