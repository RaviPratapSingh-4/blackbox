from groq import Groq, GroqError

from app.llm.base import LLMError


class GroqClient:
    def __init__(self, api_key: str, model: str, timeout: float = 30.0):
        if not api_key:
            raise LLMError("GROQ_API_KEY is not set")
        self._client = Groq(api_key=api_key, timeout=timeout, max_retries=1)
        self._model = model

    def complete_json(self, system: str, user: str) -> str:
        try:
            resp = self._client.chat.completions.create(
                model=self._model, temperature=0, response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        except GroqError as exc:
            raise LLMError(str(exc)[:200]) from exc
        return resp.choices[0].message.content or ""