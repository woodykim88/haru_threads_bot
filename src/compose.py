"""글 한 편 만들기: 슬롯마다 토끼 캐릭터 "하루"의 일상·공감 글 하나 (src/persona.py)."""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from src import persona
from src.history import HistoryEntry
from src.llm import LLMClient


class PipelineError(Exception):
    """게시할 글을 만들지 못했을 때."""


@dataclass(frozen=True)
class Models:
    writer: str
    fast: str


@dataclass(frozen=True)
class Draft:
    key: str                  # 중복 방지 키 (persona:슬롯)
    title: str                # 기록용 이름 (글 앞부분)
    parts: tuple[str, ...]    # 게시 문구 (캐릭터 글은 첫 글 하나)
    source_url: str = ''
    kind: str = persona.KIND
    rescued: bool = False     # AI 글이 검수에 떨어져 준비된 글을 쓴 경우
    scene: str = ''           # 그림 장면 (IMAGE_TIMES 슬롯에서만 그린다)

    @property
    def text(self) -> str:
        return '\n\n— — —\n\n'.join(self.parts)


def compose(llm: LLMClient, models: Models, history: Sequence[HistoryEntry], slot: str) -> Draft:
    text, canned, scene = persona.compose_persona(llm, models.writer, history, slot)
    body = persona.with_share_line(text, slot)  # 16:00·23:30 하루 걸러 공유 줄 (검수 뒤에 붙인다)
    return Draft(f'{persona.KIND}:{slot}', text.splitlines()[0][:40], (body,), rescued=canned, scene=scene)
