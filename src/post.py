"""게시 작업: 슬롯 시각이 되면 글을 만들고 바로 Threads에 올린다 (텍스트라 준비 단계가 따로 없다).

중복 게시 방지: 공개 API 호출 직전에 PUBLISHING으로 기록하고, 그 슬롯은 다시 게시하지 않는다.
"""
from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src import channel, compose, guard, history, notifier, schedule, state
from src.guard import RunResult
from src.llm import LLMClient, LLMError
from src.providers import TextBackend
from src.runlog import PostRecord
from src.threads import ThreadsClient, ThreadsError

PUBLISHING = 'PUBLISHING'
RESCUED_NOTE = '준비된 글'


@dataclass(frozen=True)
class PostDeps:
    backend: TextBackend
    models: compose.Models
    client: ThreadsClient
    tg_get: Callable[..., Any] | None = None


def _stamp(now: datetime) -> str:
    return now.astimezone(schedule.KST).isoformat(timespec='seconds')


def done_slots(past: tuple[history.HistoryEntry, ...]) -> set[str]:
    return {e.slot for e in past if e.status in (history.PUBLISHED, history.SKIPPED, PUBLISHING)}


def publish_replies(client: ThreadsClient, parent_id: str, replies: tuple[str, ...]) -> str:
    """첫 글 아래에 답글을 차례로 잇습니다. 실패하면 멈추고 메모를 남깁니다 (첫 글은 이미 공개됨)."""
    for i, text in enumerate(replies, start=1):
        try:
            box = client.create_text(text, reply_to=parent_id)
            client.wait_before_publish()
            parent_id = client.publish(box)
        except ThreadsError as e:
            print(f'[답글 {i} 실패] {e}')
            return f'답글 {i}/{len(replies)} 게시 실패: {e}'[:300]
    return ''


def post_slot(key: str, deps: PostDeps, llm: LLMClient, past: tuple[history.HistoryEntry, ...],
              now: datetime) -> history.HistoryEntry:
    draft = compose.compose(llm, deps.models, past, key)
    container = deps.client.create_text(draft.parts[0])
    entry = history.HistoryEntry(slot=key, status=PUBLISHING, title=draft.title, seed=draft.kind,
                                 doc_id=draft.key, source_url=draft.source_url, caption=draft.text,
                                 note=RESCUED_NOTE if draft.rescued else '', updated_at=_stamp(now))
    history.save_history(history.upsert(past, entry))
    deps.client.wait_before_publish()
    media_id = deps.client.publish(container)
    done = history.with_status(entry, history.PUBLISHED, media_id=media_id)
    history.save_history(history.upsert(history.load_history(), done))
    note = ' / '.join(n for n in (entry.note, publish_replies(deps.client, media_id, draft.parts[1:])) if n)
    try:
        done = history.with_status(done, history.PUBLISHED, permalink=deps.client.permalink(media_id), note=note)
    except ThreadsError as e:
        print(f'[주소 조회 실패] 게시는 완료됨: {e}')
        done = history.with_status(done, history.PUBLISHED, note=note)
    history.save_history(history.upsert(history.load_history(), done))
    return done


