"""Threads 토큰 확인 + 사용자 ID 자동 기록. 토큰 값은 화면에 출력하지 않는다.
사용법: "../../블로그/구글블로그-정보마스터/.venv/bin/python" scripts/check_threads.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import requests
from dotenv import dotenv_values, set_key

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from src.channel import HANDLE  # noqa: E402

ENV_PATH = Path(__file__).resolve().parent.parent / '.env'
EXPECTED_USERNAME = HANDLE


def main() -> int:
    env = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    token = (env.get('THREADS_ACCESS_TOKEN') or '').strip()
    if not token:
        print('[토큰 없음] .env의 THREADS_ACCESS_TOKEN= 뒤에 토큰을 붙여 넣고 저장해 주세요.')
        return 1
    try:
        r = requests.get('https://graph.threads.net/v1.0/me', params={'fields': 'id,username', 'access_token': token},
                         timeout=20)
    except requests.RequestException as e:
        print(f'[연결 실패] {e.__class__.__name__}')
        return 1
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        print(f'[토큰 오류] {data.get("error", {}).get("message", r.status_code)}')
        return 1
    print(f'연결된 계정: @{data.get("username")}')
    print(f'사용자 ID: {data.get("id")}')
    if data.get('username') != EXPECTED_USERNAME:
        print(f'⚠️ @{EXPECTED_USERNAME}가 아닌 다른 계정입니다.')
        return 1
    if not (env.get('THREADS_USER_ID') or '').strip():
        set_key(str(ENV_PATH), 'THREADS_USER_ID', str(data.get('id')), quote_mode='never')
        print('.env의 THREADS_USER_ID를 자동으로 채웠습니다.')
    print('✅ 준비 완료')
    return 0


if __name__ == '__main__':
    sys.exit(main())
