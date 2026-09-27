from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

from src.llm import LLMClient
from src.providers import OpenAITextBackend

AT_1235 = datetime(2026, 9, 27, 3, 35, tzinfo=timezone.utc)   # KST 12:35


class FakeOpenAI:
    def __init__(self, responses: dict[str, list[Any]]) -> None:
        self._responses = {k: list(v) for k, v in responses.items()}
        self.requests: list[dict[str, Any]] = []
        self.responses = SimpleNamespace(parse=self._parse)

    def _parse(self, **kwargs: Any) -> SimpleNamespace:
        self.requests.append(kwargs)
        return SimpleNamespace(output_parsed=self._responses[kwargs['text_format'].__name__].pop(0))


def fake_llm(responses: dict[str, list[Any]]) -> tuple[LLMClient, FakeOpenAI]:
    client = FakeOpenAI(responses)
    return LLMClient(OpenAITextBackend(client), max_calls=16), client


class Resp:
    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status_code = status
        self._payload = payload
        self.content = b'1'

    def json(self) -> dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(str(self.status_code))
