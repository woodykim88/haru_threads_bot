"""AI 회사(OpenAI / Google Gemini / Anthropic Claude) 연결 계층. 구글블로그 AI뉴스 소식 자동화에서 이식 (텍스트만 사용).

파이프라인은 TextBackend.parse()만 알면 되고, 어느 회사를 쓰는지는 환경변수로 정한다.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel
from src import usage

T = TypeVar('T', bound=BaseModel)

TEXT_PROVIDERS = ('openai', 'gemini', 'anthropic')
PROVIDER_LABELS = {'openai': 'OpenAI (GPT)', 'gemini': 'Google Gemini', 'anthropic': 'Anthropic Claude'}
KEY_ENV = {'openai': 'OPENAI_API_KEY', 'gemini': 'GEMINI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}

DEFAULT_TEXT_MODELS = {
    'openai': {'writer': 'gpt-5.6-terra', 'fast': 'gpt-5.4-mini'},
    'gemini': {'writer': 'gemini-2.5-pro', 'fast': 'gemini-2.5-flash'},
    'anthropic': {'writer': 'claude-sonnet-5', 'fast': 'claude-haiku-4-5'},
}
ANTHROPIC_MAX_TOKENS = 8000


class ProviderConfigError(Exception):
    """AI 회사/모델/키 설정이 잘못되었을 때 발생합니다."""


@dataclass(frozen=True)
class AISettings:
    text_provider: str
    writer_model: str
    fast_model: str


def load_ai_settings(env: Mapping[str, str]) -> AISettings:
    provider = (env.get('TEXT_PROVIDER') or 'openai').strip().lower()
    if provider not in TEXT_PROVIDERS:
        raise ProviderConfigError(f'TEXT_PROVIDER는 {"/".join(TEXT_PROVIDERS)} 중 하나여야 합니다. (현재: {provider})')
    defaults = DEFAULT_TEXT_MODELS[provider]
    writer = (env.get('WRITER_MODEL') or defaults['writer']).strip()
    fast = (env.get('FAST_MODEL') or defaults['fast']).strip()
    return AISettings(provider, writer, fast)


def api_key(env: Mapping[str, str], provider: str) -> str:
    key = (env.get(KEY_ENV[provider]) or '').strip()
    if not key:
        raise ProviderConfigError(f'{PROVIDER_LABELS[provider]}를 쓰려면 {KEY_ENV[provider]}가 필요합니다.')
    return key


class TextBackend(Protocol):
    def parse(self, model: str, instructions: str, user_input: str, schema: type[T]) -> T | None: ...


class OpenAITextBackend:
    def __init__(self, client: Any) -> None:
        self._client = client

    def parse(self, model: str, instructions: str, user_input: str, schema: type[T]) -> T | None:
        response = self._client.responses.parse(
            model=model, instructions=instructions, input=user_input, text_format=schema
        )
        usage.record(model, response)
        return response.output_parsed


class AnthropicTextBackend:
    def __init__(self, client: Any) -> None:
        self._client = client

    def parse(self, model: str, instructions: str, user_input: str, schema: type[T]) -> T | None:
        response = self._client.messages.parse(
            model=model,
            max_tokens=ANTHROPIC_MAX_TOKENS,
            system=instructions,
            messages=[{'role': 'user', 'content': user_input}],
            output_format=schema,
        )
        usage.record(model, response)
        return response.parsed_output


class GeminiTextBackend:
    def __init__(self, client: Any) -> None:
        self._client = client

    def parse(self, model: str, instructions: str, user_input: str, schema: type[T]) -> T | None:
        from google.genai import types

        response = self._client.models.generate_content(
            model=model,
            contents=user_input,
            config=types.GenerateContentConfig(
                system_instruction=instructions,
                response_mime_type='application/json',
                response_schema=schema,
            ),
        )
        parsed = response.parsed
        if parsed is None or isinstance(parsed, schema):
            return parsed
        return schema.model_validate(parsed)


def build_text_backend(provider: str, env: Mapping[str, str]) -> TextBackend:
    key = api_key(env, provider)
    if provider == 'openai':
        from openai import OpenAI
        return OpenAITextBackend(OpenAI(api_key=key))
    if provider == 'anthropic':
        from anthropic import Anthropic
        return AnthropicTextBackend(Anthropic(api_key=key))
    from google import genai
    return GeminiTextBackend(genai.Client(api_key=key))
