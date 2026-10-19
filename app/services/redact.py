import re

EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
CARD = re.compile(r"(card ending )\d{4}", re.I)
INJECTION = re.compile(
    r"ignore (all )?(previous|prior) instructions|disregard (all )?(previous|prior) instructions"
    r"|system override|note to ai|you are now|reveal your (system )?prompt",
    re.I,
)


def redact(text: str) -> str:
    return CARD.sub(r"\1[CARD]", EMAIL.sub("[EMAIL]", text))


def looks_like_injection(text: str) -> bool:
    return bool(INJECTION.search(text))