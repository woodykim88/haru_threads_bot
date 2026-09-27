"""로컬 .env 값을 GitHub Secrets로 등록한다. 공통 값(OpenAI, 텔레그램, GitHub 토큰)은
건강 계정 폴더 → 블로그 폴더 .env에서 가져온다. 값은 화면에 출력하지 않는다."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
FALLBACKS = (ROOT.parent / '인스타피드 건강뉴스 자동화' / '.env', ROOT.parent / '구글블로그 AI뉴스 소식 자동화' / '.env')
OWN_KEYS = ('THREADS_USER_ID', 'THREADS_ACCESS_TOKEN')
SHARED_KEYS = ('OPENAI_API_KEY', 'TELEGRAM_BOT_TOKEN', 'TELEGRAM_CHAT_ID', 'GH_SECRETS_PAT')


def main() -> int:
    own = dotenv_values(ROOT / '.env') if (ROOT / '.env').exists() else {}
    others = [dotenv_values(p) for p in FALLBACKS if p.exists()]
    values = {k: (own.get(k) or '').strip() for k in OWN_KEYS}
    for k in SHARED_KEYS:
        values[k] = next(((e.get(k) or '').strip() for e in [own, *others] if (e.get(k) or '').strip()), '')
    for name, value in values.items():
        if not value:
            print(f'[건너뜀] {name}: 값이 비어 있음')
            continue
        subprocess.run(['gh', 'secret', 'set', name], input=value, text=True, check=True, cwd=ROOT,
                       stdout=subprocess.DEVNULL)
        print(f'[등록] {name} ({len(value)}자)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