def run_post(env: Mapping[str, str], deps: PostDeps, telegram: notifier.TelegramConfig | None,
             now: datetime) -> RunResult:
    times = schedule.parse_times(env.get('PUBLISH_TIMES'))
    past = history.load_history()
    slots = [schedule.slot_key(s) for s in schedule.publishable_slots(now, times)]
    todo = [k for k in slots if k not in done_slots(past)]
    current = guard.sync_commands(state.load_state(), telegram, todo[0] if todo else '',
                                  **({'get': deps.tg_get} if deps.tg_get else {}))
    state.save_state(current)
    paused = guard.pause_message(env, current)
    if paused:
        return RunResult('skipped', paused)
    if not todo:
        return RunResult('skipped', '지금 게시할 슬롯이 없습니다.')

    posts, errors, calls = [], [], 0
    for key in todo:
        if key in current.skip_slots:
            past = history.upsert(past, history.HistoryEntry(key, history.SKIPPED, note=f'/{channel.CMD_PREFIX}_skip', updated_at=_stamp(now)))
            history.save_history(past)
            continue
        llm = LLMClient(deps.backend)
        try:
            done = post_slot(key, deps, llm, past, now)
            past = history.load_history()
            posts.append(PostRecord(done.title, done.status, key, done.permalink))
            mark = '⚠️ 준비된 글로' if RESCUED_NOTE in done.note else '✅'
            notifier.notify(telegram, f'{mark} 하루 게시: {done.title}\n{done.permalink or "(주소 조회 실패)"}')
        except (compose.PipelineError, LLMError) as e:
            errors.append(f'{key}: {e}')
            past = history.upsert(past, history.HistoryEntry(key, history.FAILED, note=str(e)[:300], updated_at=_stamp(now)))
            history.save_history(past)
            notifier.notify(telegram, f'⚠️ {key} 글을 만들지 못해 이번엔 건너뜁니다.\n원인: {e}')
        except ThreadsError as e:
            errors.append(f'{key}: {e}')
            past = history.load_history()
            if (history.find(past, key) or history.HistoryEntry(key, '')).status == PUBLISHING:
                notifier.notify(telegram, f'❓ {key} 게시 요청 중 오류. Threads에 올라갔는지 확인해 주세요.\n원인: {e}')
            else:
                past = history.upsert(past, history.HistoryEntry(key, history.FAILED, note=str(e)[:300], updated_at=_stamp(now)))
                history.save_history(past)
                notifier.notify(telegram, f'❌ {key} 게시 실패\n원인: {e}')
            if e.fatal:
                state.save_state(state.pause(state.load_state(), f'Threads API 오류 (code {e.code})'))
                notifier.notify(telegram, f'🛑 계정 보호를 위해 자동 게시를 멈췄습니다. 토큰·권한을 확인한 뒤 /{channel.CMD_PREFIX}_resume')
        finally:
            calls += llm.calls

    state.save_state(guard.check_failure_streak(past, state.load_state(), telegram))
    if errors:
        return RunResult('failed', ' / '.join(errors), tuple(posts), calls)
    return RunResult('success', f'{len(posts)}건 게시', tuple(posts), calls)


# --- 미리 보여 준 글 그대로 게시 (수동 테스트·사람 확인 후 게시용) ---

PENDING_PATH = Path(__file__).resolve().parent.parent / 'data' / 'pending.json'


def save_pending(draft: compose.Draft, slot: str, path: Path | None = None) -> None:
    path = path or PENDING_PATH
    row = {'slot': slot, 'key': draft.key, 'title': draft.title, 'kind': draft.kind,
           'parts': list(draft.parts), 'source_url': draft.source_url}
    path.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def run_pending(client: ThreadsClient, telegram: notifier.TelegramConfig | None, now: datetime,
                path: Path | None = None) -> RunResult:
    """data/pending.json의 글을 그대로 올리고 기록한 뒤 파일을 지웁니다. 같은 슬롯은 두 번 올리지 않습니다."""
    path = path or PENDING_PATH
    if not path.exists():
        return RunResult('skipped', '올릴 글(data/pending.json)이 없습니다.')
    row = json.loads(path.read_text(encoding='utf-8'))
    past = history.load_history()
    if row['slot'] in done_slots(past):
        path.unlink()
        return RunResult('skipped', f'{row["slot"]}은 이미 올렸습니다.')
    parts = tuple(row['parts'])
    container = client.create_text(parts[0])
    entry = history.HistoryEntry(slot=row['slot'], status=PUBLISHING, title=row['title'], seed=row['kind'],
                                 doc_id=row['key'], source_url=row['source_url'],
                                 caption='\n\n— — —\n\n'.join(parts), note='미리 보여 준 글', updated_at=_stamp(now))
    history.save_history(history.upsert(past, entry))
    client.wait_before_publish()
    media_id = client.publish(container)
    done = history.with_status(entry, history.PUBLISHED, media_id=media_id)
    history.save_history(history.upsert(history.load_history(), done))
    note = publish_replies(client, media_id, parts[1:])
    try:
        done = history.with_status(done, history.PUBLISHED, permalink=client.permalink(media_id), note=note or entry.note)
    except ThreadsError as e:
        print(f'[주소 조회 실패] 게시는 완료됨: {e}')
    history.save_history(history.upsert(history.load_history(), done))
    path.unlink()
    notifier.notify(telegram, f'✅ 게시: {done.title}\n{done.permalink or "(주소 조회 실패)"}')
    return RunResult('success', f'1건 게시: {done.permalink}', (PostRecord(done.title, done.status, done.slot, done.permalink),))
