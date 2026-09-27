"""사람 검수를 대신하는 운영 안전장치: 일시정지 판단, 텔레그램 명령 반영, 연속 실패 시 자동 정지."""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from src import channel, commands, notifier
from src.history import HistoryEntry, consecutive_failures
from src.runlog import PostRecord
from src.state import State, pause

MAX_CONSECUTIVE_FAILURES = 4  # 4슬롯(2일) 연속 실패하면 자동 정지
HIGH_LLM_CALLS_PER_SET = 10  # 평소 세트당 3~5회. 이 이상이면 원고가 검수에 자주 떨어져 다시 쓰고 있다는 뜻


@dataclass(frozen=True)
class RunResult:
    outcome: str  # success / skipped / failed
    message: str
    posts: tuple[PostRecord, ...] = ()
    llm_calls: int = 0


def env_paused(env: Mapping[str, str]) -> bool:
    return (env.get('PAUSED') or '').strip().lower() in ('1', 'true', 'yes', 'on')


def pause_message(env: Mapping[str, str], state: State) -> str | None:
    """멈춰 있으면 이유를, 아니면 None을 반환합니다."""
    if env_paused(env):
        return 'GitHub Variables의 PAUSED=true라서 건너뜁니다.'
    if state.paused:
        return f'자동 정지 상태라 건너뜁니다 ({state.pause_reason}). 재개: /{channel.CMD_PREFIX}_resume'
    return None


def sync_commands(
    state: State,
    telegram: notifier.TelegramConfig | None,
    next_slot: str,
    get: Callable[..., Any] = requests.get,
) -> State:
    """텔레그램 명령을 읽어 상태에 반영하고, 반영한 내용을 알립니다."""
    new_state, notes = commands.apply_commands(state, commands.fetch_commands(telegram, get), next_slot)
    for note in notes:
        print(f'[명령] {note}')
        notifier.notify(telegram, note)
    return new_state


def check_failure_streak(
    history: Sequence[HistoryEntry], state: State, telegram: notifier.TelegramConfig | None
) -> State:
    counted = tuple(e for e in history if e.slot >= state.resumed_from)
    streak = consecutive_failures(counted)
    if streak < MAX_CONSECUTIVE_FAILURES or state.paused:
        return state
    reason = f'{streak}슬롯 연속 실패'
    notifier.notify(telegram, f'🛑 {reason}로 자동 게시를 멈췄습니다. 실행 기록을 확인한 뒤 /{channel.CMD_PREFIX}_resume 으로 재개하세요.')
    return pause(state, reason)


def llm_calls_warning(result: RunResult, writer_model: str) -> str | None:
    """세트당 AI 호출이 많으면 알림 문구를, 아니면 None을 반환합니다. 게시물 없는 실패 실행은 1세트로 칩니다."""
    sets = max(len(result.posts), 1)
    if result.llm_calls < HIGH_LLM_CALLS_PER_SET * sets:
        return None
    return (f'⚠️ AI 호출이 많았습니다: {result.llm_calls}회 ({sets}세트, 평소 세트당 3~5회)\n'
            f'원고 모델({writer_model})이 검수에 자주 떨어져 다시 쓰는 중일 수 있습니다. '
            '반복되면 원고 모델을 점검하세요.')
