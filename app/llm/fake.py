class FakeLLM:
    """Test double: each call returns the next scripted response; an Exception instance is raised instead."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[tuple[str, str]] = []

    def complete_json(self, system: str, user: str) -> str:
        self.calls.append((system, user))
        item = self._responses.pop(0)  # IndexError means the test scripted too few responses
        if isinstance(item, Exception):
            raise item
        return item