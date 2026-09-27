"""GitHub Actions 사전 점검: 지금 게시할 슬롯이 있는지 (외부 라이브러리 없이). 없으면 설치를 건너뛴다."""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src import history, schedule

DONE = (history.PUBLISHED, history.SKIPPED, 'PUBLISHING')


def is_due(now: datetime, times: tuple[schedule.Time, ...], past: tuple[history.HistoryEntry, ...]) -> bool:
    done = {e.slot for e in past if e.status in DONE}
    return any(schedule.slot_key(s) not in done for s in schedule.publishable_slots(now, times))


def main() -> int:
    try:
        due = is_due(datetime.now(timezone.utc), schedule.parse_times(os.environ.get('PUBLISH_TIMES')),
                     history.load_history())
    except (schedule.ScheduleError, ValueError) as e:
        print(f'[설정 오류] {e} → due=true')
        due = True
    print(f'[점검] 할 일 {"있음" if due else "없음"}')
    output = os.environ.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a', encoding='utf-8') as f:
            f.write(f'due={"true" if due else "false"}\n')
    return 0


if __name__ == '__main__':
    sys.exit(main())
