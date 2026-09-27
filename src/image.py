"""하루 그림: 글 장면에 맞는 일러스트 한 장 (channel.IMAGE_TIMES 슬롯만, 2026-09-27 사용자 결정 하루 1장).

- 프로필 그림(assets/haru_ref.jpg)을 기준 이미지로 넘겨 매번 같은 캐릭터가 나오게 한다 (gpt-image-2 편집 모드).
- 그림은 Cloudflare R2(인스타 채널과 같은 버킷, threads-haru/ 경로)에 올리고, 그 공개 주소로 Threads에 게시한다.
- 그림을 만들거나 올리다 실패하면 글만 게시한다 (회차를 건너뛰지 않음).
"""
from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src import usage

REFERENCE = Path(__file__).resolve().parent.parent / 'assets' / 'haru_ref.jpg'
MODEL = 'gpt-image-2'
SIZE = '1024x1024'
QUALITY = 'medium'
KEY_PREFIX = 'threads-haru'
R2_ENV_KEYS = ('R2_ACCOUNT_ID', 'R2_ACCESS_KEY_ID', 'R2_SECRET_ACCESS_KEY', 'R2_BUCKET', 'R2_PUBLIC_BASE_URL')
STYLE = (
    'Draw the same rabbit character as the reference image: a small white rabbit named Haru with one ear folded, '
    'pink blush, sleepy gentle eyes. Keep the exact hand-drawn colored-pencil style, soft rounded lines, warm cream '
    'and beige pastel palette with carrot-orange accents. Cute, cozy, healing mood. No text, no letters, no humans. '
    'Scene: '
)


class ImageError(Exception):
    """그림을 만들거나 올리지 못했을 때 (글만 게시하고 계속 진행)."""


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    public_base_url: str


def load_r2_config(env: Mapping[str, str]) -> R2Config:
    values = {k: (env.get(k) or '').strip() for k in R2_ENV_KEYS}
    missing = [k for k, v in values.items() if not v]
    if missing:
        raise ImageError(f'R2 설정이 비어 있습니다: {", ".join(missing)}')
    return R2Config(values['R2_ACCOUNT_ID'], values['R2_ACCESS_KEY_ID'], values['R2_SECRET_ACCESS_KEY'],
                    values['R2_BUCKET'], values['R2_PUBLIC_BASE_URL'].rstrip('/'))


def object_key(slot: str) -> str:
    """threads-haru/2026/09/2026-09-27T2000-1a2b3c4d.jpg"""
    digest = hashlib.sha256(slot.encode()).hexdigest()[:8]
    return f'{KEY_PREFIX}/{slot[:4]}/{slot[5:7]}/{slot.replace(":", "")}-{digest}.jpg'


def draw(client: Any, scene: str) -> bytes:
    """기준 이미지를 넘겨 같은 캐릭터로 장면을 그립니다."""
    with REFERENCE.open('rb') as ref:
        response = client.images.edit(model=MODEL, image=ref, prompt=STYLE + scene, size=SIZE, quality=QUALITY,
                                      output_format='jpeg', n=1)
    usage.record(MODEL, response)
    data = response.data[0].b64_json if response.data else None
    if not data:
        raise ImageError('그림 응답이 비어 있습니다.')
    return base64.b64decode(data)


def upload(config: R2Config, key: str, body: bytes, s3: Any = None) -> str:
    if s3 is None:
        import boto3

        s3 = boto3.client('s3', endpoint_url=f'https://{config.account_id}.r2.cloudflarestorage.com',
                          aws_access_key_id=config.access_key_id, aws_secret_access_key=config.secret_access_key,
                          region_name='auto')
    s3.put_object(Bucket=config.bucket, Key=key, Body=body, ContentType='image/jpeg',
                  CacheControl='public, max-age=31536000, immutable')
    return f'{config.public_base_url}/{key}'


def make_image(env: Mapping[str, str], scene: str, slot: str, client: Any = None, s3: Any = None) -> str:
    """장면을 그려 R2에 올리고 공개 주소를 반환합니다. 실패하면 ImageError."""
    config = load_r2_config(env)
    try:
        if client is None:
            from openai import OpenAI

            client = OpenAI(api_key=env.get('OPENAI_API_KEY', ''))
        body = draw(client, scene)
        return upload(config, object_key(slot), body, s3)
    except ImageError:
        raise
    except Exception as e:  # noqa: BLE001 - 그림 실패는 글 게시를 막지 않는다
        raise ImageError(f'{e.__class__.__name__}: {str(e)[:200]}') from e
