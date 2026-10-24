from langchain_openai import ChatOpenAI

from atlas.config import Settings


class MissingKeyError(RuntimeError):
    pass


def build_chat_model(settings: Settings) -> ChatOpenAI:
    if settings.openrouter_api_key is None:
        raise MissingKeyError("OPENROUTER_API_KEY is not set. Add it to .env (see .env.example).")
    return ChatOpenAI(
        model=settings.atlas_model,
        api_key=settings.openrouter_api_key,
        base_url=settings.openrouter_base_url,
        temperature=0,
        max_retries=2,
        max_tokens=settings.atlas_max_output_tokens,
        default_headers={"X-Title": "Atlas"},
    )
