"""텔레그램 명령 읽기: /{접두어}_stop, /{접두어}_skip, /{접두어}_resume (접두어는 channel.CMD_PREFIX).

서버 없이 준비·게시 작업이 돌 때마다 getUpdates로 한 번 읽는다.
봇을 블로그와 함께 쓰므로 offset을 넘기지 않는다(다른 곳이 읽을 메시지를 지우지 않음).
대신 처리한 update_id를 state.json에 기억해 같은 명령을 두 번 처리하지 않는다.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests

from src.channel import CMD_PREFIX
from src.notifier import TELEGRAM_API, TelegramConfig
from src.state import State, mark_handled, pause, resume, skip

STOP, SKIP, RESUME = (f'/{CMD_PREFIX}_{name}' for name in ('stop', 'skip', 'resume'))
COMMANDS = (STOP, SKIP, RESUME)


@dataclass(frozen=True)
class Command:
    update_id: int
    name: str


def fetch_commands(config: TelegramConfig | None, get: Callable[..., Any] = requests.get) -> list[Command]:
    """지정한 채팅방에서 온 명령만 반환합니다. 읽기 실패는 게시를 막지 않습니다."""
    if config is None:
        return []
    try:
        response = get(f'{TELEGRAM_API}/bot{config.bot_token}/getUpdates',
                       params={'allowed_updates': '["message"]'}, timeout=20)
        response.raise_for_status()
        updates = response.json().get('result', [])
    except (requests.RequestException, ValueError) as e:
        print(f'[명령 읽기 실패] {e.__class__.__name__} (웹훅이 설정된 봇이면 읽을 수 없습니다)')
        return []
    commands = []
    for update in updates:
        message = update.get('message') or {}
        if str(message.get('chat', {}).get('id', '')) != config.chat_id:
            continue
        word = (message.get('text') or '').strip().split(' ')[0].split('@')[0].lower()
        if word in COMMANDS:
            commands.append(Command(int(update['update_id']), word))
    return commands


def apply_commands(state: State, commands: list[Command], next_slot: str) -> tuple[State, list[str]]:
    """아직 처리하지 않은 명령을 순서대로 적용하고 (새 상태, 알림 문구 목록)을 반환합니다."""
    notes = []
    fresh = [c for c in sorted(commands, key=lambda c: c.update_id) if c.update_id not in state.handled_updates]
    for command in fresh:
        if command.name == STOP:
            state = pause(state, f'텔레그램 {STOP} 명령')
            notes.append(f'⏸ 자동 게시를 멈췄습니다. 다시 시작하려면 {RESUME}')
        elif command.name == RESUME:
            state = resume(state, next_slot)
            notes.append('▶️ 자동 게시를 다시 시작합니다.')
        elif command.name == SKIP and next_slot:
            state = skip(state, next_slot)
            notes.append(f'⏭ {next_slot} 게시를 건너뜁니다.')
    return mark_handled(state, tuple(c.update_id for c in fresh)), notes
