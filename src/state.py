"""운영 상태(data/state.json): 자동 일시정지, 건너뛸 슬롯, 처리한 텔레그램 명령.

GitHub Variables의 PAUSED는 사람이 직접 바꾸는 스위치이고, 이 파일은 시스템(자동 중단 규칙·텔레그램 명령)이 바꾼다.
워크플로가 이 파일을 커밋하므로 다음 실행에도 이어진다.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path

DEFAULT_STATE_PATH = Path(__file__).resolve().parent.parent / 'data' / 'state.json'
MAX_REMEMBERED_UPDATES = 200


@dataclass(frozen=True)
class State:
    paused: bool = False
    pause_reason: str = ''
    skip_slots: tuple[str, ...] = ()
    resumed_from: str = ''  # 재개한 뒤의 슬롯만 연속 실패로 센다 (재개하자마자 다시 멈추지 않게)
    handled_updates: tuple[int, ...] = field(default_factory=tuple)


def load_state(path: Path | None = None) -> State:
    path = path or DEFAULT_STATE_PATH
    if not path.exists():
        return State()
    raw = json.loads(path.read_text(encoding='utf-8'))
    return State(
        paused=bool(raw.get('paused', False)),
        pause_reason=raw.get('pause_reason', ''),
        skip_slots=tuple(raw.get('skip_slots', ())),
        resumed_from=raw.get('resumed_from', ''),
        handled_updates=tuple(raw.get('handled_updates', ())),
    )


def save_state(state: State, path: Path | None = None) -> None:
    path = path or DEFAULT_STATE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {**asdict(state), 'skip_slots': list(state.skip_slots),
           'handled_updates': list(state.handled_updates[-MAX_REMEMBERED_UPDATES:])}
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(row, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def pause(state: State, reason: str) -> State:
    return replace(state, paused=True, pause_reason=reason)


def resume(state: State, from_slot: str = '') -> State:
    return replace(state, paused=False, pause_reason='', resumed_from=from_slot)


def skip(state: State, slot: str) -> State:
    return state if slot in state.skip_slots else replace(state, skip_slots=(*state.skip_slots, slot))


def mark_handled(state: State, update_ids: tuple[int, ...]) -> State:
    return replace(state, handled_updates=(*state.handled_updates, *update_ids))
