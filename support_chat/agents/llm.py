import threading

from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from support_chat.config import API_KEY, BASE_URL, MODEL

if not API_KEY:
    raise SystemExit("Set COGENT_OPRNROUTER_KEY in .env")

_local = threading.local()


def get_model() -> OpenAIChatModel:
    model = getattr(_local, "model", None)
    if model is None:
        model = _local.model = OpenAIChatModel(
            MODEL,
            provider=OpenAIProvider(base_url=BASE_URL, api_key=API_KEY),
        )
    return model
