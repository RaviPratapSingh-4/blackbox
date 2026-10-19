import time

from groq import Groq, GroqError, RateLimitError

from app.llm.base import LLMError


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout: float = 60.0):
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=0)
        self._model = model

    def complete_json(self, system: str, user: str) -> str:
        for attempt in (1, 2):
            try:
                resp = self._client.chat.completions.create(
                    model=self._model, temperature=0, response_format={"type": "json_object"},
                    max_completion_tokens=6000,
                    reasoning_effort="low",      # gpt-oss only; remove this line if you switch to a non-reasoning model
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
                return resp.choices[0].message.content or ""
            except RateLimitError as exc:
                if attempt == 2:
                    raise LLMError(f"rate limited: {str(exc)[:150]}") from exc
                time.sleep(25)  # free-tier limits are per minute
            except GroqError as exc:
                raise LLMError(str(exc)[:200]) from exc
