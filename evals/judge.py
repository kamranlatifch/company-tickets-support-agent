import json
import os
import re

from deepeval.models import DeepEvalBaseLLM
from openai import AsyncOpenAI, OpenAI
from pydantic import BaseModel

from support_chat.config import API_KEY, BASE_URL

JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "anthropic/claude-haiku-4.5")


def _parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


class OpenRouterJudge(DeepEvalBaseLLM):
    def __init__(self, model: str = JUDGE_MODEL):
        self.model_id = model
        self.client = OpenAI(base_url=BASE_URL, api_key=API_KEY)
        self.async_client = AsyncOpenAI(base_url=BASE_URL, api_key=API_KEY)
        super().__init__(model)

    def load_model(self):
        return self.client

    def get_model_name(self) -> str:
        return self.model_id

    def _request(self, prompt: str, schema: type[BaseModel] | None) -> dict:
        content = prompt
        kwargs = {}
        if schema is not None:
            # DeepEval asks for output matching a pydantic schema; JSON mode + the schema in the prompt
            content += f"\n\nRespond with JSON only, matching this JSON schema:\n{json.dumps(schema.model_json_schema())}"
            kwargs["response_format"] = {"type": "json_object"}
        return dict(model=self.model_id, temperature=0, messages=[{"role": "user", "content": content}], **kwargs)

    def generate(self, prompt: str, schema: type[BaseModel] | None = None):
        text = self.client.chat.completions.create(**self._request(prompt, schema)).choices[0].message.content or ""
        return schema.model_validate(_parse_json(text)) if schema is not None else text

    async def a_generate(self, prompt: str, schema: type[BaseModel] | None = None):
        response = await self.async_client.chat.completions.create(**self._request(prompt, schema))
        text = response.choices[0].message.content or ""
        return schema.model_validate(_parse_json(text)) if schema is not None else text
