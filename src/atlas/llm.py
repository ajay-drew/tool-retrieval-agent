from collections.abc import Callable

from langchain_core.language_models import BaseChatModel

from atlas.config import Settings

DAILY_QUOTA_MARKERS = ("PerDay", "per day")


class MissingKeyError(RuntimeError):
    pass


def _gemini(settings: Settings) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.atlas_model,
        google_api_key=settings.llm_api_key,
        temperature=0,
        max_output_tokens=settings.atlas_max_output_tokens,
        max_retries=0,
        timeout=120,
    )


def _openai_compatible(settings: Settings) -> BaseChatModel:
    from langchain_openai import ChatOpenAI

    extra = {"reasoning_effort": settings.atlas_reasoning_effort}
    return ChatOpenAI(
        model=settings.atlas_model,
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        temperature=0,
        max_retries=0,
        max_tokens=settings.atlas_max_output_tokens,
        timeout=120,
        **{k: v for k, v in extra.items() if v},
    )


PROVIDERS: dict[str, Callable[[Settings], BaseChatModel]] = {
    "gemini": _gemini,
    "openai": _openai_compatible,
}


def build_chat_model(settings: Settings) -> BaseChatModel:
    if settings.llm_api_key is None:
        raise MissingKeyError("LLM_API_KEY is not set. Add it to .env (see .env.example).")
    if settings.atlas_llm_provider not in PROVIDERS:
        known = ", ".join(PROVIDERS)
        raise ValueError(f"ATLAS_LLM_PROVIDER must be one of {known}")
    return PROVIDERS[settings.atlas_llm_provider](settings)


def is_retryable_model_error(exc: BaseException) -> bool:
    """Retry rate limits and server errors, but never a daily quota: waiting won't clear it."""
    text = f"{type(exc).__name__} {exc}"
    if any(marker in text for marker in DAILY_QUOTA_MARKERS):
        return False
    status = getattr(exc, "status_code", None) or getattr(exc, "code", None)
    if status in (429, 500, 502, 503, 504):
        return True
    return any(word in text for word in ("RateLimit", "RESOURCE_EXHAUSTED", "ServiceUnavailable"))
