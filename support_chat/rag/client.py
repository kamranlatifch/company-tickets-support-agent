from openai import OpenAI

from support_chat.config import API_KEY, BASE_URL, EMBED_MODEL, MODEL

if not API_KEY:
    raise SystemExit("Set COGENT_OPRNROUTER_KEY in .env")

client = OpenAI(base_url=BASE_URL, api_key=API_KEY)


def embed_texts(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBED_MODEL, input=texts)
    ordered = sorted(response.data, key=lambda item: item.index)
    return [item.embedding for item in ordered]


def embed_query(text: str) -> list[float]:
    return embed_texts([text])[0]


def chat(messages, temperature: float = 0.3, max_tokens: int = 600) -> str:
    response = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    return (response.choices[0].message.content or "").strip()


def chat_stream(messages, temperature: float = 0.3, max_tokens: int = 600):
    stream = client.chat.completions.create(
        model=MODEL,
        messages=messages,
        temperature=temperature,
        max_tokens=max_tokens,
        stream=True,
    )
    for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
