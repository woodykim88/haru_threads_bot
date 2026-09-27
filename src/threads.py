"""Threads API: 텍스트 게시, 게시 한도, 토큰 갱신. 토큰은 파라미터로만 보내고 오류에 URL을 남기지 않는다."""
from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

import requests

GRAPH = 'https://graph.threads.net'
API_VERSION = 'v1.0'
TIMEOUT_SECONDS = 30
PUBLISH_WAIT_SECONDS = 30  # Meta 권장: 컨테이너 만든 뒤 잠깐 기다렸다 게시
MAX_TEXT_CHARS = 500
FATAL_ERROR_CODES = frozenset({10, 190, 200, 368})

Request = Callable[[str, str, Mapping[str, str]], requests.Response]


class ThreadsError(Exception):
    def __init__(self, message: str, code: int | None = None, fatal: bool = False) -> None:
        super().__init__(message)
        self.code = code
        self.fatal = fatal


class ThreadsConfigError(Exception):
    """THREADS_USER_ID / THREADS_ACCESS_TOKEN이 없을 때."""


@dataclass(frozen=True)
class ThreadsConfig:
    user_id: str
    access_token: str


def load_threads_config(env: Mapping[str, str]) -> ThreadsConfig:
    user_id, token = env.get('THREADS_USER_ID', '').strip(), env.get('THREADS_ACCESS_TOKEN', '').strip()
    missing = [n for n, v in (('THREADS_USER_ID', user_id), ('THREADS_ACCESS_TOKEN', token)) if not v]
    if missing:
        raise ThreadsConfigError(f'Threads 설정이 비어 있습니다: {", ".join(missing)}')
    return ThreadsConfig(user_id, token)


def _default_request(method: str, url: str, params: Mapping[str, str]) -> requests.Response:
    if method == 'GET':
        return requests.get(url, params=params, timeout=TIMEOUT_SECONDS)
    return requests.post(url, data=params, timeout=TIMEOUT_SECONDS)


def _error(response: requests.Response) -> ThreadsError:
    try:
        error = response.json().get('error', {})
    except ValueError:
        error = {}
    code = error.get('code')
    fatal = code in FATAL_ERROR_CODES or response.status_code == 403
    return ThreadsError(f'Threads API 오류 (code {code}, HTTP {response.status_code}): '
                        f'{error.get("message") or response.status_code}', code, fatal)


def _json(response: requests.Response) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        raise ThreadsError(f'Threads API 응답을 해석하지 못했습니다 (HTTP {response.status_code}).') from None
    if not isinstance(data, dict):
        raise ThreadsError('Threads API 응답 형식이 올바르지 않습니다.')
    return data


class ThreadsClient:
    def __init__(self, config: ThreadsConfig, request: Request = _default_request,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._config = config
        self._request = request
        self._sleep = sleep

    def _call(self, method: str, path: str, params: Mapping[str, str] | None = None) -> dict[str, Any]:
        full = {**(params or {}), 'access_token': self._config.access_token}
        try:
            response = self._request(method, f'{GRAPH}/{API_VERSION}/{path}', full)
        except requests.RequestException as e:
            raise ThreadsError(f'Threads API 연결 실패: {e.__class__.__name__}') from None
        if response.status_code >= 400:
            raise _error(response)
        return _json(response)

    def create_text(self, text: str, reply_to: str = '') -> str:
        """텍스트 컨테이너를 만듭니다. reply_to를 주면 그 글에 이어지는 답글이 됩니다."""
        if len(text) > MAX_TEXT_CHARS:
            raise ThreadsError(f'Threads 글은 {MAX_TEXT_CHARS}자까지입니다 (현재 {len(text)}자).')
        params = {'media_type': 'TEXT', 'text': text, **({'reply_to_id': reply_to} if reply_to else {})}
        data = self._call('POST', f'{self._config.user_id}/threads', params)
        if not data.get('id'):
            raise ThreadsError('Threads 컨테이너 id가 없습니다.')
        return str(data['id'])

    def publish(self, creation_id: str) -> str:
        """재시도하지 않는다 (서버에선 성공했는데 응답만 실패하면 두 번 올라갈 수 있음)."""
        data = self._call('POST', f'{self._config.user_id}/threads_publish', {'creation_id': creation_id})
        if not data.get('id'):
            raise ThreadsError('Threads 게시 id가 없습니다.')
        return str(data['id'])

    def permalink(self, media_id: str) -> str:
        return self._call('GET', media_id, {'fields': 'permalink'}).get('permalink', '')

    def wait_before_publish(self) -> None:
        self._sleep(PUBLISH_WAIT_SECONDS)


def refresh_token(token: str, request: Request = _default_request) -> tuple[str, int]:
    try:
        response = request('GET', f'{GRAPH}/refresh_access_token',
                           {'grant_type': 'th_refresh_token', 'access_token': token})
    except requests.RequestException as e:
        raise ThreadsError(f'토큰 갱신 연결 실패: {e.__class__.__name__}') from None
    if response.status_code >= 400:
        raise _error(response)
    data = _json(response)
    if not data.get('access_token'):
        raise ThreadsError('토큰 갱신 응답에 access_token이 없습니다.')
    return data['access_token'], int(data.get('expires_in', 0))
