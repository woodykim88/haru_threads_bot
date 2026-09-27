"""텔레그램 알림 (블로그 봇 재사용). TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID가 없으면 아무것도 하지 않는다.

같은 봇을 블로그·인스타·다른 Threads 계정과 함께 쓰므로 모든 메시지 앞에 [Threads 채널명]을 붙인다.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import requests

from src.channel import NAME

TELEGRAM_API = 'https://api.telegram.org'
PREFIX = f'[Threads {NAME}] '
MAX_MESSAGE_CHARS = 4000   # 텔레그램 한도 4096자
MAX_MEDIA_CAPTION = 1000   # 사진 캡션 한도 1024자
MAX_MEDIA_GROUP = 10


@dataclass(frozen=True)
class TelegramConfig:
    bot_token: str
    chat_id: str


def load_telegram_config(env: Mapping[str, str]) -> TelegramConfig | None:
    token = env.get('TELEGRAM_BOT_TOKEN', '').strip()
    chat_id = env.get('TELEGRAM_CHAT_ID', '').strip()
    return TelegramConfig(token, chat_id) if token and chat_id else None


def _send(config: TelegramConfig, method: str, payload: dict[str, Any], post: Callable[..., Any]) -> bool:
    try:
        response = post(f'{TELEGRAM_API}/bot{config.bot_token}/{method}', json=payload, timeout=20)
        response.raise_for_status()
        return True
    except requests.RequestException as e:
        # URL에 봇 토큰이 들어 있으므로 예외 메시지 전체를 출력하지 않는다
        print(f'[알림 실패] 텔레그램 {method} 오류: {e.__class__.__name__}')
        return False


def notify(config: TelegramConfig | None, text: str, post: Callable[..., Any] = requests.post) -> bool:
    """메시지를 보냅니다. 알림 실패가 게시를 막으면 안 되므로 예외 대신 False를 반환합니다."""
    if config is None:
        return False
    payload = {'chat_id': config.chat_id, 'text': (PREFIX + text)[:MAX_MESSAGE_CHARS],
               'disable_web_page_preview': True}
    return _send(config, 'sendMessage', payload, post)


def notify_album(
    config: TelegramConfig | None, image_urls: Sequence[str], caption: str,
    post: Callable[..., Any] = requests.post,
) -> bool:
    """카드 이미지를 앨범으로 보냅니다 (첫 장에 설명). 실패하면 글 알림으로 대신합니다."""
    if config is None:
        return False
    media = [{'type': 'photo', 'media': url} for url in image_urls[:MAX_MEDIA_GROUP]]
    if media:
        media[0] = {**media[0], 'caption': (PREFIX + caption)[:MAX_MEDIA_CAPTION]}
    ok = bool(media) and _send(config, 'sendMediaGroup', {'chat_id': config.chat_id, 'media': media}, post)
    return ok or notify(config, caption, post)
