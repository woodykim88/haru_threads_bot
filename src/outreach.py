"""다른 계정 글에 달 댓글 초안 만들기 (2026-10-11).

Threads API로는 남의 글에 댓글을 달 수 없고(권한 없음), 남의 글을 긁어 오는 것은 약관 위반이라
사람이 하루 10분 직접 한다. 이 모듈은 사용자가 data/outreach_inbox.md에 붙여 넣은 글(--- 로 구분)마다
하루 말투의 댓글 초안 3개를 만들어 output/outreach_drafts.md에 쓴다. 게시는 사람이 직접 복사해서 한다.
"""
from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from src import persona
from src.guard import RunResult
from src.llm import LLMClient, load_prompt

ROOT = Path(__file__).resolve().parent.parent
INBOX_PATH = ROOT / 'data' / 'outreach_inbox.md'
DRAFTS_PATH = ROOT / 'output' / 'outreach_drafts.md'
MAX_POSTS = 10
MIN_CHARS, MAX_CHARS = 5, 70


class CommentDrafts(BaseModel):
    skip: bool = Field(description='댓글을 달기 부적절한 글(슬픈·심각한 내용)이면 true')
    comments: list[str] = Field(default_factory=list, description='하루 말투 댓글 초안 3개')


def read_inbox(path: Path = INBOX_PATH) -> list[str]:
    """# 제목, > 안내 줄을 빼고 --- 로 나눈 글 목록 (최대 MAX_POSTS개)."""
    try:
        raw = path.read_text(encoding='utf-8')
    except OSError:
        return []
    blocks = ['\n'.join(ln for ln in b.strip().splitlines() if not ln.startswith(('#', '>'))).strip()
              for b in re.split(r'\n---+\s*(?:\n|$)', raw)]
    return [b for b in blocks if b][:MAX_POSTS]


def usable(comments: list[str]) -> list[str]:
    """길이·금지어·사람인 척 표현 검수를 통과한 초안만."""
    return [c.strip() for c in comments
            if MIN_CHARS <= len(c.strip()) <= MAX_CHARS and not persona.issues(c.strip(), False)]


def run_outreach(llm: LLMClient, model: str, inbox: Path = INBOX_PATH, out: Path = DRAFTS_PATH) -> RunResult:
    posts = read_inbox(inbox)
    if not posts:
        return RunResult('skipped', f'댓글 달 글이 없습니다. {inbox}에 글을 붙여 넣고 --- 로 구분하세요.')
    sections = []
    for i, post in enumerate(posts, 1):
        draft = llm.parse(model, load_prompt('outreach'), f'다른 계정의 글:\n{post}', CommentDrafts)
        comments = [] if draft.skip else usable(draft.comments)
        body = '\n'.join(f'- {c}' for c in comments) if comments else '(이 글에는 댓글을 달지 않는 게 좋아요)'
        sections.append(f'## 글 {i}\n> ' + post.replace('\n', '\n> ') + f'\n\n{body}')
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n\n'.join(sections) + '\n', encoding='utf-8')
    print('\n\n'.join(sections))
    return RunResult('success', f'댓글 초안 {len(posts)}글 → {out}', llm_calls=llm.calls)
