"""우리 채널 성과 반영: 최근 글의 조회수를 읽어 잘 된 글·안 된 글을 글쓰기에 참고로 넣는다 (2026-09-28 사용자 결정).

- 하루 한 번(--job insights) Threads 인사이트를 읽어 data/performance.json(대시보드용)과
  data/performance.md(글쓰기 참고)를 쓴다. AI를 부르지 않으므로 비용이 들지 않는다.
- llm.load_prompt가 글쓰기 프롬프트 뒤에 performance.md를 붙인다 (몇 줄이라 글 하나에 1원 안팎).
- 다른 계정의 인기 글 검색(keyword_search)은 Meta 별도 승인이 필요해서 쓰지 않는다.
- Threads 세 채널과 하루 채널이 같은 파일을 쓴다. 고칠 때 네 저장소를 함께 고친다.
"""
from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.guard import RunResult
from src.threads import ThreadsClient, ThreadsError

DATA = Path(__file__).resolve().parent.parent / 'data'
STATS_PATH = DATA / 'performance.json'
BRIEF_PATH = DATA / 'performance.md'
POST_LIMIT = 25
METRICS = 'views,likes,replies,reposts,shares'
TOP, BOTTOM, MIN_POSTS = 3, 3, 5
MAX_AGE_DAYS = 14  # 자동화 전에 사람이 올린 옛 글은 참고에서 뺀다
SNIPPET_CHARS = 70


def _recent(timestamp: str, now: datetime) -> bool:
    try:
        posted = datetime.strptime(timestamp, '%Y-%m-%dT%H:%M:%S%z')
    except ValueError:
        return False
    return now - posted <= timedelta(days=MAX_AGE_DAYS)


def fetch_stats(client: ThreadsClient, now: datetime | None = None, limit: int = POST_LIMIT) -> list[dict[str, Any]]:
    """최근 MAX_AGE_DAYS일 첫 글(답글 제외)의 조회수·반응. 한 글의 인사이트를 못 읽어도 나머지는 계속."""
    now = now or datetime.now(timezone.utc)
    data = client.get(f'{client.user_id}/threads', {'fields': 'id,text,timestamp,is_reply', 'limit': str(limit)})
    stats = []
    for post in data.get('data', []):
        if post.get('is_reply') or not post.get('text') or not _recent(post.get('timestamp', ''), now):
            continue
        try:
            insight = client.get(f"{post['id']}/insights", {'metric': METRICS})
        except ThreadsError as e:
            print(f'[성과] 인사이트 실패 {post["id"]}: {e}')
            continue
        values = {m['name']: m['values'][0]['value'] for m in insight.get('data', []) if m.get('values')}
        stats.append({'id': post['id'], 'timestamp': post.get('timestamp', ''), 'text': post['text'],
                      **{k: int(values.get(k, 0)) for k in METRICS.split(',')}})
    return stats


def _line(row: dict[str, Any]) -> str:
    first = ' '.join(row['text'].split())[:SNIPPET_CHARS]
    return f"- 조회 {row['views']}회 · 좋아요 {row['likes']} · 댓글 {row['replies']}: {first}"


def build_brief(stats: Sequence[dict[str, Any]], today: str) -> str:
    """글이 MIN_POSTS개 미만이면 비교할 게 없어 빈 문자열."""
    if len(stats) < MIN_POSTS:
        return ''
    ranked = sorted(stats, key=lambda r: (r['views'], r['likes'] + r['replies']), reverse=True)
    top, bottom = ranked[:TOP], ranked[-BOTTOM:]
    return (f'\n\n## 우리 채널 최근 성과 (자동 갱신 {today})\n'
            '반응이 좋았던 글:\n' + '\n'.join(_line(r) for r in top) +
            '\n반응이 적었던 글:\n' + '\n'.join(_line(r) for r in bottom) +
            '\n좋았던 글의 소재·첫 문장 방식·형식을 참고해서 비슷하게 끌리는 글을 써. 문장을 그대로 베끼지는 마.\n')


def run_insights(client: ThreadsClient, now: datetime) -> RunResult:
    stats = fetch_stats(client, now)
    DATA.mkdir(parents=True, exist_ok=True)
    STATS_PATH.write_text(json.dumps({'updated_at': now.isoformat(timespec='seconds'), 'posts': stats},
                                     ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    brief = build_brief(stats, now.strftime('%Y-%m-%d'))
    BRIEF_PATH.write_text(brief, encoding='utf-8')
    views = sum(r['views'] for r in stats)
    return RunResult('success', f'성과 갱신: 글 {len(stats)}개, 조회 합계 {views}회')


def brief_text() -> str:
    try:
        return BRIEF_PATH.read_text(encoding='utf-8')
    except OSError:
        return ''
