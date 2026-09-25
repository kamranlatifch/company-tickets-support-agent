"""The one LLM (via OpenRouter) that both agents share.

`get_model()` returns a model that is private to the calling thread. PydanticAI's `run_sync`
runs each call on the calling thread's own asyncio event loop, and an HTTP connection pool is
bound to the loop that opened its connections. One shared client used from several threads at
once (Streamlit runs each customer session in its own thread) therefore fails intermittently with
"bound to a different event loop" / "Connection error" (~2% of concurrent calls in testing).
A client per thread never shares connections across loops.
"""

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
