"""Threads 장기 토큰(60일) 자동 갱신. 새 토큰은 GitHub Secret(THREADS_ACCESS_TOKEN)에 다시 저장한다."""
from __future__ import annotations

import os
import subprocess
from collections.abc import Callable, Mapping

from src import notifier
from src.guard import RunResult
from src.threads import ThreadsError, refresh_token

WARN_DAYS = 14
SECRET_NAME = 'THREADS_ACCESS_TOKEN'


def gh_set_secret(env: Mapping[str, str]) -> Callable[[str, str], None]:
    pat = env.get('GH_SECRETS_PAT', '').strip()

    def set_secret(name: str, value: str) -> None:
        if not pat:
            raise RuntimeError('GH_SECRETS_PAT가 없어 새 토큰을 저장할 수 없습니다.')
        subprocess.run(['gh', 'secret', 'set', name], input=value, text=True, check=True,
                       env={**os.environ, 'GH_TOKEN': pat}, stdout=subprocess.DEVNULL)
    return set_secret


def run_refresh(env: Mapping[str, str], telegram: notifier.TelegramConfig | None,
                refresh: Callable[[str], tuple[str, int]] = refresh_token,
                set_secret: Callable[[str, str], None] | None = None) -> RunResult:
    token = env.get('THREADS_ACCESS_TOKEN', '').strip()
    if not token:
        return RunResult('failed', 'THREADS_ACCESS_TOKEN이 없습니다.')
    try:
        new_token, expires_in = refresh(token)
        if env.get('GITHUB_ACTIONS') == 'true':
            print(f'::add-mask::{new_token}')
        (set_secret or gh_set_secret(env))(SECRET_NAME, new_token)
    except (ThreadsError, RuntimeError, subprocess.CalledProcessError) as e:
        notifier.notify(telegram, f'🔑 Threads 토큰 자동 갱신 실패: {e.__class__.__name__}. 만료되면 게시가 멈춥니다.')
        return RunResult('failed', f'토큰 갱신 실패: {e}')
    days = expires_in // 86400
    if days and days < WARN_DAYS:
        notifier.notify(telegram, f'🔑 Threads 토큰이 {days}일 뒤 만료됩니다.')
    return RunResult('success', f'토큰 갱신 완료 (유효 {days}일)')
