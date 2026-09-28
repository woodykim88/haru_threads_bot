"""구조화 응답 호출 래퍼. AI 회사와 무관하게 호출 횟수에 상한을 둔다(비용 폭주 방지)."""
from __future__ import annotations

from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from src.providers import TextBackend

PROMPTS_DIR = Path(__file__).resolve().parent.parent / 'prompts'
DEFAULT_MAX_CALLS = 16  # 최악의 경우 화제 1 + 선별 1 + 3주제 x 2회 x (작성+검증) = 14회

T = TypeVar('T', bound=BaseModel)


class LLMError(Exception):
    """LLM 호출 실패 또는 상한 초과."""


# 글쓰기 프롬프트에는 우리 채널 최근 성과(잘 된 글·안 된 글, src/performance.py가 매일 갱신)를 붙인다
WRITING_PROMPTS = frozenset({'writer', 'product', 'general', 'casual', 'persona'})
PERFORMANCE_PATH = PROMPTS_DIR.parent / 'data' / 'performance.md'


def load_prompt(name: str) -> str:
    text = (PROMPTS_DIR / f'{name}.md').read_text(encoding='utf-8')
    if name in WRITING_PROMPTS and PERFORMANCE_PATH.exists():
        text += PERFORMANCE_PATH.read_text(encoding='utf-8')
    return text


class LLMClient:
    def __init__(self, backend: TextBackend, max_calls: int = DEFAULT_MAX_CALLS) -> None:
        self._backend = backend
        self._max_calls = max_calls
        self.calls = 0

    def parse(self, model: str, instructions: str, user_input: str, schema: type[T]) -> T:
        """schema 형태의 응답을 받아 검증된 pydantic 객체로 반환합니다."""
        if self.calls >= self._max_calls:
            raise LLMError(f'이번 실행의 LLM 호출 상한({self._max_calls}회)을 넘었습니다.')
        self.calls += 1
        parsed = self._backend.parse(model, instructions, user_input, schema)
        if parsed is None:
            raise LLMError(f'{schema.__name__} 응답을 해석하지 못했습니다 (거절 또는 형식 오류).')
        return parsed
