from app.config import settings
from app.llm.base import LLMClient, LLMError
from app.llm.groq_client import GroqClient


def get_llm() -> LLMClient:
    """Raises LLMError when the provider can't be built (e.g. missing key); the pipeline treats that as 'LLM down'."""
    if settings.llm_provider == "groq":
        return GroqClient(settings.groq_api_key, settings.groq_model)
    raise LLMError(f"unknown LLM provider: {settings.llm_provider}")