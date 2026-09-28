"""댓글 자동 답글: 2시간마다 최근 글에 달린 새 댓글에 하루(토끼) 말투로 짧게 답한다 (2026-09-28 사용자 결정, 하루부터 시작).

계정이 스팸으로 보이지 않게: 한 번에 최대 5개, 하루 최대 20개, 답글마다 게시 대기(30초).
욕설·스팸·민감한 댓글, "AI야?" 같은 정체 질문은 답하지 않는다 (거짓말하지 않기 위해 건너뜀).
처리한 댓글 id는 data/replied.json에 남겨 두 번 답하지 않는다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from src import notifier, persona
from src.channel import HANDLE
from src.guard import RunResult
from src.llm import LLMClient, LLMError, load_prompt
from src.threads import ThreadsClient, ThreadsError

REPLIED_PATH = Path(__file__).resolve().parent.parent / 'data' / 'replied.json'
MAX_PER_RUN = 5
MAX_PER_DAY = 20
LOOKBACK_DAYS = 3
POST_LIMIT = 15
MAX_REPLY_CHARS = 120
KEEP_IDS = 1000


class ReplyDraft(BaseModel):
    skip: bool = Field(description='답하지 않을 댓글이면 true (스팸·욕설·민감·정체 질문 등)')
    reply: str = Field(default='', description='하루의 답글 5~80자 (skip이면 빈 문자열)')
    reason: str = Field(default='', description='skip한 이유 한 줄')


@dataclass(frozen=True)
class Comment:
    id: str
    post_text: str
    username: str
    text: str


def load_replied(path: Path = REPLIED_PATH) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {'ids': [], 'days': {}}


def save_replied(data: dict[str, Any], path: Path = REPLIED_PATH) -> None:
    trimmed = {'ids': data['ids'][-KEEP_IDS:], 'days': dict(sorted(data['days'].items())[-14:])}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(trimmed, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def _posted_after(timestamp: str, cutoff: datetime) -> bool:
    try:
        return datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z') >= cutoff
    except ValueError:
        return False


def new_comments(client: ThreadsClient, handled: set[str], now: datetime) -> list[Comment]:
    """최근 LOOKBACK_DAYS일 내 글의, 내가 쓰지 않은 아직 처리 안 한 댓글 (오래된 것부터)."""
    cutoff = now - timedelta(days=LOOKBACK_DAYS)
    posts = client.get(f'{client.user_id}/threads', {'fields': 'id,text,timestamp,is_reply', 'limit': str(POST_LIMIT)})
    found: list[tuple[str, Comment]] = []
    for post in posts.get('data', []):
        if post.get('is_reply') or not _posted_after(post.get('timestamp', ''), cutoff):
            continue
        replies = client.get(f"{post['id']}/replies",
                             {'fields': 'id,text,username,timestamp,is_reply_owned_by_me,hide_status'})
        for r in replies.get('data', []):
            mine = r.get('is_reply_owned_by_me') or r.get('username') == HANDLE
            if mine or r['id'] in handled or not (r.get('text') or '').strip() or r.get('hide_status') == 'HIDDEN':
                continue
            found.append((r.get('timestamp', ''), Comment(r['id'], post.get('text', ''), r.get('username', ''),
                                                          r['text'].strip())))
    return [c for _, c in sorted(found, key=lambda pair: pair[0])]


def reply_issues(text: str) -> list[str]:
    found = persona.issues(text, needs_question=False)
    if len(text) > MAX_REPLY_CHARS:
        found.append(f'답글은 {MAX_REPLY_CHARS}자 이내')
    return found


def write_reply(llm: LLMClient, model: str, comment: Comment) -> str:
    """답할 문구를 반환합니다. 답하지 않을 댓글이거나 검수에 걸리면 빈 문자열."""
    user_input = f'내 원글: {comment.post_text[:300]}\n\n댓글 (@{comment.username}): {comment.text[:300]}'
    draft = llm.parse(model, load_prompt('reply'), user_input, ReplyDraft)
    if draft.skip or not draft.reply.strip():
        print(f'[답글 건너뜀] {comment.text[:30]} ({draft.reason})')
        return ''
    issues = reply_issues(draft.reply.strip())
    if issues:
        print(f'[답글 탈락] {draft.reply[:30]}: ' + ' / '.join(issues))
        return ''
    return draft.reply.strip()


def run_replies(client: ThreadsClient, llm: LLMClient, model: str, telegram: notifier.TelegramConfig | None,
                now: datetime | None = None, path: Path = REPLIED_PATH) -> RunResult:
    now = now or datetime.now(timezone.utc)
    day = now.astimezone(timezone(timedelta(hours=9))).strftime('%Y-%m-%d')
    data = load_replied(path)
    budget = min(MAX_PER_RUN, MAX_PER_DAY - int(data['days'].get(day, 0)))
    if budget <= 0:
        return RunResult('skipped', f'오늘 답글 한도({MAX_PER_DAY}개)를 채웠습니다.')
    comments = new_comments(client, set(data['ids']), now)
    sent: list[str] = []
    for comment in comments:
        if len(sent) >= budget:
            break
        try:
            text = write_reply(llm, model, comment)
            if text:
                box = client.create_text(text, reply_to=comment.id)
                client.wait_before_publish()
                client.publish(box)
                sent.append(f'@{comment.username}: {comment.text[:20]} → {text}')
        except LLMError as e:
            print(f'[답글 실패] {e}')
            break
        except ThreadsError as e:
            print(f'[답글 게시 실패] {e}')
            if e.fatal:
                notifier.notify(telegram, f'🛑 댓글 답글 중 Threads 오류라 멈춥니다: {e}')
                break
            continue
        data = {**data, 'ids': [*data['ids'], comment.id]}
    data = {**data, 'days': {**data['days'], day: int(data['days'].get(day, 0)) + len(sent)}}
    save_replied(data, path)
    if sent:
        notifier.notify(telegram, f'💬 댓글 {len(sent)}개에 답했어요\n' + '\n'.join(sent[:5]))
    return RunResult('success', f'새 댓글 {len(comments)}개 중 {len(sent)}개 답글', llm_calls=llm.calls)
