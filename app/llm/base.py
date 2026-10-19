from typing import Protocol


class LLMError(Exception):
    """Provider failed (network, auth, rate limit, timeout). The caller falls back to the deterministic report."""


class LLMClient(Protocol):
    def complete_json(self, system: str, user: str) -> str:
        """Return the model's raw text. Parsing and validation happen in the caller so bad output can be retried."""    