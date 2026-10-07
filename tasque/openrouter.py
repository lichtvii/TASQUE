import aiohttp

COMPLETIONS_URL = "https://openrouter.ai/api/v1/chat/completions"
DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


class OpenRouterError(Exception):
    pass


class OpenRouterClient:
    def __init__(self, api_key: str, model_id: str, temperature: float, max_tokens: int,
                 reasoning_enabled: bool | None):
        self.api_key = api_key
        self.model_id = model_id
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.reasoning_enabled = reasoning_enabled
        self.session: aiohttp.ClientSession | None = None

    async def open(self) -> None:
        self.session = aiohttp.ClientSession(
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "X-Title": "Tasque",
            },
            timeout=aiohttp.ClientTimeout(total=90),
        )

    async def close(self) -> None:
        if self.session:
            await self.session.close()

    async def complete(self, messages: list[dict], temperature: float | None = None,
                       max_tokens: int | None = None) -> str:
        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens if max_tokens is None else max_tokens,
        }
        if self.reasoning_enabled is not None:
            payload["reasoning"] = {"enabled": self.reasoning_enabled}

        async with self.session.post(COMPLETIONS_URL, json=payload) as response:
            body = await response.json(content_type=None)
            if response.status != 200 or "error" in body:
                raise OpenRouterError(f"HTTP {response.status}: {body.get('error', body)}")

        return body["choices"][0]["message"].get("content") or ""

    async def decide(self, model_id: str, state: dict, questions: dict) -> dict:
        payload = {"model": model_id, "state": state, "questions": questions}
        async with self.session.post(DECISIONS_URL, json=payload) as response:
            body = await response.json(content_type=None)
            if response.status != 200 or "error" in body or "answers" not in body:
                raise OpenRouterError(f"HTTP {response.status}: {body.get('error', body)}")
        return body["answers"]
